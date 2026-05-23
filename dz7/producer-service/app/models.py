from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator


class EventType(str, Enum):
    VIEW_STARTED = "VIEW_STARTED"
    VIEW_FINISHED = "VIEW_FINISHED"
    VIEW_PAUSED = "VIEW_PAUSED"
    VIEW_RESUMED = "VIEW_RESUMED"
    LIKED = "LIKED"
    SEARCHED = "SEARCHED"


class DeviceType(str, Enum):
    MOBILE = "MOBILE"
    DESKTOP = "DESKTOP"
    TV = "TV"
    TABLET = "TABLET"


class MovieEventIn(BaseModel):
    event_id: UUID = Field(default_factory=uuid4)
    user_id: str = Field(min_length=1)
    movie_id: str = Field(min_length=1)
    event_type: EventType
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    device_type: DeviceType
    session_id: str = Field(min_length=1)
    progress_seconds: int | None = Field(default=None, ge=0)
    search_query: str | None = None
    schema_version: int = 1

    @model_validator(mode="after")
    def validate_payload(self) -> "MovieEventIn":
        if self.timestamp.tzinfo is None:
            self.timestamp = self.timestamp.replace(tzinfo=timezone.utc)
        else:
            self.timestamp = self.timestamp.astimezone(timezone.utc)

        requires_progress = {
            EventType.VIEW_STARTED,
            EventType.VIEW_PAUSED,
            EventType.VIEW_RESUMED,
            EventType.VIEW_FINISHED,
        }
        if self.event_type in requires_progress and self.progress_seconds is None:
            raise ValueError("progress_seconds is required for watch events")

        if self.event_type == EventType.SEARCHED and not self.search_query:
            raise ValueError("search_query is required for SEARCHED events")

        return self

    def to_avro_dict(self) -> dict[str, object]:
        return {
            "event_id": str(self.event_id),
            "user_id": self.user_id,
            "movie_id": self.movie_id,
            "event_type": self.event_type.value,
            "timestamp": int(self.timestamp.timestamp() * 1000),
            "device_type": self.device_type.value,
            "session_id": self.session_id,
            "progress_seconds": self.progress_seconds,
            "search_query": self.search_query,
            "schema_version": self.schema_version,
        }


class PublishResponse(BaseModel):
    event_id: UUID
    topic: str
    partition_key: str
