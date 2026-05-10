from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_host: str = "0.0.0.0"
    app_port: int = 8000
    kafka_bootstrap_servers: str = "localhost:19092,localhost:29092"
    kafka_topic: str = "warehouse-events"
    schema_registry_url: str = "http://localhost:8081"
    kafka_acks: str = "all"


@lru_cache
def get_settings() -> Settings:
    return Settings()
