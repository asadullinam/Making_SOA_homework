from __future__ import annotations

import json
import io
import struct
from functools import cached_property

import requests
from fastavro import parse_schema, schemaless_writer


class SchemaRegistryClient:
    def __init__(self, base_url: str, topic: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.subject = f"{topic}-value"

    @cached_property
    def latest_schema(self) -> tuple[int, dict]:
        response = requests.get(
            f"{self.base_url}/subjects/{self.subject}/versions/latest",
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
        return payload["id"], parse_schema(json.loads(payload["schema"]))

    def encode(self, payload: dict[str, object]) -> bytes:
        schema_id, schema = self.latest_schema
        buffer = io.BytesIO()
        buffer.write(struct.pack(">bI", 0, schema_id))
        schemaless_writer(buffer, schema, payload)
        return buffer.getvalue()
