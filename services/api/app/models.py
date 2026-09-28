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
    identifiers: list[Identifier] = []


class ResolutionRecord(BaseModel):
    entity_type: Literal["PERSON", "ORGANIZATION", "PUBLIC_BODY"]
    name: str
    jurisdiction_code: str | None = None
    address: str | None = None
    identifiers: dict[str, str] = {}
    directors: list[str] = []
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
    fields: list[str] = Field(default_factory=lambda: ["publication-number", "notice-title", "buyer-name"])
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
