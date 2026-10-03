from typing import Any
from uuid import UUID

from .entity_resolution.normalize import normalize_identifier, normalize_org_name
from .ingest_repository import (
    ensure_claim_with_source,
    ensure_document_version,
    ensure_entity,
    ensure_identifier,
)
from .parsers import extract_html_title, parse_gleif_record


async def canonicalize_gleif(
    conn,
    payload: dict[str, Any],
    source_record_id: UUID,
) -> UUID:
    record = parse_gleif_record(payload)
    entity_id = await ensure_entity(
        conn,
        entity_type="ORGANIZATION",
        canonical_name=record["legal_name"],
        normalized_name=normalize_org_name(record["legal_name"]),
        jurisdiction_code=record["jurisdiction"],
        identifier_scheme="LEI",
        identifier_value=record["lei"],
    )
    await ensure_identifier(
        conn,
        entity_id=entity_id,
        scheme="LEI",
        identifier_value=record["lei"],
        country_code=record["jurisdiction"],
        verified=True,
        source_record_id=source_record_id,
    )

    registered_as = normalize_identifier(record.get("registered_as"))
    if registered_as:
        await ensure_identifier(
            conn,
            entity_id=entity_id,
            scheme="NATIONAL_COMPANY_NUMBER",
            identifier_value=registered_as,
            country_code=record["jurisdiction"],
            verified=True,
            source_record_id=source_record_id,
        )
        authority_id = record.get("registration_authority_id")
        if authority_id:
            await ensure_identifier(
                conn,
                entity_id=entity_id,
                scheme=f"GLEIF_RA:{authority_id}",
                identifier_value=registered_as,
                country_code=record["jurisdiction"],
                verified=True,
                source_record_id=source_record_id,
            )

    await ensure_claim_with_source(
        conn,
        subject_entity_id=entity_id,
        predicate="IDENTIFIED_BY",
        literal_value={"scheme": "LEI", "value": record["lei"]},
        claim_type="FACT",
        verification_status="VERIFIED_AUTHORITATIVE",
        source_record_id=source_record_id,
        evidence_strength="E1",
        extraction_method="GLEIF_JSON_API",
    )
    return entity_id


async def canonicalize_eurlex(
    conn,
    celex: str,
    html: str,
    canonical_uri: str,
    content_hash: str,
    object_uri: str,
    source_record_id: UUID,
) -> tuple[UUID, UUID]:
    title = extract_html_title(html) or f"EUR-Lex {celex}"
    entity_id = await ensure_entity(
        conn,
        entity_type="LEGAL_ACT",
        canonical_name=title,
        normalized_name=" ".join(title.casefold().split()),
        jurisdiction_code="EU",
        identifier_scheme="CELEX",
        identifier_value=celex,
    )
    await ensure_identifier(
        conn,
        entity_id=entity_id,
        scheme="CELEX",
        identifier_value=celex,
        country_code="EU",
        verified=True,
        source_record_id=source_record_id,
    )
    document_id, version_id = await ensure_document_version(
        conn,
        source_code="EURLEX",
        external_document_id=celex,
        document_type="LEGAL_ACT",
        title=title,
        issuer_entity_id=None,
        canonical_uri=canonical_uri,
        content_hash=content_hash,
        object_uri=object_uri,
        mime_type="text/html",
        language="eng",
        parser_version="trace-v0.3",
    )
    await ensure_claim_with_source(
        conn,
        subject_entity_id=entity_id,
        predicate="PUBLISHED_AS",
        literal_value={"celex": celex, "document_id": str(document_id)},
        claim_type="FACT",
        verification_status="VERIFIED_PRIMARY",
        source_record_id=source_record_id,
        evidence_strength="E0",
        extraction_method="EURLEX_CELLAR",
        document_version_id=version_id,
    )
    return entity_id, document_id
