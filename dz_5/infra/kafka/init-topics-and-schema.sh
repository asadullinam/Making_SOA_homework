#!/bin/bash
set -euo pipefail

BOOTSTRAP_SERVERS="kafka-1:9092,kafka-2:9092"
TOPIC_NAME="movie-events"
SCHEMA_REGISTRY_URL="http://schema-registry:8081"
SCHEMA_SUBJECT="${TOPIC_NAME}-value"

echo "Waiting for Kafka and Schema Registry..."
until kafka-topics --bootstrap-server "${BOOTSTRAP_SERVERS}" --list >/dev/null 2>&1; do
  sleep 2
done

until curl -fsS "${SCHEMA_REGISTRY_URL}/subjects" >/dev/null; do
  sleep 2
done

echo "Creating topic ${TOPIC_NAME}..."
kafka-topics \
  --bootstrap-server "${BOOTSTRAP_SERVERS}" \
  --create \
  --if-not-exists \
  --topic "${TOPIC_NAME}" \
  --partitions 3 \
  --replication-factor 2 \
  --config min.insync.replicas=1

echo "Registering Avro schema for ${SCHEMA_SUBJECT}..."
schema_payload="$(
  awk '
    BEGIN { printf "{\"schema\":\"" }
    {
      gsub(/\\/,"\\\\");
      gsub(/"/,"\\\"");
      printf "%s\\n", $0
    }
    END { printf "\",\"schemaType\":\"AVRO\"}" }
  ' /schemas/movie-event.avsc
)"
curl -fsS \
  -X POST \
  -H "Content-Type: application/vnd.schemaregistry.v1+json" \
  --data "${schema_payload}" \
  "${SCHEMA_REGISTRY_URL}/subjects/${SCHEMA_SUBJECT}/versions" >/tmp/schema-result.json

echo "Schema registration result:"
cat /tmp/schema-result.json
