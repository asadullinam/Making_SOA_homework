from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timezone

import clickhouse_connect
import requests

PRODUCER_URL = os.environ["PRODUCER_URL"]
CLICKHOUSE_URL = os.environ["CLICKHOUSE_URL"]
CLICKHOUSE_USER = os.environ["CLICKHOUSE_USER"]
CLICKHOUSE_PASSWORD = os.environ["CLICKHOUSE_PASSWORD"]
CLICKHOUSE_DATABASE = os.environ["CLICKHOUSE_DATABASE"]


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


def test_event_flows_from_producer_to_clickhouse():
    event_id = str(uuid.uuid4())
    payload = {
        "event_id": event_id,
        "user_id": "integration-user",
        "movie_id": "integration-movie",
        "event_type": "VIEW_FINISHED",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "device_type": "DESKTOP",
        "session_id": f"test-session-{event_id}",
        "progress_seconds": 3210,
    }

    response = requests.post(f"{PRODUCER_URL}/events", json=payload, timeout=30)
    response.raise_for_status()
    body = response.json()
    assert body["event_id"] == event_id

    client = create_clickhouse_client()
    deadline = time.time() + 60
    while time.time() < deadline:
        rows = client.query(
            """
            SELECT event_id, user_id, movie_id, event_type, progress_seconds
            FROM movie_events
            WHERE event_id = %(event_id)s
            """,
            parameters={"event_id": event_id},
        ).result_rows
        if rows:
            assert rows[0][1] == payload["user_id"]
            assert rows[0][2] == payload["movie_id"]
            assert rows[0][3] == payload["event_type"]
            assert rows[0][4] == payload["progress_seconds"]
            return
        time.sleep(2)

    raise AssertionError("Event did not arrive in ClickHouse within 60 seconds")
