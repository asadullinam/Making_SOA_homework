from __future__ import annotations

import asyncio
import logging

from fastapi import FastAPI, HTTPException

from app.config import get_settings
from app.generator import generator_loop
from app.kafka_client import KafkaPublisher
from app.metrics import instrument_app
from app.models import MovieEventIn, PublishResponse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [producer-service] %(name)s - %(message)s",
)

settings = get_settings()
publisher = KafkaPublisher(settings)
app = FastAPI(title="Movie Event Producer")
instrument_app(app, "producer-service")


@app.on_event("startup")
async def startup_event() -> None:
    if settings.generator_enabled:
        asyncio.create_task(generator_loop(publisher, settings.generator_interval_seconds))


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/events", response_model=PublishResponse)
def create_event(event: MovieEventIn) -> PublishResponse:
    try:
        partition_key = publisher.safe_publish(event)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return PublishResponse(
        event_id=event.event_id,
        topic=settings.kafka_topic,
        partition_key=partition_key,
    )
