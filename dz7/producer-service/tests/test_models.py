from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.models import DeviceType, EventType, MovieEventIn


def test_search_event_requires_search_query() -> None:
    with pytest.raises(ValueError):
        MovieEventIn(
            user_id="user-1",
            movie_id="movie-1",
            event_type=EventType.SEARCHED,
            timestamp=datetime.now(timezone.utc),
            device_type=DeviceType.DESKTOP,
            session_id="session-1",
        )


def test_watch_event_normalizes_timestamp_and_requires_progress() -> None:
    event = MovieEventIn(
        user_id="user-1",
        movie_id="movie-1",
        event_type=EventType.VIEW_FINISHED,
        timestamp=datetime(2030, 1, 1, 12, 0, 0),
        device_type=DeviceType.TV,
        session_id="session-1",
        progress_seconds=42,
    )

    assert event.timestamp.tzinfo == timezone.utc
    assert event.progress_seconds == 42
