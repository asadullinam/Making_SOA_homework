from __future__ import annotations

from datetime import datetime, timezone

from helpers import build_event_payload, post_event, wait_for_clickhouse_event


def test_event_flows_from_producer_to_clickhouse() -> None:
    payload = build_event_payload(
        "VIEW_FINISHED",
        datetime.now(timezone.utc),
        user_id="integration-user",
        session_id="integration-session",
        movie_id="integration-movie",
        progress_seconds=3210,
    )

    body = post_event(payload)
    assert body["event_id"] == payload["event_id"]

    event = wait_for_clickhouse_event(payload["event_id"])
    assert str(event[0]) == payload["event_id"]
    assert event[1] == payload["user_id"]
    assert event[2] == payload["movie_id"]
    assert event[3] == payload["event_type"]
    assert event[4] == payload["progress_seconds"]
