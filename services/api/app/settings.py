from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Literal


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    trace_env: str = "dev"
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
    http_timeout_seconds: float = 30.0


settings = Settings()
