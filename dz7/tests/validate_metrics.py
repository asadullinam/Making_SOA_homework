from __future__ import annotations

import os

import requests

from helpers import PROMETHEUS_URL, wait_for_prometheus_query, write_json_artifact

RESULTS_FILE = os.getenv("RESULTS_FILE", "/tests/artifacts/metrics-validation.json")
P95_THRESHOLD_SECONDS = float(os.getenv("P95_THRESHOLD_SECONDS", "0.5"))
ERROR_RATE_THRESHOLD = float(os.getenv("ERROR_RATE_THRESHOLD", "0.01"))
CONSUMER_LAG_THRESHOLD = float(os.getenv("CONSUMER_LAG_THRESHOLD", "1000"))


def read_scalar(query: str) -> float:
    payload = wait_for_prometheus_query(query, timeout_seconds=90)
    return float(payload["data"]["result"][0]["value"][1])


def read_scalar_allow_empty(query: str) -> float:
    response = requests.get(
        f"{PROMETHEUS_URL}/api/v1/query",
        params={"query": query},
        timeout=15,
    )
    response.raise_for_status()
    payload = response.json()
    if payload["status"] != "success":
        raise AssertionError(payload)
    if not payload["data"]["result"]:
        return 0.0
    return float(payload["data"]["result"][0]["value"][1])


def main() -> None:
    producer_up = read_scalar('up{job="producer-service"}')
    aggregation_up = read_scalar('up{job="aggregation-service"}')
    error_rate = read_scalar_allow_empty(
        'sum(rate(http_request_errors_total{service="producer-service"}[5m])) / clamp_min(sum(rate(http_requests_total{service="producer-service",endpoint!="/metrics"}[5m])), 0.001)'
    )
    p95_latency = read_scalar(
        'histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{service="producer-service",endpoint!="/metrics"}[5m])))'
    )
    consumer_lag = read_scalar_allow_empty(
        'kafka_consumergroup_lag_sum{consumergroup="clickhouse-movie-events"}'
    )

    payload = {
        "prometheus_url": PROMETHEUS_URL,
        "checks": {
            "producer_up": producer_up,
            "aggregation_up": aggregation_up,
            "producer_error_rate": error_rate,
            "producer_p95_latency_seconds": p95_latency,
            "clickhouse_movie_events_consumer_lag": consumer_lag,
        },
        "thresholds": {
            "producer_error_rate_lt": ERROR_RATE_THRESHOLD,
            "producer_p95_latency_seconds_lt": P95_THRESHOLD_SECONDS,
            "clickhouse_movie_events_consumer_lag_lt": CONSUMER_LAG_THRESHOLD,
        },
    }
    write_json_artifact(RESULTS_FILE, payload)

    assert producer_up == 1.0
    assert aggregation_up == 1.0
    assert error_rate < ERROR_RATE_THRESHOLD, payload
    assert p95_latency < P95_THRESHOLD_SECONDS, payload
    assert consumer_lag < CONSUMER_LAG_THRESHOLD, payload


if __name__ == "__main__":
    main()
