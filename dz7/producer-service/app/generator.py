from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.kafka_client import KafkaPublisher
from app.models import DeviceType, EventType, MovieEventIn

logger = logging.getLogger(__name__)

USERS = [f"user-{index}" for index in range(1, 201)]
MOVIES = [f"movie-{index}" for index in range(1, 81)]
SEARCH_TERMS = [
    "sci-fi",
    "comedy",
    "drama",
    "oscar winners",
    "crime thriller",
    "family movies",
    "marvel",
    "christopher nolan",
    "animated movies",
    "romantic comedies",
    "series to binge",
    "top imdb",
    "new releases",
    "80s classics",
    "detective series",
    "space opera",
    "historical drama",
    "cyberpunk",
    "korean thriller",
    "anime",
]


def _session_events() -> list[tuple[EventType, int | None]]:
    finish_progress = random.randint(3_600, 8_000)
    pause_progress = random.randint(120, min(1_800, finish_progress - 300))
    resume_progress = min(finish_progress - 60, pause_progress + random.randint(60, 900))
    sequence = [(EventType.VIEW_STARTED, 0)]

    if random.random() < 0.8:
        sequence.extend(
            [
                (EventType.VIEW_PAUSED, pause_progress),
                (EventType.VIEW_RESUMED, resume_progress),
            ]
        )
    if random.random() < 0.25:
        second_pause = min(finish_progress - 30, resume_progress + random.randint(90, 1_200))
        second_resume = min(finish_progress - 10, second_pause + random.randint(30, 600))
        sequence.extend(
            [
                (EventType.VIEW_PAUSED, second_pause),
                (EventType.VIEW_RESUMED, second_resume),
            ]
        )

    if random.random() < 0.72:
        sequence.append((EventType.VIEW_FINISHED, finish_progress))
    return sequence


def build_synthetic_sequence() -> list[MovieEventIn]:
    user_id = random.choice(USERS)
    movie_id = random.choice(MOVIES)
    device_type = random.choice(list(DeviceType))
    session_id = f"session-{uuid4()}"
    base_time = datetime.now(timezone.utc)

    events: list[MovieEventIn] = []
    current_time = base_time
    for event_type, progress in _session_events():
        events.append(
            MovieEventIn(
                user_id=user_id,
                movie_id=movie_id,
                event_type=event_type,
                timestamp=current_time,
                device_type=device_type,
                session_id=session_id,
                progress_seconds=progress,
            )
        )
        current_time += timedelta(seconds=random.randint(20, 180))

    if random.random() < 0.55:
        events.append(
            MovieEventIn(
                user_id=user_id,
                movie_id=movie_id,
                event_type=EventType.LIKED,
                timestamp=current_time + timedelta(seconds=random.randint(15, 180)),
                device_type=device_type,
                session_id=session_id,
                progress_seconds=events[-1].progress_seconds,
            )
        )

    if random.random() < 0.65:
        events.insert(
            0,
            MovieEventIn(
                user_id=user_id,
                movie_id=movie_id,
                event_type=EventType.SEARCHED,
                timestamp=base_time - timedelta(seconds=30),
                device_type=device_type,
                session_id=session_id,
                progress_seconds=0,
                search_query=random.choice(SEARCH_TERMS),
            ),
        )

    return events


async def generator_loop(publisher: KafkaPublisher, interval_seconds: float) -> None:
    while True:
        batch = build_synthetic_sequence()
        for event in batch:
            publisher.safe_publish(event)
        logger.info("Synthetic batch published with %s events", len(batch))
        await asyncio.sleep(interval_seconds)
