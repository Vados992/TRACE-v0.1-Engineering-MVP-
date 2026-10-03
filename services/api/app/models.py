from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, Field, model_validator

EntityType = Literal[
    "PERSON",
    "ORGANIZATION",
    "PUBLIC_BODY",
    "POLICY",
    "LEGAL_ACT",
    "PROGRAMME",
    "CONTRACT",
    "TENDER",
    "AWARD",
    "GRANT",
    "PAYMENT",
    "FUND",
    "ASSET",
    "MEETING",
    "LOBBY_ACTIVITY",
    "ROLE",
    "DECLARATION",
    "EVENT",
    "DOCUMENT",
    "SOURCE",
    "JURISDICTION",
    "SECTOR",
]


class EntitySummary(BaseModel):
    id: UUID
    entity_type: str
    canonical_name: str
    jurisdiction_code: str | None = None
    status: str


class Identifier(BaseModel):
    scheme: str
    identifier_value: str
    country_code: str | None = None
    verified: bool = False


class EntityDetail(EntitySummary):
    identifiers: list[Identifier] = Field(default_factory=list)


class ResolutionRecord(BaseModel):
    entity_type: Literal["PERSON", "ORGANIZATION", "PUBLIC_BODY"]
    name: str
    jurisdiction_code: str | None = None
    address: str | None = None
    identifiers: dict[str, str] = Field(default_factory=dict)
    directors: list[str] = Field(default_factory=list)
    incorporation_date: date | None = None


class ResolutionRequest(BaseModel):
    left: ResolutionRecord
    right: ResolutionRecord


class ResolutionResult(BaseModel):
    score: float
    decision: Literal["AUTO_MERGE", "HUMAN_REVIEW", "KEEP_SEPARATE"]
    features: dict[str, float]
    reasons: list[str]


class TedSearchRequest(BaseModel):
    query: str = Field(min_length=1)
    fields: list[str] = Field(
        default_factory=lambda: [
            "publication-number",
            "notice-title",
            "procedure-identifier",
            "publication-date",
            "buyer-name",
            "buyer-identifier",
            "buyer-country",
            "winner-name",
            "winner-identifier",
            "winner-country",
            "winner-decision-date",
            "result-value-notice",
            "result-value-cur-notice",
        ]
    )
    page: int = Field(default=1, ge=1)
    limit: int = Field(default=25, ge=1, le=250)
    pagination_mode: Literal["PAGE_NUMBER", "ITERATION"] = "PAGE_NUMBER"
    iteration_next_token: str | None = None


class ExternalDocument(BaseModel):
    source: str
    external_id: str
    retrieved_at: datetime
    content_type: str | None = None
    sha256: str
    canonical_uri: str
    payload: Any | None = None


class IngestResult(BaseModel):
    source: str
    external_id: str
    status: Literal["SUCCEEDED", "PARTIAL", "FAILED"]
    source_record_id: UUID | None = None
    raw_artifact_id: UUID | None = None
    entity_ids: list[UUID] = Field(default_factory=list)
    document_ids: list[UUID] = Field(default_factory=list)
    sha256: str | None = None
    notes: list[str] = Field(default_factory=list)


class GraphPathRequest(BaseModel):
    source_entity_id: UUID
    target_entity_id: UUID
    from_time: AwareDatetime | None = None
    to_time: AwareDatetime | None = None
    max_depth: int = Field(default=6, ge=1, le=6)
    limit: int = Field(default=10, ge=1, le=50)
    verified_only: bool = True

    @model_validator(mode="after")
    def interval(self):
        if self.from_time and self.to_time and self.from_time > self.to_time:
            raise ValueError("from_time must precede to_time")
        return self


class InvestigationRequest(GraphPathRequest):
    query_text: str | None = None


class InvestigationResult(BaseModel):
    investigation_id: UUID
    status: Literal["SUCCEEDED", "FAILED"]
    source_entity: EntityDetail
    target_entity: EntityDetail
    paths: list[dict[str, Any]] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class RelationshipBuildResult(BaseModel):
    layer: str
    status: Literal["SUCCEEDED", "PARTIAL", "FAILED"]
    source_record_ids: list[UUID] = Field(default_factory=list)
    entity_ids: list[UUID] = Field(default_factory=list)
    relationship_ids: list[UUID] = Field(default_factory=list)
    money_flow_ids: list[UUID] = Field(default_factory=list)
    conflicts: int = 0
    notes: list[str] = Field(default_factory=list)


class LobbyingObservationInput(BaseModel):
    transparency_id: str = Field(min_length=1)
    registrant_name: str = Field(min_length=1)
    registrant_country: str | None = None
    institution_name: str | None = None
    meeting_date: date | None = None
    subject: str | None = None
    policy_celex: str | None = None
    declared_budget_min: Decimal | None = None
    declared_budget_max: Decimal | None = None
    currency: str | None = None
    source_external_id: str = Field(min_length=1)


class LobbyingImportRequest(BaseModel):
    records: list[LobbyingObservationInput] = Field(min_length=1, max_length=500)


class PolicyLifecycleRequest(BaseModel):
    celex: str = Field(min_length=4)


class ReconciliationSummary(BaseModel):
    open_entity_candidates: int
    open_relationship_conflicts: int
    source_mappings: int
    relationship_observations: int
