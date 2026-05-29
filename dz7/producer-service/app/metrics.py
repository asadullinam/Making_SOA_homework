from __future__ import annotations

import time
from typing import Callable

from fastapi import FastAPI, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.responses import Response as StarletteResponse

HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Total number of HTTP requests",
    ("service", "method", "endpoint", "status"),
)
HTTP_REQUEST_ERRORS_TOTAL = Counter(
    "http_request_errors_total",
    "Total number of failed HTTP requests",
    ("service", "method", "endpoint", "error_type"),
)
HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ("service", "method", "endpoint"),
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)


def _endpoint_label(request: Request) -> str:
    route = request.scope.get("route")
    if route is not None and getattr(route, "path", None):
        return route.path
    return request.url.path


def instrument_app(app: FastAPI, service_name: str) -> None:
    @app.middleware("http")
    async def prometheus_middleware(request: Request, call_next: Callable) -> Response:
        if request.url.path == "/metrics":
            return await call_next(request)

        method = request.method
        started_at = time.perf_counter()
        status = "500"
        endpoint = request.url.path

        try:
            response = await call_next(request)
            status = str(response.status_code)
            endpoint = _endpoint_label(request)
            return response
        except Exception as exc:
            endpoint = _endpoint_label(request)
            HTTP_REQUEST_ERRORS_TOTAL.labels(
                service=service_name,
                method=method,
                endpoint=endpoint,
                error_type=exc.__class__.__name__,
            ).inc()
            raise
        finally:
            duration = time.perf_counter() - started_at
            HTTP_REQUESTS_TOTAL.labels(
                service=service_name,
                method=method,
                endpoint=endpoint,
                status=status,
            ).inc()
            HTTP_REQUEST_DURATION_SECONDS.labels(
                service=service_name,
                method=method,
                endpoint=endpoint,
            ).observe(duration)
            if status.startswith("4") or status.startswith("5"):
                HTTP_REQUEST_ERRORS_TOTAL.labels(
                    service=service_name,
                    method=method,
                    endpoint=endpoint,
                    error_type=f"http_{status}",
                ).inc()

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> StarletteResponse:
        return StarletteResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)
