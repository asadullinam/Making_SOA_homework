from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone

from fastapi import FastAPI
from pydantic import BaseModel

from app.aggregation import AggregationService
from app.config import get_settings
from app.db import create_clickhouse_client, create_postgres_engine
from app.exporter import ExportService
from app.repository import MetricsRepository
from app.scheduler import build_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [aggregation-service] %(name)s - %(message)s",
)

settings = get_settings()
clickhouse_client = create_clickhouse_client(settings)
postgres_engine = create_postgres_engine(settings)
repository = MetricsRepository(postgres_engine)
aggregation_service = AggregationService(clickhouse_client, repository)
export_service = ExportService(settings, repository)
scheduler = build_scheduler(
    aggregation_service,
    export_service,
    settings.aggregation_schedule_minutes,
    settings.export_schedule_minutes,
)


class JobResponse(BaseModel):
    status: str
    metric_date: date
    processed_rows: int | None = None
    duration_seconds: float | None = None
    metrics_written: int | None = None
    s3_key: str | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    scheduler.start()
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)
        clickhouse_client.close()
        postgres_engine.dispose()


app = FastAPI(title="Aggregation Service", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/aggregate", response_model=JobResponse)
def aggregate(target_date: date | None = None) -> JobResponse:
    target = target_date or (datetime.now(timezone.utc) - timedelta(days=1)).date()
    result = aggregation_service.aggregate_for_date(target)
    return JobResponse(
        status="ok",
        metric_date=result.metric_date,
        processed_rows=result.processed_rows,
        duration_seconds=result.duration_seconds,
        metrics_written=result.metrics_written,
    )


@app.post("/export", response_model=JobResponse)
def export(target_date: date | None = None) -> JobResponse:
    target = target_date or (datetime.now(timezone.utc) - timedelta(days=1)).date()
    s3_key = export_service.export_for_date(target)
    return JobResponse(status="ok", metric_date=target, s3_key=s3_key)
