"""Redis cache adapter. Redis is always a cache, never the source of truth."""
from __future__ import annotations

import json
from typing import Any


class RedisCacheAdapter:
    def __init__(
        self,
        *,
        url: str | None = None,
        client: Any = None,
        namespace: str = "liorin",
        default_ttl_seconds: int = 60,
    ) -> None:
        if client is None:
            try:
                import redis
            except ImportError as exc:
                raise RuntimeError("redis package is required for RedisCacheAdapter") from exc
            if not url:
                raise ValueError("Redis URL is required")
            client = redis.Redis.from_url(url, decode_responses=True)
        self.client = client
        self.namespace = namespace.strip(":")
        self.default_ttl_seconds = default_ttl_seconds

    def _key(self, key: str) -> str:
        return f"{self.namespace}:{key}"

    def get(self, key: str) -> Any | None:
        raw = self.client.get(self._key(key))
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return json.loads(raw)

    def set(self, key: str, value: Any, *, ttl_seconds: int | None = None) -> None:
        ttl = self.default_ttl_seconds if ttl_seconds is None else ttl_seconds
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        if ttl and ttl > 0:
            self.client.setex(self._key(key), ttl, payload)
        else:
            self.client.set(self._key(key), payload)

    def delete(self, key: str) -> None:
        self.client.delete(self._key(key))

    def invalidate_prefix(self, prefix: str) -> int:
        pattern = self._key(prefix) + "*"
        deleted = 0
        for key in self.client.scan_iter(match=pattern, count=200):
            deleted += int(self.client.delete(key) or 0)
        return deleted
