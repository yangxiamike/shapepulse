from __future__ import annotations

import time
import sys
from collections import OrderedDict
from collections.abc import Iterator, MutableMapping
from typing import Any, Callable, Generic, TypeVar

try:
    import numpy as np
except ImportError:  # pragma: no cover - server runtime includes NumPy
    np = None

try:
    import pandas as pd
except ImportError:  # pragma: no cover - server runtime includes Pandas
    pd = None


K = TypeVar("K")
V = TypeVar("V")


def estimate_size_bytes(value: Any, _seen: set[int] | None = None) -> int:
    """Estimate retained bytes without serializing or copying the value."""

    seen = _seen if _seen is not None else set()
    identity = id(value)
    if identity in seen:
        return 0
    seen.add(identity)
    if pd is not None and isinstance(value, pd.DataFrame):
        return int(value.memory_usage(index=True, deep=True).sum())
    if pd is not None and isinstance(value, pd.Series):
        return int(value.memory_usage(index=True, deep=True))
    if np is not None and isinstance(value, np.ndarray):
        return int(value.nbytes)
    size = sys.getsizeof(value)
    if isinstance(value, dict):
        return size + sum(
            estimate_size_bytes(key, seen) + estimate_size_bytes(item, seen)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple, set, frozenset)):
        return size + sum(estimate_size_bytes(item, seen) for item in value)
    return size


class BoundedTTLCache(MutableMapping[K, V], Generic[K, V]):
    """A small LRU cache with deterministic entry, age, and byte limits."""

    def __init__(
        self,
        max_entries: int,
        ttl_seconds: float,
        *,
        clock=time.monotonic,
        max_bytes: int | None = None,
        weigher: Callable[[V], int] = estimate_size_bytes,
    ):
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if max_bytes is not None and max_bytes < 1:
            raise ValueError("max_bytes must be positive")
        self.max_entries = int(max_entries)
        self.ttl_seconds = float(ttl_seconds)
        self.max_bytes = None if max_bytes is None else int(max_bytes)
        self.current_bytes = 0
        self._clock = clock
        self._weigher = weigher
        self._items: OrderedDict[K, tuple[float, int, V]] = OrderedDict()
        self.evictions = 0
        self.expirations = 0
        self.oversized_rejections = 0

    def _purge_expired(self) -> None:
        now = self._clock()
        expired = [
            key for key, (expires_at, _weight, _value) in self._items.items()
            if expires_at <= now
        ]
        for key in expired:
            item = self._items.pop(key, None)
            if item is not None:
                self.current_bytes -= item[1]
            self.expirations += 1

    def __getitem__(self, key: K) -> V:
        self._purge_expired()
        _expires_at, _weight, value = self._items[key]
        self._items.move_to_end(key)
        return value

    def get(self, key: K, default=None):
        try:
            return self[key]
        except KeyError:
            return default

    def __setitem__(self, key: K, value: V) -> None:
        self._purge_expired()
        previous = self._items.pop(key, None)
        if previous is not None:
            self.current_bytes -= previous[1]
        weight = max(0, int(self._weigher(value)))
        if self.max_bytes is not None and weight > self.max_bytes:
            self.oversized_rejections += 1
            return
        self._items[key] = (self._clock() + self.ttl_seconds, weight, value)
        self.current_bytes += weight
        while len(self._items) > self.max_entries or (
            self.max_bytes is not None and self.current_bytes > self.max_bytes
        ):
            _old_key, (_expires, old_weight, _old_value) = self._items.popitem(last=False)
            self.current_bytes -= old_weight
            self.evictions += 1

    def __delitem__(self, key: K) -> None:
        _expires, weight, _value = self._items.pop(key)
        self.current_bytes -= weight

    def __iter__(self) -> Iterator[K]:
        self._purge_expired()
        return iter(tuple(self._items))

    def __len__(self) -> int:
        self._purge_expired()
        return len(self._items)

    def clear(self) -> None:
        self._items.clear()
        self.current_bytes = 0

    def info(self) -> dict[str, int | float]:
        return {
            "entries": len(self),
            "max_entries": self.max_entries,
            "ttl_seconds": self.ttl_seconds,
            "current_bytes": self.current_bytes,
            "max_bytes": self.max_bytes or 0,
            "evictions": self.evictions,
            "expirations": self.expirations,
            "oversized_rejections": self.oversized_rejections,
        }
