from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


EntityType = Literal[
    "PERSON", "ORGANIZATION", "PUBLIC_BODY", "POLICY", "LEGAL_ACT", "PROGRAMME",
    "CONTRACT", "TENDER", "AWARD", "GRANT", "PAYMENT", "FUND", "ASSET", "MEETING",
    "LOBBY_ACTIVITY", "ROLE", "DECLARATION", "EVENT", "DOCUMENT", "SOURCE",
    "JURISDICTION", "SECTOR",
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
        default_factory=lambda: ["publication-number", "notice-title", "buyer-name"]
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
    from_time: datetime | None = None
    to_time: datetime | None = None
    max_depth: int = Field(default=6, ge=1, le=8)
    limit: int = Field(default=10, ge=1, le=50)
    verified_only: bool = True


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
