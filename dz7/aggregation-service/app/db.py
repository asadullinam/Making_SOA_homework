from __future__ import annotations

from urllib.parse import urlparse

import clickhouse_connect
from sqlalchemy import create_engine

from app.config import Settings


def create_clickhouse_client(settings: Settings):
    parsed = urlparse(settings.clickhouse_url)
    return clickhouse_connect.get_client(
        host=parsed.hostname,
        port=parsed.port or 8123,
        username=settings.clickhouse_user,
        password=settings.clickhouse_password,
        database=settings.clickhouse_database,
    )


def create_postgres_engine(settings: Settings):
    return create_engine(settings.postgres_dsn, future=True, pool_pre_ping=True)
