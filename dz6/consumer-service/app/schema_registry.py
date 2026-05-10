from __future__ import annotations

import io
import json
import struct
from functools import lru_cache

import requests
from fastavro import parse_schema, schemaless_reader


class SchemaRegistryDecoder:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    @lru_cache(maxsize=32)
    def _schema_by_id(self, schema_id: int) -> tuple[int, dict]:
        response = requests.get(f"{self.base_url}/schemas/ids/{schema_id}", timeout=10)
        response.raise_for_status()
        payload = response.json()
        schema = parse_schema(json.loads(payload["schema"]))
        subject_response = requests.get(f"{self.base_url}/subjects", timeout=10)
        subject_response.raise_for_status()
        version = 2
        for subject in subject_response.json():
            if not subject.endswith("-value"):
                continue
            versions_response = requests.get(f"{self.base_url}/subjects/{subject}/versions", timeout=10)
            versions_response.raise_for_status()
            for candidate_version in versions_response.json():
                candidate_response = requests.get(
                    f"{self.base_url}/subjects/{subject}/versions/{candidate_version}",
                    timeout=10,
                )
                candidate_response.raise_for_status()
                if candidate_response.json()["id"] == schema_id:
                    version = int(candidate_version)
                    break
        return version, schema

    def decode(self, payload: bytes) -> tuple[int, dict]:
        buffer = io.BytesIO(payload)
        magic, schema_id = struct.unpack(">bI", buffer.read(5))
        if magic != 0:
            raise ValueError("Unsupported schema registry payload header")
        schema_version, schema = self._schema_by_id(schema_id)
        data = schemaless_reader(buffer, schema)
        return schema_version, data
