from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    trace_env: str = "dev"
    database_url: str = "postgresql://trace:trace_dev_only@localhost:5432/trace"
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "trace_graph_dev_only"
    ted_base_url: str = "https://api.ted.europa.eu"
    gleif_base_url: str = "https://api.gleif.org/api/v1"
    cellar_base_url: str = "https://publications.europa.eu/resource/celex"
    http_timeout_seconds: float = 30.0


settings = Settings()
