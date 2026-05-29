from __future__ import annotations

from datetime import date, datetime, timezone

import requests

from helpers import (
    AGGREGATION_URL,
    build_event_payload,
    cleanup_date,
    post_event,
    postgres_connection,
    wait_for_clickhouse_event,
)


def test_e2e_event_to_aggregates_and_postgres_storage() -> None:
    target_date = date(2030, 1, 2)
    user_id = "e2e-user-2030-01-02"
    session_id = "e2e-session-2030-01-02"
    movie_id = "e2e-movie-1"

    cleanup_date(target_date, user_id)
    try:
        timestamps = [
            datetime(2030, 1, 2, 10, 0, tzinfo=timezone.utc),
            datetime(2030, 1, 2, 10, 5, tzinfo=timezone.utc),
        ]
        payloads = [
            build_event_payload(
                "VIEW_STARTED",
                timestamps[0],
                user_id=user_id,
                session_id=session_id,
                movie_id=movie_id,
                progress_seconds=0,
            ),
            build_event_payload(
                "VIEW_FINISHED",
                timestamps[1],
                user_id=user_id,
                session_id=session_id,
                movie_id=movie_id,
                progress_seconds=5400,
            ),
        ]

        for payload in payloads:
            response = post_event(payload)
            assert response["event_id"] == payload["event_id"]
            wait_for_clickhouse_event(payload["event_id"])

        aggregate_response = requests.post(
            f"{AGGREGATION_URL}/aggregate",
            params={"target_date": target_date.isoformat()},
            timeout=60,
        )
        aggregate_response.raise_for_status()
        body = aggregate_response.json()
        assert body["status"] == "ok"
        assert body["metric_date"] == target_date.isoformat()
        assert body["processed_rows"] >= 2

        with postgres_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT metric_name, metric_value
                    FROM daily_metrics
                    WHERE metric_date = %s
                    ORDER BY metric_name
                    """,
                    (target_date,),
                )
                rows = cursor.fetchall()

        metrics = {name: value for name, value in rows}
        assert metrics["DAU"] == 1
        assert metrics["VIEW_STARTED"] >= 1
        assert metrics["VIEW_FINISHED"] >= 1
        assert metrics["CONVERSION_RATE"] == 1
    finally:
        cleanup_date(target_date, user_id)
