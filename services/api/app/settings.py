import hashlib
import json
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_KEYS = {
    hashlib.sha256(f"trace-dev-{role}-only".encode()).hexdigest(): {
        "subject": f"demo-{role}",
        "role": role,
    }
    for role in ("analyst", "reviewer", "publisher", "admin")
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    trace_env: Literal["dev", "desktop", "production", "test"] = "dev"
    auth_mode: Literal["api_key", "oidc", "hybrid"] = "api_key"
    oidc_issuer: str = ""
    oidc_audience: str = ""
    oidc_jwks_url: str = ""
    oidc_subject_claim: str = "sub"
    oidc_roles_claim: str = "groups"
    oidc_role_map_json: str = "{}"
    oidc_jwks_cache_seconds: int = 300
    oidc_clock_skew_seconds: int = 60
    auth_keys_json: str = json.dumps(DEV_KEYS)
    allowed_hosts: list[str] = ["localhost", "127.0.0.1", "testserver", "[::1]"]
    max_request_bytes: int = 5 * 1024 * 1024
    graph_max_expansions: int = 5000
    graph_timeout_seconds: float = 10.0
    db_pool_min_size: int = 1
    db_pool_max_size: int = 10
    db_pool_timeout_seconds: float = 10.0
    db_statement_timeout_ms: int = 15000
    database_url: str = "postgresql://trace:trace_dev_only@localhost:5432/trace"
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "trace_graph_dev_only"

    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "trace_minio"
    minio_secret_key: str = "trace_minio_dev_only"
    minio_bucket: str = "trace-evidence"
    minio_secure: bool = False
    evidence_backend: Literal["s3", "filesystem"] = "s3"
    evidence_directory: str = "/var/lib/trace/evidence"
    redis_url: str = "redis://redis:6379/0"
    opensearch_url: str = "http://opensearch:9200"

    ted_base_url: str = "https://api.ted.europa.eu"
    gleif_base_url: str = "https://api.gleif.org/api/v1"
    cellar_base_url: str = "https://publications.europa.eu/resource/celex"
    unsdg_base_url: str = "https://unstats.un.org/SDGAPI"
    http_timeout_seconds: float = 30.0
    http_max_response_bytes: int = 20 * 1024 * 1024
    cellar_max_response_bytes: int = 64 * 1024 * 1024
    ocds_base_url: str = "https://www.find-tender.service.gov.uk/api/1.0/ocdsReleasePackages"
    openownership_archive_url: str = (
        "https://oo-bodsdata.s3.amazonaws.com/data/uk_version_0_4/json.zip"
    )
    bods_dataset_url: str = ""
    ppds_dataset_url: str = ""
    bods_token_env: str | None = None
    ppds_token_env: str | None = None


settings = Settings()
