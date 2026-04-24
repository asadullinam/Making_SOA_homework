from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from clickhouse_connect.driver.client import Client

from app.repository import MetricsRepository

logger = logging.getLogger(__name__)


@dataclass
class AggregationResult:
    metric_date: date
    processed_rows: int
    duration_seconds: float
    metrics_written: int


class AggregationService:
    def __init__(self, clickhouse: Client, repository: MetricsRepository) -> None:
        self.clickhouse = clickhouse
        self.repository = repository

    def aggregate_for_date(self, target_date: date) -> AggregationResult:
        started_at = time.perf_counter()
        logger.info("Aggregation started for %s", target_date.isoformat())

        processed_rows = self._count_raw_rows(target_date)
        computed_at = datetime.now(timezone.utc).replace(microsecond=0)

        self._rewrite_daily_dau(target_date, computed_at)
        self._rewrite_avg_watch_time(target_date, computed_at)
        self._rewrite_top_movies(target_date, computed_at)
        self._rewrite_conversion(target_date, computed_at)
        self._rewrite_retention(target_date, computed_at)
        self._rewrite_device_distribution(target_date, computed_at)
        self._rewrite_retention_cohorts(target_date, computed_at)

        metrics = self._build_metric_payload(target_date, computed_at)
        self.repository.upsert_metrics(target_date, metrics)

        duration = time.perf_counter() - started_at
        logger.info(
            "Aggregation finished for %s. processed_rows=%s metrics=%s duration=%.2fs",
            target_date.isoformat(),
            processed_rows,
            len(metrics),
            duration,
        )
        return AggregationResult(
            metric_date=target_date,
            processed_rows=processed_rows,
            duration_seconds=duration,
            metrics_written=len(metrics),
        )

    def _count_raw_rows(self, target_date: date) -> int:
        result = self.clickhouse.query(
            """
            SELECT count()
            FROM movie_events
            WHERE event_date = %(target_date)s
            """,
            parameters={"target_date": target_date},
        )
        return int(result.result_rows[0][0])

    def _rewrite_daily_dau(self, target_date: date, computed_at: datetime) -> None:
        self.clickhouse.command(
            "DELETE FROM daily_dau WHERE metric_date = %(target_date)s",
            parameters={"target_date": target_date},
        )
        self.clickhouse.command(
            """
            INSERT INTO daily_dau
            SELECT
                %(target_date)s AS metric_date,
                uniqExact(user_id) AS dau,
                %(computed_at)s AS computed_at
            FROM movie_events
            WHERE event_date = %(target_date)s
            """,
            parameters={"target_date": target_date, "computed_at": computed_at},
        )

    def _rewrite_avg_watch_time(self, target_date: date, computed_at: datetime) -> None:
        self.clickhouse.command(
            "DELETE FROM daily_avg_watch_time WHERE metric_date = %(target_date)s",
            parameters={"target_date": target_date},
        )
        self.clickhouse.command(
            """
            INSERT INTO daily_avg_watch_time
            SELECT
                %(target_date)s AS metric_date,
                avg(toFloat64(progress_seconds)) AS avg_watch_seconds,
                %(computed_at)s AS computed_at
            FROM movie_events
            WHERE event_date = %(target_date)s
              AND event_type = 'VIEW_FINISHED'
              AND progress_seconds IS NOT NULL
            """,
            parameters={"target_date": target_date, "computed_at": computed_at},
        )

    def _rewrite_top_movies(self, target_date: date, computed_at: datetime) -> None:
        self.clickhouse.command(
            "DELETE FROM daily_top_movies WHERE metric_date = %(target_date)s",
            parameters={"target_date": target_date},
        )
        self.clickhouse.command(
            """
            INSERT INTO daily_top_movies
            WITH ranked AS (
                SELECT
                    movie_id,
                    countIf(event_type = 'VIEW_FINISHED') AS views,
                    row_number() OVER (ORDER BY countIf(event_type = 'VIEW_FINISHED') DESC, movie_id) AS rank
                FROM movie_events
                WHERE event_date = %(target_date)s
                GROUP BY movie_id
            )
            SELECT %(target_date)s AS metric_date, movie_id, views, toUInt8(rank), %(computed_at)s AS computed_at
            FROM ranked
            WHERE rank <= 10
            """,
            parameters={"target_date": target_date, "computed_at": computed_at},
        )

    def _rewrite_conversion(self, target_date: date, computed_at: datetime) -> None:
        self.clickhouse.command(
            "DELETE FROM daily_conversion WHERE metric_date = %(target_date)s",
            parameters={"target_date": target_date},
        )
        self.clickhouse.command(
            """
            INSERT INTO daily_conversion
            SELECT
                %(target_date)s AS metric_date,
                countIf(event_type = 'VIEW_STARTED') AS started,
                countIf(event_type = 'VIEW_FINISHED') AS finished,
                if(countIf(event_type = 'VIEW_STARTED') = 0, 0., countIf(event_type = 'VIEW_FINISHED') / countIf(event_type = 'VIEW_STARTED')) AS conversion_rate,
                %(computed_at)s AS computed_at
            FROM movie_events
            WHERE event_date = %(target_date)s
            """,
            parameters={"target_date": target_date, "computed_at": computed_at},
        )

    def _rewrite_retention(self, target_date: date, computed_at: datetime) -> None:
        self.clickhouse.command(
            "DELETE FROM daily_retention WHERE metric_date = %(target_date)s",
            parameters={"target_date": target_date},
        )
        self.clickhouse.command(
            """
            INSERT INTO daily_retention
            WITH first_watch AS (
                SELECT
                    user_id,
                    min(toDate(timestamp)) AS first_date
                FROM movie_events
                WHERE event_type IN ('VIEW_STARTED', 'VIEW_FINISHED', 'VIEW_PAUSED', 'VIEW_RESUMED')
                GROUP BY user_id
            ),
            cohort AS (
                SELECT user_id
                FROM first_watch
                WHERE first_date = %(target_date)s
            ),
            returns AS (
                SELECT
                    c.user_id,
                    max(if(e.event_date = %(target_date_d1)s, 1, 0)) AS retained_d1,
                    max(if(e.event_date = %(target_date_d7)s, 1, 0)) AS retained_d7
                FROM cohort c
                LEFT JOIN movie_events e
                    ON e.user_id = c.user_id
                   AND e.event_type IN ('VIEW_STARTED', 'VIEW_FINISHED', 'VIEW_PAUSED', 'VIEW_RESUMED')
                   AND e.event_date IN (%(target_date_d1)s, %(target_date_d7)s)
                GROUP BY c.user_id
            )
            SELECT
                %(target_date)s AS metric_date,
                if(count() = 0, 0., avg(toFloat64(retained_d1))) AS retention_d1,
                if(count() = 0, 0., avg(toFloat64(retained_d7))) AS retention_d7,
                %(computed_at)s AS computed_at
            FROM returns
            """,
            parameters={
                "target_date": target_date,
                "target_date_d1": target_date + timedelta(days=1),
                "target_date_d7": target_date + timedelta(days=7),
                "computed_at": computed_at,
            },
        )

    def _rewrite_device_distribution(self, target_date: date, computed_at: datetime) -> None:
        self.clickhouse.command(
            "DELETE FROM device_distribution WHERE metric_date = %(target_date)s",
            parameters={"target_date": target_date},
        )
        self.clickhouse.command(
            """
            INSERT INTO device_distribution
            SELECT
                %(target_date)s AS metric_date,
                device_type,
                count() AS events,
                %(computed_at)s AS computed_at
            FROM movie_events
            WHERE event_date = %(target_date)s
            GROUP BY device_type
            """,
            parameters={"target_date": target_date, "computed_at": computed_at},
        )

    def _rewrite_retention_cohorts(self, target_date: date, computed_at: datetime) -> None:
        self.clickhouse.command(
            "DELETE FROM retention_cohorts WHERE cohort_date = %(target_date)s",
            parameters={"target_date": target_date},
        )
        self.clickhouse.command(
            """
            INSERT INTO retention_cohorts
            WITH first_watch AS (
                SELECT
                    user_id,
                    min(toDate(timestamp)) AS cohort_date
                FROM movie_events
                WHERE event_type IN ('VIEW_STARTED', 'VIEW_FINISHED', 'VIEW_PAUSED', 'VIEW_RESUMED')
                GROUP BY user_id
            ),
            cohort_users AS (
                SELECT
                    fw.cohort_date,
                    fw.user_id,
                    e.event_date,
                    dateDiff('day', fw.cohort_date, e.event_date) AS lifecycle_day
                FROM first_watch fw
                INNER JOIN movie_events e ON e.user_id = fw.user_id
                WHERE fw.cohort_date = %(target_date)s
                  AND e.event_type IN ('VIEW_STARTED', 'VIEW_FINISHED', 'VIEW_PAUSED', 'VIEW_RESUMED')
            ),
            cohort_size AS (
                SELECT countDistinct(user_id) AS cohort_size
                FROM first_watch
                WHERE cohort_date = %(target_date)s
            )
            SELECT
                %(target_date)s AS cohort_date,
                toUInt8(lifecycle_day) AS lifecycle_day,
                uniqExact(user_id) AS users,
                (SELECT cohort_size FROM cohort_size) AS cohort_size,
                if((SELECT cohort_size FROM cohort_size) = 0, 0., uniqExact(user_id) / (SELECT cohort_size FROM cohort_size)) AS retention_rate,
                %(computed_at)s AS computed_at
            FROM cohort_users
            WHERE lifecycle_day BETWEEN 0 AND 7
            GROUP BY lifecycle_day
            ORDER BY lifecycle_day
            """,
            parameters={"target_date": target_date, "computed_at": computed_at},
        )

    def _build_metric_payload(self, target_date: date, computed_at: datetime) -> list[dict[str, object]]:
        payload: list[dict[str, object]] = []

        dau = self.clickhouse.query(
            "SELECT dau FROM daily_dau FINAL WHERE metric_date = %(target_date)s",
            parameters={"target_date": target_date},
        ).result_rows
        if dau:
            payload.append({"metric_name": "DAU", "metric_value": dau[0][0], "metadata": {"computed_at": computed_at.isoformat()}})

        avg_watch = self.clickhouse.query(
            "SELECT avg_watch_seconds FROM daily_avg_watch_time FINAL WHERE metric_date = %(target_date)s",
            parameters={"target_date": target_date},
        ).result_rows
        if avg_watch:
            payload.append(
                {
                    "metric_name": "AVG_WATCH_SECONDS",
                    "metric_value": avg_watch[0][0] or 0.0,
                    "metadata": {"computed_at": computed_at.isoformat()},
                }
            )

        conversion = self.clickhouse.query(
            """
            SELECT started, finished, conversion_rate
            FROM daily_conversion FINAL
            WHERE metric_date = %(target_date)s
            """,
            parameters={"target_date": target_date},
        ).result_rows
        if conversion:
            started, finished, rate = conversion[0]
            payload.extend(
                [
                    {"metric_name": "VIEW_STARTED", "metric_value": started, "metadata": {"computed_at": computed_at.isoformat()}},
                    {"metric_name": "VIEW_FINISHED", "metric_value": finished, "metadata": {"computed_at": computed_at.isoformat()}},
                    {"metric_name": "CONVERSION_RATE", "metric_value": rate, "metadata": {"computed_at": computed_at.isoformat()}},
                ]
            )

        retention = self.clickhouse.query(
            """
            SELECT retention_d1, retention_d7
            FROM daily_retention FINAL
            WHERE metric_date = %(target_date)s
            """,
            parameters={"target_date": target_date},
        ).result_rows
        if retention:
            d1, d7 = retention[0]
            payload.extend(
                [
                    {"metric_name": "RETENTION_D1", "metric_value": d1, "metadata": {"computed_at": computed_at.isoformat()}},
                    {"metric_name": "RETENTION_D7", "metric_value": d7, "metadata": {"computed_at": computed_at.isoformat()}},
                ]
            )

        for movie_id, views, rank in self.clickhouse.query(
            """
            SELECT movie_id, views, rank
            FROM daily_top_movies FINAL
            WHERE metric_date = %(target_date)s
            ORDER BY rank
            """,
            parameters={"target_date": target_date},
        ).result_rows:
            payload.append(
                {
                    "metric_name": "TOP_MOVIE_VIEWS",
                    "dimension_key": "movie_id",
                    "dimension_value": str(movie_id),
                    "metric_value": views,
                    "metadata": {"rank": int(rank), "computed_at": computed_at.isoformat()},
                }
            )

        for device_type, events in self.clickhouse.query(
            """
            SELECT device_type, events
            FROM device_distribution FINAL
            WHERE metric_date = %(target_date)s
            ORDER BY device_type
            """,
            parameters={"target_date": target_date},
        ).result_rows:
            payload.append(
                {
                    "metric_name": "DEVICE_EVENTS",
                    "dimension_key": "device_type",
                    "dimension_value": str(device_type),
                    "metric_value": events,
                    "metadata": {"computed_at": computed_at.isoformat()},
                }
            )

        return payload
