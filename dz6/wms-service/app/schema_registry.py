from __future__ import annotations

import io
import json
import struct
from functools import cached_property

import requests
from fastavro import parse_schema, schemaless_writer


class SchemaRegistryClient:
    def __init__(self, base_url: str, topic: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.subject = f"{topic}-value"

    @cached_property
    def versions(self) -> dict[int, tuple[int, dict]]:
        response = requests.get(
            f"{self.base_url}/subjects/{self.subject}/versions",
            timeout=10,
        )
        response.raise_for_status()
        versions = response.json()
        cache: dict[int, tuple[int, dict]] = {}
        for version in versions:
            version_response = requests.get(
                f"{self.base_url}/subjects/{self.subject}/versions/{version}",
                timeout=10,
            )
            version_response.raise_for_status()
            payload = version_response.json()
            cache[int(version)] = (payload["id"], parse_schema(json.loads(payload["schema"])))
        return cache

    def encode(self, payload: dict[str, object], schema_version: int) -> bytes:
        schema_id, schema = self.versions[schema_version]
        buffer = io.BytesIO()
        buffer.write(struct.pack(">bI", 0, schema_id))
        schemaless_writer(buffer, schema, payload)
        return buffer.getvalue()
