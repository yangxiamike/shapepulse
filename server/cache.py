from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Iterator, MutableMapping
from typing import Generic, TypeVar


K = TypeVar("K")
V = TypeVar("V")


class BoundedTTLCache(MutableMapping[K, V], Generic[K, V]):
    """A small LRU cache with deterministic entry and age limits."""

    def __init__(
        self,
        max_entries: int,
        ttl_seconds: float,
        *,
        clock=time.monotonic,
    ):
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self.max_entries = int(max_entries)
        self.ttl_seconds = float(ttl_seconds)
        self._clock = clock
        self._items: OrderedDict[K, tuple[float, V]] = OrderedDict()
        self.evictions = 0
        self.expirations = 0

    def _purge_expired(self) -> None:
        now = self._clock()
        expired = [
            key for key, (expires_at, _value) in self._items.items()
            if expires_at <= now
        ]
        for key in expired:
            self._items.pop(key, None)
            self.expirations += 1

    def __getitem__(self, key: K) -> V:
        self._purge_expired()
        expires_at, value = self._items[key]
        self._items.move_to_end(key)
        return value

    def get(self, key: K, default=None):
        try:
            return self[key]
        except KeyError:
            return default

    def __setitem__(self, key: K, value: V) -> None:
        self._purge_expired()
        self._items.pop(key, None)
        self._items[key] = (self._clock() + self.ttl_seconds, value)
        while len(self._items) > self.max_entries:
            self._items.popitem(last=False)
            self.evictions += 1

    def __delitem__(self, key: K) -> None:
        del self._items[key]

    def __iter__(self) -> Iterator[K]:
        self._purge_expired()
        return iter(tuple(self._items))

    def __len__(self) -> int:
        self._purge_expired()
        return len(self._items)

    def clear(self) -> None:
        self._items.clear()

    def info(self) -> dict[str, int | float]:
        return {
            "entries": len(self),
            "max_entries": self.max_entries,
            "ttl_seconds": self.ttl_seconds,
            "evictions": self.evictions,
            "expirations": self.expirations,
        }
