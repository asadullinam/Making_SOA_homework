from __future__ import annotations

from datetime import date

from app.aggregation import AggregationService


class FakeQueryResult:
    def __init__(self, rows):
        self.result_rows = rows


class FakeClickHouseClient:
    def __init__(self) -> None:
        self.commands = []

    def command(self, sql: str, parameters: dict | None = None) -> None:
        self.commands.append((sql, parameters))

    def query(self, sql: str, parameters: dict | None = None) -> FakeQueryResult:
        compact_sql = " ".join(sql.split())
        if "SELECT count() FROM movie_events" in compact_sql:
            return FakeQueryResult([(4,)])
        if "SELECT dau FROM daily_dau" in compact_sql:
            return FakeQueryResult([(2,)])
        if "SELECT avg_watch_seconds FROM daily_avg_watch_time" in compact_sql:
            return FakeQueryResult([(120.5,)])
        if "SELECT started, finished, conversion_rate FROM daily_conversion" in compact_sql:
            return FakeQueryResult([(3, 2, 2 / 3)])
        if "SELECT retention_d1, retention_d7 FROM daily_retention" in compact_sql:
            return FakeQueryResult([(0.5, 0.25)])
        if "SELECT movie_id, views, rank FROM daily_top_movies" in compact_sql:
            return FakeQueryResult([("movie-1", 10, 1), ("movie-2", 7, 2)])
        if "SELECT device_type, events FROM device_distribution" in compact_sql:
            return FakeQueryResult([("DESKTOP", 3), ("TV", 1)])
        raise AssertionError(f"Unexpected query: {compact_sql}")


class FakeRepository:
    def __init__(self) -> None:
        self.calls = []

    def upsert_metrics(self, metric_date: date, rows) -> None:
        self.calls.append((metric_date, list(rows)))


def test_aggregate_for_date_rewrites_views_and_persists_metrics() -> None:
    clickhouse = FakeClickHouseClient()
    repository = FakeRepository()
    service = AggregationService(clickhouse, repository)

    result = service.aggregate_for_date(date(2030, 1, 1))

    assert result.metric_date == date(2030, 1, 1)
    assert result.processed_rows == 4
    assert result.metrics_written == len(repository.calls[0][1])
    assert len(clickhouse.commands) >= 7

    metric_names = {row["metric_name"] for row in repository.calls[0][1]}
    assert {"DAU", "AVG_WATCH_SECONDS", "CONVERSION_RATE", "RETENTION_D1", "RETENTION_D7"} <= metric_names
