from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    project_id: str
    spanner_instance_id: str
    spanner_database_id: str
    pubsub_interaction_topic: str
    environment: str = "development"
    retrieval_deadline_sec: float = 0.15
    exploration_rate: float = 0.10


@lru_cache
def get_settings() -> Settings:
    return Settings()
