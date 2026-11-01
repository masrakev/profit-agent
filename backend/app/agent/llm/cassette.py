"""Record / replay of model calls.

A cassette is one HTTP exchange with the Meta Model API, keyed by the SHA-256 of the normalised
request (method, path and JSON body with sorted keys; headers, including the key, are never part
of it). A multipart upload (voice transcription) is normalised part by part: its JSON part as
JSON, its audio as a hash, never the audio itself. Cassettes are committed under
`backend/tests/cassettes/`:

- `recorded/`: real responses written in `record` mode (synthetic benchmark data only);
- `synthetic/`: hand-written responses in the documented format, marked `"synthetic": true`,
  until real ones are recorded. Replay prefers a recorded cassette over a synthetic one.

Modes: `live` (network), `record` (network, then write the cassette), `replay` (cassettes only;
a miss raises `CassetteMissError`, so CI fails instead of calling a model).
"""

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import httpx2

from app.agent.llm.errors import CassetteMissError
from app.domain.hashing import canonical_json, sha256_hex

KEPT_RESPONSE_HEADERS = ("content-type", "retry-after")
KEPT_HEADER_PREFIX = "x-ratelimit-"


class LLMMode(StrEnum):
    LIVE = "live"
    RECORD = "record"
    REPLAY = "replay"


def normalized_request(request: httpx2.Request) -> dict[str, Any]:
    raw = request.read()
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/form-data"):
        body: Any = multipart_body(raw, content_type)
    else:
        body = json.loads(raw) if raw else None
    return {"method": request.method, "path": request.url.path, "body": body}


_BOUNDARY = re.compile(r'boundary="?([^";]+)"?')
_NAME = re.compile(r'\bname="([^"]*)"')


def multipart_body(raw: bytes, content_type: str) -> dict[str, Any]:
    """A multipart body by part name, without its random boundary: JSON parts parsed, any other
    part (audio) as its SHA-256, size and type only, so a cassette never holds the audio."""
    found = _BOUNDARY.search(content_type)
    if found is None:
        raise ValueError("multipart request without a boundary")
    parts: dict[str, Any] = {}
    for chunk in raw.split(b"--" + found.group(1).encode())[1:]:
        if chunk.startswith(b"--"):  # the closing delimiter
            break
        head, _, payload = chunk.removeprefix(b"\r\n").partition(b"\r\n\r\n")
        headers = {}
        for line in head.decode("utf-8").split("\r\n"):
            key, _, value = line.partition(":")
            headers[key.strip().lower()] = value.strip()
        payload = payload.removesuffix(b"\r\n")
        name = _NAME.search(headers.get("content-disposition", ""))
        kind = headers.get("content-type", "")
        parts[name.group(1) if name else ""] = (
            json.loads(payload)
            if kind.startswith("application/json")
            else {
                "sha256": hashlib.sha256(payload).hexdigest(),
                "bytes": len(payload),
                "type": kind,
            }
        )
    return parts


def cassette_key(normalized: dict[str, Any]) -> str:
    return sha256_hex(canonical_json(normalized))


def _summary(normalized: dict[str, Any]) -> str:
    body = normalized.get("body") or {}
    model = body.get("model") or (body.get("request") or {}).get("model")
    items = body.get("input") or []
    last = items[-1].get("type") if items and isinstance(items[-1], dict) else None
    return f"{normalized['method']} {normalized['path']} model={model} last={last}"


@dataclass(frozen=True)
class Cassette:
    key: str
    synthetic: bool
    note: str
    request: dict[str, Any]
    status: int
    headers: dict[str, str]
    body: Any

    def to_json(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "synthetic": self.synthetic,
            "note": self.note,
            "request": self.request,
            "response": {"status": self.status, "headers": self.headers, "body": self.body},
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Cassette":
        response = data["response"]
        return cls(
            key=data["key"],
            synthetic=bool(data["synthetic"]),
            note=str(data.get("note", "")),
            request=data["request"],
            status=int(response["status"]),
            headers=dict(response.get("headers", {})),
            body=response["body"],
        )


class CassetteStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.recorded = root / "recorded"
        self.synthetic = root / "synthetic"

    def find(self, key: str) -> Cassette | None:
        for folder in (self.recorded, self.synthetic):
            path = folder / f"{key}.json"
            if path.exists():
                cassette = Cassette.from_json(json.loads(path.read_text(encoding="utf-8")))
                if cassette.key != key:
                    raise ValueError(f"{path} holds cassette {cassette.key}, not {key}")
                return cassette
        return None

    def save(self, cassette: Cassette) -> Path:
        folder = self.synthetic if cassette.synthetic else self.recorded
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{cassette.key}.json"
        path.write_text(
            json.dumps(cassette.to_json(), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return path

    def all(self) -> list[tuple[Path, Cassette]]:
        found = []
        for folder in (self.recorded, self.synthetic):
            for path in sorted(folder.glob("*.json")) if folder.exists() else []:
                found.append(
                    (path, Cassette.from_json(json.loads(path.read_text(encoding="utf-8"))))
                )
        return found


class ReplayTransport(httpx2.BaseTransport):
    def __init__(self, store: CassetteStore) -> None:
        self.store = store
        self.served: list[str] = []

    def handle_request(self, request: httpx2.Request) -> httpx2.Response:
        normalized = normalized_request(request)
        key = cassette_key(normalized)
        cassette = self.store.find(key)
        if cassette is None:
            raise CassetteMissError(key, _summary(normalized))
        self.served.append(key)
        return httpx2.Response(
            cassette.status, headers=cassette.headers, json=cassette.body, request=request
        )


class RecordTransport(httpx2.BaseTransport):
    """Forwards to `inner` and writes every exchange as a cassette."""

    def __init__(
        self,
        inner: httpx2.BaseTransport,
        store: CassetteStore,
        *,
        synthetic: bool = False,
        note: str = "",
    ) -> None:
        self.inner = inner
        self.store = store
        self.synthetic = synthetic
        self.note = note
        self.written: list[Path] = []

    def close(self) -> None:
        self.inner.close()  # the real connections

    def handle_request(self, request: httpx2.Request) -> httpx2.Response:
        normalized = normalized_request(request)
        response = self.inner.handle_request(request)
        content = response.read()
        headers = {
            k.lower(): v
            for k, v in response.headers.items()
            if k.lower() in KEPT_RESPONSE_HEADERS or k.lower().startswith(KEPT_HEADER_PREFIX)
        }
        body = json.loads(content) if content else None
        cassette = Cassette(
            key=cassette_key(normalized),
            synthetic=self.synthetic,
            note=self.note,
            request=normalized,
            status=response.status_code,
            headers=headers,
            body=body,
        )
        self.written.append(self.store.save(cassette))
        # `content` is already decoded: drop the headers that describe the wire encoding.
        passed = {
            k: v
            for k, v in response.headers.items()
            if k.lower() not in ("content-encoding", "content-length", "transfer-encoding")
        }
        return httpx2.Response(
            response.status_code, headers=passed, content=content, request=request
        )
