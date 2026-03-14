from dataclasses import dataclass
from typing import Any


@dataclass
class ApiError(Exception):
    error_code: str
    status_code: int
    message: str
    details: Any | None = None
