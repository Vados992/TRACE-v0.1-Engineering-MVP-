"""Bounded file adapters. These do not claim live access or full schema certification."""

import re
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EntityInput(StrictModel):
    key: str = Field(min_length=1, max_length=300)
    name: str = Field(min_length=1, max_length=1000)
    entity_type: Literal["PERSON", "ORGANIZATION", "PUBLIC_BODY", "CONTRACT", "POLICY"]
    scheme: str | None = Field(default=None, max_length=100)
    identifier: str | None = Field(default=None, max_length=300)
    country: str | None = Field(default=None, min_length=2, max_length=2)

    @model_validator(mode="after")
    def identifier_pair(self):
        if bool(self.scheme) != bool(self.identifier):
            raise ValueError("scheme and identifier must be supplied together")
        return self


class EdgeInput(StrictModel):
    subject: str
    object: str
    relation: Literal[
        "BENEFICIAL_OWNER_OF",
        "OWNS",
        "HOLDS_ROLE_IN",
        "AWARDED_TO",
        "ISSUED_CONTRACT",
        "SUPPLIER_OF",
        "INFLUENCES",
        "DECLARED_INTEREST_IN",
    ]
    valid_from: AwareDatetime | None = None
    valid_to: AwareDatetime | None = None
    amount: Decimal | None = Field(default=None, ge=0, max_digits=24, decimal_places=6)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    ownership_percent: Decimal | None = Field(default=None, ge=0, le=100)
    contract: str | None = None
    details: dict = Field(default_factory=dict)
    locator: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def coherent(self):
        if self.subject == self.object:
            raise ValueError("self relationship")
        if self.valid_from and self.valid_to and self.valid_to < self.valid_from:
            raise ValueError("invalid validity interval")
        if self.amount is not None and not self.currency:
            raise ValueError("amount requires currency")
        return self


class NormalizedImport(StrictModel):
    entities: list[EntityInput] = Field(min_length=1, max_length=2000)
    relationships: list[EdgeInput] = Field(default_factory=list, max_length=5000)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def references(self):
        keys = [e.key for e in self.entities]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate entity keys")
        for edge in self.relationships:
            if edge.subject not in keys or edge.object not in keys:
                raise ValueError("unresolved relationship reference")
            if edge.contract and edge.contract not in keys:
                raise ValueError("unresolved contract reference")
        return self


def instant(value):
    if not value:
        return None
    value = str(value)
    if len(value) == 10:
        value += "T00:00:00Z"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def parse_ocds(payload: dict) -> NormalizedImport:
    if str(payload.get("version")) != "1.1" or not isinstance(payload.get("releases"), list):
        raise ValueError("Expected OCDS 1.1 release package")
    entities, edges, warnings = {}, [], []
    for i, release in enumerate(payload["releases"]):
        ocid = release["ocid"]
        if not release.get("id") or not release.get("date"):
            raise ValueError("OCDS release requires id and date")
        party_keys = {}
        buyer_id = (release.get("buyer") or {}).get("id")
        for party in release.get("parties", []):
            key = f"{ocid}:party:{party['id']}"
            party_keys[party["id"]] = key
            identifier = party.get("identifier") or {}
            entities[key] = EntityInput(
                key=key,
                name=party.get("name") or identifier.get("legalName") or party["id"],
                entity_type="PUBLIC_BODY" if party["id"] == buyer_id else "ORGANIZATION",
                scheme=identifier.get("scheme"),
                identifier=identifier.get("id"),
            )
        for j, award in enumerate(release.get("awards", [])):
            # Canceled/pending awards do not become awarded relationships.
            if award.get("status") != "active":
                warnings.append(f"/releases/{i}/awards/{j}: non-active award skipped")
                continue
            key = f"{ocid}:award:{award['id']}"
            entities[key] = EntityInput(
                key=key, name=award.get("title") or key, entity_type="CONTRACT"
            )
            when = instant(award.get("date"))
            locator = f"/releases/{i}/awards/{j}"
            if buyer_id not in party_keys:
                raise ValueError("OCDS buyer must resolve to a party")
            buyer = party_keys[buyer_id]
            edges.append(
                EdgeInput(
                    subject=buyer,
                    object=key,
                    relation="ISSUED_CONTRACT",
                    valid_from=when,
                    valid_to=when,
                    locator=locator,
                )
            )
            suppliers = award.get("suppliers") or []
            value = award.get("value") or {}
            if len(suppliers) != 1:
                warnings.append(f"{locator}: consortium amount not allocated to suppliers")
            for supplier in suppliers:
                if supplier["id"] not in party_keys:
                    raise ValueError("OCDS supplier must resolve to a party")
                winner = party_keys[supplier["id"]]
                edges.append(
                    EdgeInput(
                        subject=winner,
                        object=key,
                        relation="SUPPLIER_OF",
                        valid_from=when,
                        valid_to=when,
                        locator=locator,
                    )
                )
                edges.append(
                    EdgeInput(
                        subject=buyer,
                        object=winner,
                        relation="AWARDED_TO",
                        valid_from=when,
                        valid_to=when,
                        amount=value.get("amount") if len(suppliers) == 1 else None,
                        currency=value.get("currency") if len(suppliers) == 1 else None,
                        contract=key,
                        locator=locator,
                    )
                )
    return NormalizedImport(
        entities=list(entities.values()), relationships=edges, warnings=warnings
    )


def parse_bods(payload) -> NormalizedImport:
    if not isinstance(payload, list):
        raise ValueError("Expected a BODS statement array")
    versions = {str((s.get("publicationDetails") or {}).get("bodsVersion")) for s in payload}
    if versions == {"0.4"}:
        return parse_bods04(payload)
    entities, edges, warnings = [], [], []
    for statement in payload:
        version = (statement.get("publicationDetails") or {}).get("bodsVersion")
        if version != "0.3":
            raise ValueError("Only explicit, unmixed BODS 0.3 or 0.4 statements supported")
        kind = statement["statementType"]
        if kind not in {"personStatement", "entityStatement"}:
            continue
        if kind == "personStatement":
            names = statement.get("names") or []
            name = names[0].get("fullName") if names else None
            if statement.get("personType") != "knownPerson" or not name:
                warnings.append(
                    f"{statement['statementID']}: unknown person retained only as raw evidence"
                )
                continue
        else:
            name = statement.get("name")
        identifiers = statement.get("identifiers") or []
        identifier = identifiers[0] if identifiers else {}
        entities.append(
            EntityInput(
                key=statement["statementID"],
                name=name or statement["statementID"],
                entity_type="PERSON" if kind == "personStatement" else "ORGANIZATION",
                scheme=identifier.get("scheme"),
                identifier=identifier.get("id"),
            )
        )
    keys = {e.key for e in entities}
    for i, statement in enumerate(payload):
        if statement["statementType"] != "ownershipOrControlStatement":
            continue
        subject = (statement.get("interestedParty") or {}).get("describedByPersonStatement")
        subject = subject or (statement.get("interestedParty") or {}).get(
            "describedByEntityStatement"
        )
        obj = (statement.get("subject") or {}).get("describedByEntityStatement")
        if subject not in keys or obj not in keys:
            warnings.append(
                f"{statement['statementID']}: unresolved/unknown owner; no inferred identity"
            )
            continue
        for j, interest in enumerate(statement.get("interests", [])):
            if interest.get("type") not in {
                "shareholding",
                "voting-rights",
                "other-influence-or-control",
            }:
                warnings.append(
                    f"{statement['statementID']}: unsupported interest type retained raw"
                )
                continue
            beneficial = interest.get("isBeneficialOwnershipOrControl") is True
            edges.append(
                EdgeInput(
                    subject=subject,
                    object=obj,
                    relation="BENEFICIAL_OWNER_OF" if beneficial else "OWNS",
                    valid_from=instant(interest.get("startDate")),
                    valid_to=instant(interest.get("endDate")),
                    ownership_percent=(interest.get("share") or {}).get("exact"),
                    locator=f"/{i}/interests/{j}",
                )
            )
    return NormalizedImport(entities=entities, relationships=edges, warnings=warnings)


def parse_bods04(payload) -> NormalizedImport:
    # v0.4 references recordId, not statementId. Preserve statement history in the vault.
    latest = {}
    for i, statement in enumerate(payload):
        record = statement["recordId"]
        rank = (
            statement.get("statementDate") or "",
            statement["publicationDetails"].get("publicationDate") or "",
            statement.get("recordStatus") == "closed",
        )
        if record not in latest or rank >= latest[record][0]:
            latest[record] = (rank, i, statement)
    entities, edges, warnings = [], [], []
    for _, i, statement in latest.values():
        kind, details = statement["recordType"], statement.get("recordDetails") or {}
        if kind not in {"entity", "person"}:
            continue
        if kind == "person":
            names = details.get("names") or []
            name = names[0].get("fullName") if names else None
            if details.get("personType") != "knownPerson" or not name:
                warnings.append(f"/{i}: unknown person retained as raw evidence")
                continue
        else:
            name = details.get("name")
        identifier = next(
            (v for v in details.get("identifiers", []) if v.get("scheme") and v.get("id")), {}
        )
        # Only actual registry entity identifiers establish cross-source identity.
        entities.append(
            EntityInput(
                key=statement["recordId"],
                name=name or statement["recordId"],
                entity_type="PERSON" if kind == "person" else "ORGANIZATION",
                scheme=identifier.get("scheme"),
                identifier=identifier.get("id"),
            )
        )
    keys = {e.key for e in entities}
    for _, i, statement in latest.values():
        if statement["recordType"] != "relationship":
            continue
        subject = (statement.get("recordDetails") or {}).get("subject")
        # A register identifier expressly cited by the publisher is a valid minimal node.
        # Do not invent a legal name or a missing entity statement.
        if (
            isinstance(subject, str)
            and subject not in keys
            and re.fullmatch(r"GB-COH-[A-Z0-9]{8}", subject)
        ):
            entities.append(
                EntityInput(
                    key=subject,
                    name=subject,
                    entity_type="ORGANIZATION",
                    scheme="GB-COH",
                    identifier=subject[7:],
                )
            )
            keys.add(subject)
            warnings.append(
                f"/{i}: subject is a registry reference only; entity name/metadata not supplied"
            )
    for _, i, statement in latest.values():
        if statement["recordType"] != "relationship":
            continue
        details = statement.get("recordDetails") or {}
        owner, subject = details.get("interestedParty"), details.get("subject")
        if not isinstance(owner, str) or owner not in keys or subject not in keys:
            warnings.append(f"/{i}: unresolved owner; no inferred identity")
            continue
        if statement.get("recordStatus") == "closed":
            warnings.append(f"/{i}: closed record retained raw; no active edge inferred")
            continue
        groups = {}
        for interest in details.get("interests", []):
            if interest.get("type") not in {
                "shareholding",
                "votingRights",
                "appointmentOfBoard",
                "otherInfluenceOrControl",
                "rightsToSurplusAssets",
            }:
                warnings.append(f"/{i}: unsupported interest type retained raw")
                continue
            group = (
                interest.get("beneficialOwnershipOrControl") is True,
                interest.get("startDate"),
                interest.get("endDate"),
            )
            groups.setdefault(group, []).append(interest)
        for (beneficial, start, end), interests in groups.items():
            exact = [
                (v.get("share") or {}).get("exact")
                for v in interests
                if v.get("type") == "shareholding"
            ]
            edges.append(
                EdgeInput(
                    subject=owner,
                    object=subject,
                    relation="BENEFICIAL_OWNER_OF" if beneficial else "OWNS",
                    valid_from=instant(start),
                    valid_to=instant(end),
                    ownership_percent=exact[0] if len(exact) == 1 else None,
                    locator=f"/{i}/recordDetails/interests",
                    details={
                        "bods_version": "0.4",
                        "statement_id": statement["statementId"],
                        "interests": interests,
                        "record_status": statement["recordStatus"],
                    },
                )
            )
    return NormalizedImport(entities=entities, relationships=edges, warnings=warnings)


def parse_procurement_export(payload: dict) -> NormalizedImport:
    # Deliberately an operator mapping contract, not a pretend native PPDS/TED API schema.
    if payload.get("schema") != "trace-procurement-export/1":
        raise ValueError("TED/PPDS file adapter expects trace-procurement-export/1")
    entities, edges = {}, []
    for i, notice in enumerate(payload["notices"]):
        if notice.get("status") != "AWARDED":
            continue
        for field, kind in [("buyer", "PUBLIC_BODY"), ("supplier", "ORGANIZATION")]:
            item = notice[field]
            key = f"{item['scheme']}:{item['id']}"
            entities[key] = EntityInput(
                key=key,
                name=item["name"],
                entity_type=kind,
                scheme=item["scheme"],
                identifier=item["id"],
            )
        buyer, supplier = notice["buyer"], notice["supplier"]
        contract_key = str(notice["id"])
        entities[contract_key] = EntityInput(
            key=contract_key, name=notice.get("title") or contract_key, entity_type="CONTRACT"
        )
        when = instant(notice.get("decision_date"))
        edges.append(
            EdgeInput(
                subject=f"{buyer['scheme']}:{buyer['id']}",
                object=f"{supplier['scheme']}:{supplier['id']}",
                relation="AWARDED_TO",
                amount=notice.get("amount"),
                currency=notice.get("currency"),
                valid_from=when,
                valid_to=when,
                contract=contract_key,
                locator=f"/notices/{i}",
            )
        )
    return NormalizedImport(
        entities=list(entities.values()),
        relationships=edges,
        warnings=["Normalized export contract; no official live PPDS integration"],
    )


ADAPTERS = {
    "ocds": parse_ocds,
    "bods": parse_bods,
    "ted": parse_procurement_export,
    "ppds": parse_procurement_export,
    "trace": NormalizedImport.model_validate,
}


def parse_import(format: str, payload) -> NormalizedImport:
    if format not in ADAPTERS:
        raise ValueError("Unsupported import format")
    try:
        return ADAPTERS[format](payload)
    except (KeyError, TypeError, IndexError, AttributeError) as exc:
        raise ValueError("Malformed or unresolved import fields") from exc
