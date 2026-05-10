#!/usr/bin/env bash
set -euo pipefail

BOOTSTRAP_SERVER="kafka-1:9092"
REGISTRY_URL="http://schema-registry:8081"
TOPIC="warehouse-events"
DLQ_TOPIC="warehouse-events-dlq"
SUBJECT="${TOPIC}-value"

echo "Waiting for Kafka topic operations..."
sleep 5

kafka-topics --bootstrap-server "${BOOTSTRAP_SERVER}" --create --if-not-exists \
  --topic "${TOPIC}" \
  --partitions 3 \
  --replication-factor 2

kafka-topics --bootstrap-server "${BOOTSTRAP_SERVER}" --create --if-not-exists \
  --topic "${DLQ_TOPIC}" \
  --partitions 3 \
  --replication-factor 2

echo "Setting BACKWARD compatibility..."
curl -fsS -X PUT "${REGISTRY_URL}/config/${SUBJECT}" \
  -H "Content-Type: application/vnd.schemaregistry.v1+json" \
  --data '{"compatibility":"BACKWARD"}'

V1_SCHEMA=$(python3 - <<'PY'
import json
from pathlib import Path
print(json.dumps({"schema": Path("/schemas/warehouse-event-v1.avsc").read_text()}))
PY
)

V2_SCHEMA=$(python3 - <<'PY'
import json
from pathlib import Path
print(json.dumps({"schema": Path("/schemas/warehouse-event-v2.avsc").read_text()}))
PY
)

echo "Registering schema V1..."
curl -fsS -X POST "${REGISTRY_URL}/subjects/${SUBJECT}/versions" \
  -H "Content-Type: application/vnd.schemaregistry.v1+json" \
  --data "${V1_SCHEMA}"

echo "Registering schema V2..."
curl -fsS -X POST "${REGISTRY_URL}/subjects/${SUBJECT}/versions" \
  -H "Content-Type: application/vnd.schemaregistry.v1+json" \
  --data "${V2_SCHEMA}"

echo "Kafka topics and schemas initialized."
