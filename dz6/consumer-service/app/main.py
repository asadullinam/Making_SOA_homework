from __future__ import annotations

import base64
import json
import logging
import threading
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from cassandra import InvalidRequest
from confluent_kafka import Consumer, Producer, TopicPartition
from fastapi import FastAPI, Response, status
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.cassandra_repo import CassandraRepository
from app.config import get_settings
from app.metrics import consumer_lag, event_processing_duration_seconds, events_processed_total
from app.models import EventProcessingError, KafkaMetadata, ValidationError, WarehouseEvent
from app.processor import WarehouseProcessor
from app.schema_registry import SchemaRegistryDecoder

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [consumer-service] %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

settings = get_settings()


class ConsumerRuntime:
    def __init__(self) -> None:
        self.repo: CassandraRepository | None = None
        self.processor: WarehouseProcessor | None = None
        self.decoder = SchemaRegistryDecoder(settings.schema_registry_url)
        self.consumer: Consumer | None = None
        self.dlq_producer: Producer | None = None
        self.kafka_connected = False
        self.cassandra_connected = False
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run_loop, daemon=True)

    def start(self) -> None:
        self.repo = self._connect_cassandra_with_retry()
        self.processor = WarehouseProcessor(self.repo)
        self.consumer = Consumer(
            {
                "bootstrap.servers": settings.kafka_bootstrap_servers,
                "group.id": settings.kafka_consumer_group,
                "enable.auto.commit": False,
                "auto.offset.reset": "earliest",
            }
        )
        self.dlq_producer = Producer(
            {
                "bootstrap.servers": settings.kafka_bootstrap_servers,
                "acks": "all",
                "enable.idempotence": True,
            }
        )
        self.repo.ping()
        self.cassandra_connected = True
        self.consumer.subscribe([settings.kafka_topic])
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread.is_alive():
            self.thread.join(timeout=10)
        if self.consumer is not None:
            self.consumer.close()
        if self.repo is not None:
            self.repo.close()

    def health(self) -> bool:
        try:
            self.cassandra_connected = self.repo is not None and self.repo.ping()
        except Exception:
            self.cassandra_connected = False
        try:
            self.kafka_connected = self.consumer is not None and self._ping_kafka()
        except Exception:
            self.kafka_connected = False
        return self.kafka_connected and self.cassandra_connected

    def _run_loop(self) -> None:
        if self.consumer is None or self.processor is None:
            raise RuntimeError("Consumer runtime has not been started")
        while not self.stop_event.is_set():
            message = self.consumer.poll(1.0)
            self._update_lag_metrics()
            if message is None:
                continue
            if message.error():
                logger.error("Kafka consumer error: %s", message.error())
                self.kafka_connected = False
                time.sleep(1)
                continue

            self.kafka_connected = True
            started_at = time.perf_counter()
            raw_payload_for_dlq: dict | None = None
            try:
                schema_version, payload = self.decoder.decode(message.value())
                raw_payload_for_dlq = payload
                event = WarehouseEvent.from_payload(payload, schema_version=schema_version)
                result = self.processor.process(
                    event,
                    KafkaMetadata(partition=message.partition(), offset=message.offset()),
                )
                self.consumer.commit(message=message, asynchronous=False)
                if result.status == "APPLIED":
                    events_processed_total.labels(event_type=result.event_type).inc()
                logger.info(
                    "Processed event_id=%s event_type=%s status=%s partition=%s offset=%s schema_version=%s",
                    event.event_id,
                    event.event_type.value,
                    result.status,
                    message.partition(),
                    message.offset(),
                    schema_version,
                )
            except (ValidationError, EventProcessingError, InvalidRequest, Exception) as exc:
                error_code = getattr(exc, "code", exc.__class__.__name__.upper())
                raw_payload_for_dlq = raw_payload_for_dlq or {
                    "raw_value_base64": base64.b64encode(message.value()).decode("ascii")
                }
                self._publish_dlq(
                    original_event=raw_payload_for_dlq,
                    error_reason=str(exc),
                    error_code=error_code,
                    partition=message.partition(),
                    offset=message.offset(),
                )
                self.consumer.commit(message=message, asynchronous=False)
                logger.exception(
                    "Sent event to DLQ partition=%s offset=%s error_code=%s",
                    message.partition(),
                    message.offset(),
                    error_code,
                )
            finally:
                event_processing_duration_seconds.observe(time.perf_counter() - started_at)

    def _publish_dlq(
        self,
        original_event: dict,
        error_reason: str,
        error_code: str,
        partition: int,
        offset: int,
    ) -> None:
        payload = json.dumps(
            {
                "original_event": original_event,
                "error_reason": error_reason,
                "error_code": error_code,
                "failed_at": datetime.now(UTC).isoformat(),
                "kafka_metadata": {
                    "partition": partition,
                    "offset": offset,
                },
            },
            ensure_ascii=True,
        ).encode("utf-8")
        delivery_errors: list[Exception] = []

        def callback(err, msg) -> None:
            if err is not None:
                delivery_errors.append(RuntimeError(str(err)))
                return
            logger.info(
                "Published DLQ message topic=%s partition=%s offset=%s",
                msg.topic(),
                msg.partition(),
                msg.offset(),
            )

        self.dlq_producer.produce(
            topic=settings.kafka_dlq_topic,
            value=payload,
            on_delivery=callback,
        )
        self.dlq_producer.flush(10)
        if delivery_errors:
            raise delivery_errors[0]

    def _update_lag_metrics(self) -> None:
        if self.consumer is None:
            return
        assignments = self.consumer.assignment()
        if not assignments:
            return
        committed = {
            tp.partition: tp.offset
            for tp in self.consumer.committed(
                [TopicPartition(tp.topic, tp.partition) for tp in assignments],
                timeout=5,
            )
        }
        for tp in assignments:
            low, high = self.consumer.get_watermark_offsets(tp, timeout=5)
            committed_offset = committed.get(tp.partition, low)
            if committed_offset is None or committed_offset < 0:
                committed_offset = low
            lag = max(high - committed_offset, 0)
            consumer_lag.labels(partition=str(tp.partition)).set(lag)

    def _connect_cassandra_with_retry(self) -> CassandraRepository:
        last_error: Exception | None = None
        for _ in range(12):
            try:
                return CassandraRepository(settings)
            except Exception as exc:
                last_error = exc
                time.sleep(5)
        raise RuntimeError("Could not connect to Cassandra") from last_error

    def _ping_kafka(self) -> bool:
        if self.consumer is None:
            return False
        metadata = self.consumer.list_topics(timeout=5)
        return settings.kafka_topic in metadata.topics


runtime = ConsumerRuntime()


@asynccontextmanager
async def lifespan(_: FastAPI):
    runtime.start()
    yield
    runtime.stop()


app = FastAPI(title="Smart Warehouse Consumer Service", lifespan=lifespan)


@app.get("/health")
def health(response: Response) -> dict[str, str]:
    if runtime.health():
        response.status_code = status.HTTP_200_OK
        return {"status": "ok"}
    response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "degraded"}


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
