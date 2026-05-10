from __future__ import annotations

import json
from collections import defaultdict
from copy import deepcopy
from datetime import datetime

from app.cassandra_repo import CassandraRepository
from app.models import (
    EventType,
    InventoryState,
    KafkaMetadata,
    OrderLine,
    OrderState,
    ProcessingResult,
    ProductTotals,
    ValidationError,
    WarehouseEvent,
)


class WarehouseProcessor:
    def __init__(self, repo: CassandraRepository) -> None:
        self.repo = repo

    def process(self, event: WarehouseEvent, metadata: KafkaMetadata) -> ProcessingResult:
        zone_states, product_totals, existing_order = self._load_current_state(event)
        normalized_event = self._normalize_event(event, existing_order)
        if normalized_event.order_lines != event.order_lines:
            zone_states, product_totals, existing_order = self._load_current_state(normalized_event)
        event = normalized_event
        self._validate_event(event)

        if self.repo.is_processed(event.event_id):
            return ProcessingResult(status="DUPLICATE", event_type=event.event_type.value)

        latest_timestamp = self._latest_timestamp(zone_states, product_totals, existing_order)
        if latest_timestamp is not None and event.event_timestamp < latest_timestamp:
            self.repo.apply_inventory_batch(
                event_id=event.event_id,
                event_type=event.event_type.value,
                event_timestamp=event.event_timestamp,
                kafka_partition=metadata.partition,
                kafka_offset=metadata.offset,
                inventory_states=[],
                product_totals=[],
                order_state=None,
                audit_payload=event.raw_payload,
                status="STALE",
                error_reason="Older event_timestamp than current state",
            )
            return ProcessingResult(status="STALE", event_type=event.event_type.value)

        next_zone_states = {(state.product_id, state.zone_id): deepcopy(state) for state in zone_states}
        next_product_totals = {state.product_id: deepcopy(state) for state in product_totals}
        order_state: OrderState | None = deepcopy(existing_order) if existing_order is not None else None

        if event.event_type == EventType.PRODUCT_RECEIVED:
            state = next_zone_states[(event.product_id, event.zone_id)]
            totals = next_product_totals[event.product_id]
            qty = self._positive(event.quantity)
            state.available_quantity += qty
            totals.total_available_quantity += qty
            self._stamp_state(state, event)
            self._stamp_totals(totals, event)
        elif event.event_type == EventType.PRODUCT_SHIPPED:
            state = next_zone_states[(event.product_id, event.zone_id)]
            totals = next_product_totals[event.product_id]
            qty = self._positive(event.quantity)
            state.available_quantity -= qty
            totals.total_available_quantity -= qty
            self._stamp_state(state, event)
            self._stamp_totals(totals, event)
        elif event.event_type == EventType.PRODUCT_MOVED:
            qty = self._positive(event.quantity)
            from_state = next_zone_states[(event.product_id, event.from_zone_id)]
            to_state = next_zone_states[(event.product_id, event.to_zone_id)]
            totals = next_product_totals[event.product_id]
            from_state.available_quantity -= qty
            to_state.available_quantity += qty
            self._stamp_state(from_state, event)
            self._stamp_state(to_state, event)
            self._stamp_totals(totals, event)
        elif event.event_type == EventType.PRODUCT_RESERVED:
            state = next_zone_states[(event.product_id, event.zone_id)]
            totals = next_product_totals[event.product_id]
            qty = self._positive(event.quantity)
            state.available_quantity -= qty
            state.reserved_quantity += qty
            totals.total_available_quantity -= qty
            totals.total_reserved_quantity += qty
            self._stamp_state(state, event)
            self._stamp_totals(totals, event)
        elif event.event_type == EventType.PRODUCT_RELEASED:
            state = next_zone_states[(event.product_id, event.zone_id)]
            totals = next_product_totals[event.product_id]
            qty = self._positive(event.quantity)
            state.available_quantity += qty
            state.reserved_quantity -= qty
            totals.total_available_quantity += qty
            totals.total_reserved_quantity -= qty
            self._stamp_state(state, event)
            self._stamp_totals(totals, event)
        elif event.event_type == EventType.INVENTORY_COUNTED:
            state = next_zone_states[(event.product_id, event.zone_id)]
            totals = next_product_totals[event.product_id]
            counted_quantity = self._non_negative(event.counted_quantity)
            delta = counted_quantity - state.available_quantity
            state.available_quantity = counted_quantity
            totals.total_available_quantity += delta
            self._stamp_state(state, event)
            self._stamp_totals(totals, event)
        elif event.event_type == EventType.ORDER_CREATED:
            if order_state is not None and order_state.status == "COMPLETED":
                raise ValidationError(f"Order {event.order_id} is already completed")
            order_state = OrderState(
                order_id=event.order_id,
                status="CREATED",
                last_event_timestamp=event.event_timestamp,
                items_json=json.dumps([line.__dict__ for line in event.order_lines], ensure_ascii=True),
            )
            self._apply_order_lines(next_zone_states, next_product_totals, event, reserve=True)
        elif event.event_type == EventType.ORDER_COMPLETED:
            if existing_order is None:
                raise ValidationError(f"Order {event.order_id} does not exist")
            order_state = OrderState(
                order_id=event.order_id,
                status="COMPLETED",
                last_event_timestamp=event.event_timestamp,
                items_json=existing_order.items_json,
            )
            self._apply_order_lines(next_zone_states, next_product_totals, event, reserve=False)

        self._ensure_non_negative(next_zone_states.values(), next_product_totals.values())

        self.repo.apply_inventory_batch(
            event_id=event.event_id,
            event_type=event.event_type.value,
            event_timestamp=event.event_timestamp,
            kafka_partition=metadata.partition,
            kafka_offset=metadata.offset,
            inventory_states=list(next_zone_states.values()),
            product_totals=list(next_product_totals.values()),
            order_state=order_state,
            audit_payload=event.raw_payload,
            status="APPLIED",
        )
        return ProcessingResult(status="APPLIED", event_type=event.event_type.value)

    def _load_current_state(
        self,
        event: WarehouseEvent,
    ) -> tuple[list[InventoryState], list[ProductTotals], OrderState | None]:
        keys: set[tuple[str, str]] = set()
        product_ids: set[str] = set()
        order_state: OrderState | None = None

        if event.product_id and event.zone_id:
            keys.add((event.product_id, event.zone_id))
            product_ids.add(event.product_id)
        if event.product_id and event.from_zone_id:
            keys.add((event.product_id, event.from_zone_id))
            product_ids.add(event.product_id)
        if event.product_id and event.to_zone_id:
            keys.add((event.product_id, event.to_zone_id))
            product_ids.add(event.product_id)
        for line in event.order_lines:
            keys.add((line.product_id, line.zone_id))
            product_ids.add(line.product_id)
        if event.order_id:
            order_state = self.repo.get_order(event.order_id)

        zone_states = [self.repo.get_inventory(product_id, zone_id) for product_id, zone_id in sorted(keys)]
        totals = [self.repo.get_product_totals(product_id) for product_id in sorted(product_ids)]
        return zone_states, totals, order_state

    def _latest_timestamp(
        self,
        zone_states: list[InventoryState],
        product_totals: list[ProductTotals],
        order_state: OrderState | None,
    ) -> datetime | None:
        timestamps = [state.last_event_timestamp for state in zone_states if state.last_event_timestamp is not None]
        timestamps.extend(
            state.last_event_timestamp for state in product_totals if state.last_event_timestamp is not None
        )
        if order_state is not None and order_state.last_event_timestamp is not None:
            timestamps.append(order_state.last_event_timestamp)
        return max(timestamps) if timestamps else None

    def _apply_order_lines(
        self,
        zone_states: dict[tuple[str, str], InventoryState],
        product_totals: dict[str, ProductTotals],
        event: WarehouseEvent,
        reserve: bool,
    ) -> None:
        grouped_lines: dict[tuple[str, str], int] = defaultdict(int)
        per_product: dict[str, int] = defaultdict(int)
        for line in event.order_lines:
            qty = self._positive(line.quantity)
            grouped_lines[(line.product_id, line.zone_id)] += qty
            per_product[line.product_id] += qty

        for (product_id, zone_id), qty in grouped_lines.items():
            state = zone_states[(product_id, zone_id)]
            if reserve:
                state.available_quantity -= qty
                state.reserved_quantity += qty
            else:
                state.reserved_quantity -= qty
            self._stamp_state(state, event)

        for product_id, qty in per_product.items():
            totals = product_totals[product_id]
            if reserve:
                totals.total_available_quantity -= qty
                totals.total_reserved_quantity += qty
            else:
                totals.total_reserved_quantity -= qty
            self._stamp_totals(totals, event)

    def _stamp_state(self, state: InventoryState, event: WarehouseEvent) -> None:
        state.last_event_timestamp = event.event_timestamp
        state.last_event_id = event.event_id
        if event.supplier_id is not None:
            state.supplier_id = event.supplier_id

    def _stamp_totals(self, totals: ProductTotals, event: WarehouseEvent) -> None:
        totals.last_event_timestamp = event.event_timestamp
        totals.last_event_id = event.event_id
        if event.supplier_id is not None:
            totals.supplier_id = event.supplier_id

    def _ensure_non_negative(
        self,
        zone_states: list[InventoryState],
        product_totals: list[ProductTotals],
    ) -> None:
        for state in zone_states:
            if state.available_quantity < 0:
                raise ValidationError(
                    f"Negative available quantity for product={state.product_id} zone={state.zone_id}: "
                    f"{state.available_quantity}"
                )
            if state.reserved_quantity < 0:
                raise ValidationError(
                    f"Negative reserved quantity for product={state.product_id} zone={state.zone_id}: "
                    f"{state.reserved_quantity}"
                )
        for totals in product_totals:
            if totals.total_available_quantity < 0:
                raise ValidationError(
                    f"Negative total available quantity for product={totals.product_id}: "
                    f"{totals.total_available_quantity}"
                )
            if totals.total_reserved_quantity < 0:
                raise ValidationError(
                    f"Negative total reserved quantity for product={totals.product_id}: "
                    f"{totals.total_reserved_quantity}"
                )

    def _validate_event(self, event: WarehouseEvent) -> None:
        if event.event_type in {
            EventType.PRODUCT_RECEIVED,
            EventType.PRODUCT_SHIPPED,
            EventType.PRODUCT_RESERVED,
            EventType.PRODUCT_RELEASED,
        }:
            if not event.product_id or not event.zone_id:
                raise ValidationError("product_id and zone_id are required")
            self._positive(event.quantity)
        elif event.event_type == EventType.PRODUCT_MOVED:
            if not event.product_id or not event.from_zone_id or not event.to_zone_id:
                raise ValidationError("product_id, from_zone_id and to_zone_id are required")
            self._positive(event.quantity)
        elif event.event_type == EventType.INVENTORY_COUNTED:
            if not event.product_id or not event.zone_id:
                raise ValidationError("product_id and zone_id are required")
            self._non_negative(event.counted_quantity)
        elif event.event_type in {EventType.ORDER_CREATED, EventType.ORDER_COMPLETED}:
            if not event.order_id:
                raise ValidationError("order_id is required")
            if event.event_type == EventType.ORDER_CREATED and not event.order_lines:
                raise ValidationError("order_lines must not be empty")
            for line in event.order_lines:
                self._positive(line.quantity)

    def _normalize_event(self, event: WarehouseEvent, existing_order: OrderState | None) -> WarehouseEvent:
        if event.event_type != EventType.ORDER_COMPLETED or event.order_lines:
            return event
        if existing_order is None:
            return event
        restored_lines = [
            OrderLine(**line)
            for line in json.loads(existing_order.items_json or "[]")
        ]
        normalized = deepcopy(event)
        normalized.order_lines = restored_lines
        normalized.raw_payload = {
            **event.raw_payload,
            "order_lines": [line.__dict__ for line in restored_lines],
        }
        return normalized

    def _positive(self, value: int | None) -> int:
        if value is None or value <= 0:
            raise ValidationError(f"Invalid quantity: {value} (must be positive)")
        return value

    def _non_negative(self, value: int | None) -> int:
        if value is None or value < 0:
            raise ValidationError(f"Invalid counted_quantity: {value} (must be non-negative)")
        return value
