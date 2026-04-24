from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=False)

    app_host: str = "0.0.0.0"
    app_port: int = 8001
    clickhouse_url: str
    clickhouse_user: str
    clickhouse_password: str
    clickhouse_database: str = "movie_analytics"
    postgres_dsn: str
    aggregation_schedule_minutes: int = 5
    export_schedule_minutes: int = 10
    minio_endpoint: str
    minio_access_key: str
    minio_secret_key: str
    minio_bucket: str = "movie-analytics"
    minio_secure: bool = False


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
