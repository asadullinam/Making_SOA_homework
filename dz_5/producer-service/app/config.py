from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=False)

    app_host: str = "0.0.0.0"
    app_port: int = 8000
    kafka_bootstrap_servers: str
    schema_registry_url: str
    kafka_topic: str = "movie-events"
    kafka_acks: str = "all"
    producer_partition_key: str = "user_id"
    generator_enabled: bool = False
    generator_interval_seconds: float = 1.5


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
