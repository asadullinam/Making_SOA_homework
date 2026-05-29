from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from typing import Iterable

from sqlalchemy import text
from sqlalchemy.engine import Engine
from tenacity import before_sleep_log, retry, retry_if_exception_type, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


class MetricsRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    @retry(
        reraise=True,
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type(Exception),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    def upsert_metrics(self, metric_date: date, rows: Iterable[dict[str, object]]) -> None:
        payload = list(rows)
        if not payload:
            logger.info("No metrics to upsert for %s", metric_date.isoformat())
            return

        logger.info("Upserting %s metrics into PostgreSQL for %s", len(payload), metric_date.isoformat())
        try:
            with self.engine.begin() as connection:
                for row in payload:
                    connection.execute(
                        text(
                            """
                            INSERT INTO daily_metrics (
                                metric_date,
                                metric_name,
                                dimension_key,
                                dimension_value,
                                metric_value,
                                computed_at,
                                metadata
                            ) VALUES (
                                :metric_date,
                                :metric_name,
                                :dimension_key,
                                :dimension_value,
                                :metric_value,
                                :computed_at,
                                CAST(:metadata AS JSONB)
                            )
                            ON CONFLICT (metric_date, metric_name, dimension_key, dimension_value)
                            DO UPDATE SET
                                metric_value = EXCLUDED.metric_value,
                                computed_at = EXCLUDED.computed_at,
                                metadata = EXCLUDED.metadata
                            """
                        ),
                        {
                            "metric_date": metric_date,
                            "metric_name": row["metric_name"],
                            "dimension_key": row.get("dimension_key", ""),
                            "dimension_value": row.get("dimension_value", ""),
                            "metric_value": float(row["metric_value"]),
                            "computed_at": datetime.now(timezone.utc),
                            "metadata": json.dumps(row.get("metadata", {})),
                        },
                    )
        except Exception:
            logger.exception("Failed to upsert metrics into PostgreSQL for %s", metric_date.isoformat())
            raise

        logger.info("Successfully upserted metrics into PostgreSQL for %s", metric_date.isoformat())

    def fetch_metrics_for_export(self, metric_date: date) -> list[dict[str, object]]:
        try:
            with self.engine.begin() as connection:
                result = connection.execute(
                    text(
                        """
                        SELECT
                            metric_date,
                            metric_name,
                            dimension_key,
                            dimension_value,
                            metric_value,
                            computed_at,
                            metadata
                        FROM daily_metrics
                        WHERE metric_date = :metric_date
                        ORDER BY metric_name, dimension_key, dimension_value
                        """
                    ),
                    {"metric_date": metric_date},
                )
                rows = [dict(row._mapping) for row in result]
        except Exception:
            logger.exception("Failed to fetch metrics from PostgreSQL for export date %s", metric_date.isoformat())
            raise

        logger.info("Fetched %s metric rows from PostgreSQL for export date %s", len(rows), metric_date.isoformat())
        return rows
