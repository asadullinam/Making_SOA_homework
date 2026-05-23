from __future__ import annotations

import json
import os
import time
import uuid
from datetime import date, datetime, timezone

import clickhouse_connect
import psycopg
import requests

PRODUCER_URL = os.environ["PRODUCER_URL"]
AGGREGATION_URL = os.environ["AGGREGATION_URL"]
CLICKHOUSE_URL = os.environ["CLICKHOUSE_URL"]
CLICKHOUSE_USER = os.environ["CLICKHOUSE_USER"]
CLICKHOUSE_PASSWORD = os.environ["CLICKHOUSE_PASSWORD"]
CLICKHOUSE_DATABASE = os.environ["CLICKHOUSE_DATABASE"]
POSTGRES_HOST = os.environ["POSTGRES_HOST"]
POSTGRES_PORT = int(os.environ["POSTGRES_PORT"])
POSTGRES_DB = os.environ["POSTGRES_DB"]
POSTGRES_USER = os.environ["POSTGRES_USER"]
POSTGRES_PASSWORD = os.environ["POSTGRES_PASSWORD"]
PROMETHEUS_URL = os.environ["PROMETHEUS_URL"]


def create_clickhouse_client():
    host = CLICKHOUSE_URL.replace("http://", "").split(":")[0]
    port = int(CLICKHOUSE_URL.rsplit(":", maxsplit=1)[1])
    return clickhouse_connect.get_client(
        host=host,
        port=port,
        username=CLICKHOUSE_USER,
        password=CLICKHOUSE_PASSWORD,
        database=CLICKHOUSE_DATABASE,
    )


def postgres_connection():
    return psycopg.connect(
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        dbname=POSTGRES_DB,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
    )


def post_event(payload: dict[str, object]) -> dict[str, object]:
    response = requests.post(f"{PRODUCER_URL}/events", json=payload, timeout=30)
    response.raise_for_status()
    return response.json()


def wait_for_clickhouse_event(event_id: str, timeout_seconds: int = 60) -> tuple:
    client = create_clickhouse_client()
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        rows = client.query(
            """
            SELECT event_id, user_id, movie_id, event_type, progress_seconds, event_date
            FROM movie_events
            WHERE event_id = %(event_id)s
            """,
            parameters={"event_id": event_id},
        ).result_rows
        if rows:
            return rows[0]
        time.sleep(2)
    raise AssertionError(f"Event {event_id} did not arrive in ClickHouse within {timeout_seconds} seconds")


def wait_for_prometheus_query(query: str, timeout_seconds: int = 60) -> dict:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        response = requests.get(
            f"{PROMETHEUS_URL}/api/v1/query",
            params={"query": query},
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        if payload["status"] == "success" and payload["data"]["result"]:
            return payload
        time.sleep(2)
    raise AssertionError(f"Prometheus query returned no data: {query}")


def build_event_payload(event_type: str, target_time: datetime, *, user_id: str, session_id: str, movie_id: str, progress_seconds: int | None = None) -> dict[str, object]:
    return {
        "event_id": str(uuid.uuid4()),
        "user_id": user_id,
        "movie_id": movie_id,
        "event_type": event_type,
        "timestamp": target_time.isoformat(),
        "device_type": "DESKTOP",
        "session_id": session_id,
        "progress_seconds": progress_seconds,
    }


def cleanup_date(target_date: date, user_id: str) -> None:
    client = create_clickhouse_client()
    statements = [
        "ALTER TABLE movie_events DELETE WHERE event_date = %(target_date)s AND user_id = %(user_id)s",
        "ALTER TABLE daily_dau DELETE WHERE metric_date = %(target_date)s",
        "ALTER TABLE daily_avg_watch_time DELETE WHERE metric_date = %(target_date)s",
        "ALTER TABLE daily_top_movies DELETE WHERE metric_date = %(target_date)s",
        "ALTER TABLE daily_conversion DELETE WHERE metric_date = %(target_date)s",
        "ALTER TABLE daily_retention DELETE WHERE metric_date = %(target_date)s",
        "ALTER TABLE device_distribution DELETE WHERE metric_date = %(target_date)s",
        "ALTER TABLE retention_cohorts DELETE WHERE cohort_date = %(target_date)s",
    ]
    for statement in statements:
        try:
            client.command(statement, parameters={"target_date": target_date, "user_id": user_id})
        except Exception:
            pass

    with postgres_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM daily_metrics WHERE metric_date = %s", (target_date,))
        connection.commit()


def write_json_artifact(path: str, payload: dict[str, object]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2, default=str)
