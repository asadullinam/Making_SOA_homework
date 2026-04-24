from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.aggregation import AggregationService
from app.exporter import ExportService

logger = logging.getLogger(__name__)


def build_scheduler(
    aggregation_service: AggregationService,
    export_service: ExportService,
    aggregation_interval_minutes: int,
    export_interval_minutes: int,
) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")

    def aggregate_latest() -> None:
        target_date = (datetime.now(timezone.utc) - timedelta(days=1)).date()
        aggregation_service.aggregate_for_date(target_date)

    def export_latest() -> None:
        target_date = (datetime.now(timezone.utc) - timedelta(days=1)).date()
        export_service.export_for_date(target_date)

    scheduler.add_job(
        aggregate_latest,
        IntervalTrigger(minutes=aggregation_interval_minutes),
        id="aggregate-latest",
        replace_existing=True,
    )
    scheduler.add_job(
        export_latest,
        IntervalTrigger(minutes=export_interval_minutes),
        id="export-latest",
        replace_existing=True,
    )
    logger.info(
        "Scheduler configured. aggregation_interval_minutes=%s export_interval_minutes=%s",
        aggregation_interval_minutes,
        export_interval_minutes,
    )
    return scheduler
