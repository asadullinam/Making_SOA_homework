import json
import time
import uuid
from datetime import datetime, timezone
from typing import Callable

from fastapi import Request, Response


async def log_requests(request: Request, call_next: Callable) -> Response:
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id

    start = time.time()
    body_bytes = b""
    if request.method in {"POST", "PUT", "DELETE"}:
        body_bytes = await request.body()
        request._body = body_bytes

    response = await call_next(request)
    duration_ms = int((time.time() - start) * 1000)

    user_id = None
    if hasattr(request.state, "user_id"):
        user_id = request.state.user_id

    body = None
    if body_bytes:
        try:
            body_json = json.loads(body_bytes.decode("utf-8"))
            if isinstance(body_json, dict):
                for key in ["password", "refresh_token"]:
                    if key in body_json:
                        body_json[key] = "***"
            body = body_json
        except json.JSONDecodeError:
            body = body_bytes.decode("utf-8", errors="ignore")

    log_record = {
        "request_id": request_id,
        "method": request.method,
        "endpoint": request.url.path,
        "status_code": response.status_code,
        "duration_ms": duration_ms,
        "user_id": user_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if body is not None:
        log_record["body"] = body

    print(json.dumps(log_record, ensure_ascii=False))
    response.headers["X-Request-Id"] = request_id
    return response
