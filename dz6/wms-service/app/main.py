from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Query

from app.config import get_settings
from app.kafka_client import KafkaPublisher
from app.models import PublishResponse, WarehouseEventIn

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [wms-service] %(name)s - %(message)s",
)

settings = get_settings()
publisher = KafkaPublisher(settings)
app = FastAPI(
    title="Smart Warehouse WMS Service",
    description="HTTP API для публикации складских событий в Kafka.",
)


@app.get("/health", summary="Liveness probe for WMS service")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post(
    "/events",
    response_model=PublishResponse,
    summary="Publish warehouse event to Kafka",
    description="Публикует одно складское событие в Kafka topic `warehouse-events` для ручной проверки сценариев из задания.",
)
def publish_event(
    event: WarehouseEventIn,
    v: int = Query(
        default=2,
        ge=1,
        le=2,
        description="Версия Avro-схемы: `1` для V1, `2` для V2",
    ),
) -> PublishResponse:
    try:
        publisher.publish(event, schema_version=v)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return PublishResponse(event_id=event.event_id, topic=settings.kafka_topic, schema_version=v)
