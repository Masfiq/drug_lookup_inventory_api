"""A tiny in-memory cache with an expiry time (TTL) and a size limit (LRU).

Popular searches ("ibuprofen", "insulin") are asked again and again, and the
drug catalog only changes when the ETL runs. Keeping recent answers in memory
for a few minutes means repeat searches skip the database entirely.

Tradeoff: each API process has its own cache, and a fresh ETL load can take up
to ``ttl_seconds`` to show up in cached searches. Both are fine for reference
data that changes weekly.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Hashable
from typing import Generic, TypeVar

V = TypeVar("V")


class TTLCache(Generic[V]):
    def __init__(
        self, ttl_seconds: float, max_size: int, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.ttl = ttl_seconds
        self.max_size = max_size
        self.clock = clock
        self.hits = 0
        self.misses = 0
        self._data: OrderedDict[Hashable, tuple[float, V]] = OrderedDict()
        self._lock = threading.Lock()  # FastAPI runs sync endpoints in a thread pool

    def get(self, key: Hashable) -> V | None:
        with self._lock:
            entry = self._data.get(key)
            if entry is None or entry[0] < self.clock():
                if entry is not None:
                    del self._data[key]  # expired
                self.misses += 1
                return None
            self._data.move_to_end(key)  # mark as recently used
            self.hits += 1
            return entry[1]

    def set(self, key: Hashable, value: V) -> None:
        with self._lock:
            self._data[key] = (self.clock() + self.ttl, value)
            self._data.move_to_end(key)
            while len(self._data) > self.max_size:
                self._data.popitem(last=False)  # drop the least recently used

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
            self.hits = self.misses = 0

    def __len__(self) -> int:
        return len(self._data)
