from __future__ import annotations

import time

from cassandra.cluster import Cluster

from app.config import get_settings


SCHEMA_STATEMENTS = [
    """
    CREATE KEYSPACE IF NOT EXISTS warehouse
    WITH replication = {'class': 'NetworkTopologyStrategy', 'datacenter1': 3}
    """,
    """
    CREATE TABLE IF NOT EXISTS warehouse.inventory_by_product_zone (
      product_id text,
      zone_id text,
      available_quantity int,
      reserved_quantity int,
      last_event_timestamp timestamp,
      last_event_id text,
      supplier_id text,
      updated_at timestamp,
      PRIMARY KEY ((product_id), zone_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS warehouse.inventory_by_product (
      product_id text PRIMARY KEY,
      total_available_quantity int,
      total_reserved_quantity int,
      last_event_timestamp timestamp,
      last_event_id text,
      supplier_id text,
      updated_at timestamp
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS warehouse.inventory_by_zone (
      zone_id text,
      product_id text,
      available_quantity int,
      reserved_quantity int,
      last_event_timestamp timestamp,
      last_event_id text,
      supplier_id text,
      updated_at timestamp,
      PRIMARY KEY ((zone_id), product_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS warehouse.orders_by_id (
      order_id text PRIMARY KEY,
      status text,
      last_event_timestamp timestamp,
      updated_at timestamp,
      items_json text
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS warehouse.processed_events (
      event_id text PRIMARY KEY,
      event_type text,
      event_timestamp timestamp,
      processed_at timestamp,
      kafka_partition int,
      kafka_offset bigint,
      status text,
      error_reason text
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS warehouse.event_audit_by_day (
      event_day date,
      processed_at timestamp,
      event_id text,
      event_type text,
      status text,
      payload text,
      error_reason text,
      kafka_partition int,
      kafka_offset bigint,
      PRIMARY KEY ((event_day), processed_at, event_id)
    ) WITH CLUSTERING ORDER BY (processed_at DESC, event_id ASC)
    """,
]


def main() -> None:
    settings = get_settings()
    last_error: Exception | None = None
    for _ in range(30):
        try:
            cluster = Cluster(contact_points=settings.cassandra_hosts, port=settings.cassandra_port)
            session = cluster.connect()
            for statement in SCHEMA_STATEMENTS:
                session.execute(statement)
            cluster.shutdown()
            print("Cassandra schema applied successfully.")
            return
        except Exception as exc:
            last_error = exc
            time.sleep(5)
    raise RuntimeError("Could not initialize Cassandra schema") from last_error


if __name__ == "__main__":
    main()
