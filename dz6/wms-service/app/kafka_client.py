from __future__ import annotations

import logging

from confluent_kafka import Producer

from app.config import Settings
from app.models import WarehouseEventIn
from app.schema_registry import SchemaRegistryClient

logger = logging.getLogger(__name__)


class KafkaPublisher:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.registry = SchemaRegistryClient(settings.schema_registry_url, settings.kafka_topic)
        self.producer = Producer(
            {
                "bootstrap.servers": settings.kafka_bootstrap_servers,
                "acks": settings.kafka_acks,
                "enable.idempotence": True,
                "socket.timeout.ms": 10000,
                "message.timeout.ms": 30000,
            }
        )

    def publish(self, event: WarehouseEventIn, schema_version: int) -> None:
        payload = self.registry.encode(event.to_avro_dict(schema_version), schema_version=schema_version)
        errors: list[Exception] = []

        def callback(err, msg) -> None:
            if err is not None:
                errors.append(RuntimeError(str(err)))
                return
            logger.info(
                "Published event_id=%s event_type=%s schema_version=%s partition=%s offset=%s",
                event.event_id,
                event.event_type.value,
                schema_version,
                msg.partition(),
                msg.offset(),
            )

        self.producer.produce(
            topic=self.settings.kafka_topic,
            key=(event.order_id or event.product_id or event.event_id).encode("utf-8"),
            value=payload,
            on_delivery=callback,
        )
        self.producer.flush(10)

        if errors:
            raise errors[0]
