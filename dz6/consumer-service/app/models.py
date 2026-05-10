from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class EventType(str, Enum):
    PRODUCT_RECEIVED = "PRODUCT_RECEIVED"
    PRODUCT_SHIPPED = "PRODUCT_SHIPPED"
    PRODUCT_MOVED = "PRODUCT_MOVED"
    PRODUCT_RESERVED = "PRODUCT_RESERVED"
    PRODUCT_RELEASED = "PRODUCT_RELEASED"
    INVENTORY_COUNTED = "INVENTORY_COUNTED"
    ORDER_CREATED = "ORDER_CREATED"
    ORDER_COMPLETED = "ORDER_COMPLETED"


class EventProcessingError(Exception):
    def __init__(self, message: str, code: str = "PROCESSING_ERROR") -> None:
        super().__init__(message)
        self.code = code


class ValidationError(EventProcessingError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="VALIDATION_ERROR")


@dataclass
class OrderLine:
    product_id: str
    zone_id: str
    quantity: int


@dataclass
class WarehouseEvent:
    event_id: str
    event_type: EventType
    event_timestamp: datetime
    product_id: str | None = None
    quantity: int | None = None
    counted_quantity: int | None = None
    zone_id: str | None = None
    from_zone_id: str | None = None
    to_zone_id: str | None = None
    order_id: str | None = None
    order_lines: list[OrderLine] = field(default_factory=list)
    entity_version: int | None = None
    supplier_id: str | None = None
    schema_version: int = 2
    raw_payload: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: dict[str, Any], schema_version: int) -> "WarehouseEvent":
        lines = [
            OrderLine(
                product_id=line["product_id"],
                zone_id=line["zone_id"],
                quantity=line["quantity"],
            )
            for line in payload.get("order_lines", [])
        ]
        timestamp = datetime.fromisoformat(payload["event_timestamp"].replace("Z", "+00:00")).astimezone(UTC)
        return cls(
            event_id=payload["event_id"],
            event_type=EventType(payload["event_type"]),
            event_timestamp=timestamp,
            product_id=payload.get("product_id"),
            quantity=payload.get("quantity"),
            counted_quantity=payload.get("counted_quantity"),
            zone_id=payload.get("zone_id"),
            from_zone_id=payload.get("from_zone_id"),
            to_zone_id=payload.get("to_zone_id"),
            order_id=payload.get("order_id"),
            order_lines=lines,
            entity_version=payload.get("entity_version"),
            supplier_id=payload.get("supplier_id"),
            schema_version=schema_version,
            raw_payload=payload,
        )


@dataclass
class InventoryState:
    product_id: str
    zone_id: str
    available_quantity: int = 0
    reserved_quantity: int = 0
    last_event_timestamp: datetime | None = None
    last_event_id: str | None = None
    supplier_id: str | None = None


@dataclass
class ProductTotals:
    product_id: str
    total_available_quantity: int = 0
    total_reserved_quantity: int = 0
    last_event_timestamp: datetime | None = None
    last_event_id: str | None = None
    supplier_id: str | None = None


@dataclass
class OrderState:
    order_id: str
    status: str
    last_event_timestamp: datetime | None = None
    items_json: str = "[]"


@dataclass
class KafkaMetadata:
    partition: int
    offset: int


@dataclass
class ProcessingResult:
    status: str
    event_type: str
