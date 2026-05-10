from __future__ import annotations

import json
from datetime import UTC, datetime

from cassandra.cluster import Cluster
from cassandra.policies import DCAwareRoundRobinPolicy
from cassandra.query import BatchStatement, SimpleStatement
from cassandra import ConsistencyLevel

from app.config import Settings
from app.metrics import cassandra_write_errors_total
from app.models import InventoryState, OrderState, ProductTotals


CONSISTENCY_MAP = {
    "ONE": ConsistencyLevel.ONE,
    "QUORUM": ConsistencyLevel.QUORUM,
    "ALL": ConsistencyLevel.ALL,
}


class CassandraRepository:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.cluster = Cluster(
            contact_points=settings.cassandra_hosts,
            port=settings.cassandra_port,
            load_balancing_policy=DCAwareRoundRobinPolicy(local_dc="datacenter1"),
            protocol_version=5,
        )
        self.session = self.cluster.connect(settings.cassandra_keyspace)
        self.read_consistency = CONSISTENCY_MAP[settings.cassandra_read_consistency.upper()]
        self.write_consistency = CONSISTENCY_MAP[settings.cassandra_write_consistency.upper()]

    def close(self) -> None:
        self.cluster.shutdown()

    def ping(self) -> bool:
        self.session.execute("SELECT release_version FROM system.local")
        return True

    def is_processed(self, event_id: str) -> bool:
        statement = SimpleStatement(
            "SELECT event_id FROM processed_events WHERE event_id = %s",
            consistency_level=self.read_consistency,
        )
        row = self.session.execute(statement, (event_id,)).one()
        return row is not None

    def get_inventory(self, product_id: str, zone_id: str) -> InventoryState:
        statement = SimpleStatement(
            """
            SELECT product_id, zone_id, available_quantity, reserved_quantity,
                   last_event_timestamp, last_event_id, supplier_id
            FROM inventory_by_product_zone
            WHERE product_id = %s AND zone_id = %s
            """,
            consistency_level=self.read_consistency,
        )
        row = self.session.execute(statement, (product_id, zone_id)).one()
        if row is None:
            return InventoryState(product_id=product_id, zone_id=zone_id)
        return InventoryState(
            product_id=row.product_id,
            zone_id=row.zone_id,
            available_quantity=row.available_quantity or 0,
            reserved_quantity=row.reserved_quantity or 0,
            last_event_timestamp=self._to_utc(row.last_event_timestamp),
            last_event_id=row.last_event_id,
            supplier_id=row.supplier_id,
        )

    def get_product_totals(self, product_id: str) -> ProductTotals:
        statement = SimpleStatement(
            """
            SELECT product_id, total_available_quantity, total_reserved_quantity,
                   last_event_timestamp, last_event_id, supplier_id
            FROM inventory_by_product
            WHERE product_id = %s
            """,
            consistency_level=self.read_consistency,
        )
        row = self.session.execute(statement, (product_id,)).one()
        if row is None:
            return ProductTotals(product_id=product_id)
        return ProductTotals(
            product_id=row.product_id,
            total_available_quantity=row.total_available_quantity or 0,
            total_reserved_quantity=row.total_reserved_quantity or 0,
            last_event_timestamp=self._to_utc(row.last_event_timestamp),
            last_event_id=row.last_event_id,
            supplier_id=row.supplier_id,
        )

    def get_order(self, order_id: str) -> OrderState | None:
        statement = SimpleStatement(
            """
            SELECT order_id, status, last_event_timestamp, items_json
            FROM orders_by_id
            WHERE order_id = %s
            """,
            consistency_level=self.read_consistency,
        )
        row = self.session.execute(statement, (order_id,)).one()
        if row is None:
            return None
        return OrderState(
            order_id=row.order_id,
            status=row.status,
            last_event_timestamp=self._to_utc(row.last_event_timestamp),
            items_json=row.items_json or "[]",
        )

    def apply_inventory_batch(
        self,
        event_id: str,
        event_type: str,
        event_timestamp: datetime,
        kafka_partition: int,
        kafka_offset: int,
        inventory_states: list[InventoryState],
        product_totals: list[ProductTotals],
        order_state: OrderState | None,
        audit_payload: dict,
        status: str = "APPLIED",
        error_reason: str | None = None,
    ) -> None:
        batch = BatchStatement(consistency_level=self.write_consistency)
        processed_at = datetime.now(UTC)
        event_day = processed_at.date()
        payload_json = json.dumps(audit_payload, ensure_ascii=True)

        batch.add(
            """
            INSERT INTO processed_events (
              event_id, event_type, event_timestamp, processed_at,
              kafka_partition, kafka_offset, status, error_reason
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                event_id,
                event_type,
                event_timestamp,
                processed_at,
                kafka_partition,
                kafka_offset,
                status,
                error_reason,
            ),
        )
        batch.add(
            """
            INSERT INTO event_audit_by_day (
              event_day, processed_at, event_id, event_type, status, payload,
              error_reason, kafka_partition, kafka_offset
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                event_day,
                processed_at,
                event_id,
                event_type,
                status,
                payload_json,
                error_reason,
                kafka_partition,
                kafka_offset,
            ),
        )

        for state in inventory_states:
            batch.add(
                """
                INSERT INTO inventory_by_product_zone (
                  product_id, zone_id, available_quantity, reserved_quantity,
                  last_event_timestamp, last_event_id, supplier_id, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    state.product_id,
                    state.zone_id,
                    state.available_quantity,
                    state.reserved_quantity,
                    state.last_event_timestamp,
                    state.last_event_id,
                    state.supplier_id,
                    processed_at,
                ),
            )
            batch.add(
                """
                INSERT INTO inventory_by_zone (
                  zone_id, product_id, available_quantity, reserved_quantity,
                  last_event_timestamp, last_event_id, supplier_id, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    state.zone_id,
                    state.product_id,
                    state.available_quantity,
                    state.reserved_quantity,
                    state.last_event_timestamp,
                    state.last_event_id,
                    state.supplier_id,
                    processed_at,
                ),
            )

        for totals in product_totals:
            batch.add(
                """
                INSERT INTO inventory_by_product (
                  product_id, total_available_quantity, total_reserved_quantity,
                  last_event_timestamp, last_event_id, supplier_id, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    totals.product_id,
                    totals.total_available_quantity,
                    totals.total_reserved_quantity,
                    totals.last_event_timestamp,
                    totals.last_event_id,
                    totals.supplier_id,
                    processed_at,
                ),
            )

        if order_state is not None:
            batch.add(
                """
                INSERT INTO orders_by_id (
                  order_id, status, last_event_timestamp, updated_at, items_json
                ) VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    order_state.order_id,
                    order_state.status,
                    order_state.last_event_timestamp,
                    processed_at,
                    order_state.items_json,
                ),
            )

        try:
            self.session.execute(batch)
        except Exception:
            cassandra_write_errors_total.inc()
            raise

    def _to_utc(self, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
