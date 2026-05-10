from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_host: str = "0.0.0.0"
    app_port: int = 8001
    kafka_bootstrap_servers: str = "localhost:19092,localhost:29092"
    kafka_topic: str = "warehouse-events"
    kafka_dlq_topic: str = "warehouse-events-dlq"
    kafka_consumer_group: str = "warehouse-state-consumer"
    schema_registry_url: str = "http://localhost:8081"
    cassandra_contact_points: str = "localhost"
    cassandra_port: int = 9042
    cassandra_keyspace: str = "warehouse"
    cassandra_read_consistency: str = "QUORUM"
    cassandra_write_consistency: str = "QUORUM"

    @property
    def cassandra_hosts(self) -> list[str]:
        return [host.strip() for host in self.cassandra_contact_points.split(",") if host.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
