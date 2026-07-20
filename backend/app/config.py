from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    research_gateway_mode: str = "local"
    retrieval_backend: str = "demo"
    embedding_backend: str = "hash"
    document_structure_backend: str = "gold"
    evidence_graph_backend: str = "gold"
    private_pdf_preview_enabled: bool = False
    private_pdf_preview_root: str = ""
    assistant_backend: str = "offline"
    project_claim_backend: str = "memory"
    experiment_run_backend: str = "memory"
    cors_origins: str = "http://localhost:5173"
    mysql_url: str = "mysql+pymysql://kd_agent:kd_agent_local@127.0.0.1:3306/kd_agent"
    neo4j_uri: str = "bolt://127.0.0.1:7687"
    neo4j_username: str = "neo4j"
    neo4j_password: str = "kd_agent_graph_local"
    astron_agent_api_url: str = (
        "https://xingchen-api.xf-yun.com/workflow/v1/chat/completions"
    )
    astron_agent_api_key: str = ""
    astron_agent_api_secret: str = ""
    astron_agent_flow_id: str = ""
    astron_agent_model_label: str = "configured-in-workflow"
    assistant_model_timeout_seconds: float = 30.0

    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [part.strip() for part in self.cors_origins.split(",") if part.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
