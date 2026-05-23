from __future__ import annotations

import logging

from confluent_kafka import Producer
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import Settings
from app.models import MovieEventIn
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

    def _partition_key(self, event: MovieEventIn) -> str:
        if self.settings.producer_partition_key == "movie_id":
            return event.movie_id
        return event.user_id

    @retry(
        reraise=True,
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type(Exception),
    )
    def publish(self, event: MovieEventIn) -> str:
        key = self._partition_key(event)
        payload = self.registry.encode(event.to_avro_dict())

        delivery_error: list[Exception] = []

        def callback(err, msg) -> None:
            if err is not None:
                delivery_error.append(RuntimeError(str(err)))
                return

            logger.info(
                "Published event_id=%s event_type=%s timestamp=%s partition=%s offset=%s",
                event.event_id,
                event.event_type.value,
                event.timestamp.isoformat(),
                msg.partition(),
                msg.offset(),
            )

        self.producer.produce(
            topic=self.settings.kafka_topic,
            key=key.encode("utf-8"),
            value=payload,
            on_delivery=callback,
        )
        self.producer.flush(10)

        if delivery_error:
            raise delivery_error[0]

        return key

    def safe_publish(self, event: MovieEventIn) -> str:
        return self.publish(event)
