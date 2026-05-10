from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class EventType(str, Enum):
    PRODUCT_RECEIVED = "PRODUCT_RECEIVED"
    PRODUCT_SHIPPED = "PRODUCT_SHIPPED"
    PRODUCT_MOVED = "PRODUCT_MOVED"
    PRODUCT_RESERVED = "PRODUCT_RESERVED"
    PRODUCT_RELEASED = "PRODUCT_RELEASED"
    INVENTORY_COUNTED = "INVENTORY_COUNTED"
    ORDER_CREATED = "ORDER_CREATED"
    ORDER_COMPLETED = "ORDER_COMPLETED"


class OrderLine(BaseModel):
    product_id: str = Field(description="SKU товара")
    zone_id: str = Field(description="Зона склада, из которой резервируем или отгружаем товар")
    quantity: int = Field(description="Количество единиц товара")


class WarehouseEventIn(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid4()), description="Уникальный идентификатор события")
    event_type: EventType = Field(description="Тип складского события")
    event_timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Время события в UTC. Используется для защиты от out-of-order событий.",
    )
    product_id: str | None = Field(default=None, description="SKU товара")
    quantity: int | None = Field(default=None, description="Количество для операций receive/ship/move/reserve/release")
    counted_quantity: int | None = Field(default=None, description="Подсчитанное количество для INVENTORY_COUNTED")
    zone_id: str | None = Field(default=None, description="Зона склада для receive/ship/reserve/release/count")
    from_zone_id: str | None = Field(default=None, description="Исходная зона для PRODUCT_MOVED")
    to_zone_id: str | None = Field(default=None, description="Целевая зона для PRODUCT_MOVED")
    order_id: str | None = Field(default=None, description="Идентификатор заказа для ORDER_CREATED / ORDER_COMPLETED")
    order_lines: list[OrderLine] = Field(default_factory=list, description="Позиции заказа")
    entity_version: int | None = Field(default=None, description="Опциональная версия сущности")
    supplier_id: str | None = Field(default=None, description="Новое поле V2-схемы для schema evolution")

    def to_avro_dict(self, schema_version: int) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "event_timestamp": self.event_timestamp.astimezone(timezone.utc).isoformat(),
            "product_id": self.product_id,
            "quantity": self.quantity,
            "counted_quantity": self.counted_quantity,
            "zone_id": self.zone_id,
            "from_zone_id": self.from_zone_id,
            "to_zone_id": self.to_zone_id,
            "order_id": self.order_id,
            "order_lines": [line.model_dump(mode="python") for line in self.order_lines],
            "entity_version": self.entity_version,
        }
        if schema_version >= 2:
            payload["supplier_id"] = self.supplier_id
        return payload


class PublishResponse(BaseModel):
    event_id: str
    topic: str
    schema_version: int
