"""In-process publish/subscribe used to push live updates over Server-Sent Events."""
from __future__ import annotations

import queue
import threading
from collections import defaultdict


class EventBus:
    def __init__(self):
        self._subs: dict[str, set[queue.Queue]] = defaultdict(set)
        self._lock = threading.Lock()

    def subscribe(self, channel: str) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=100)
        with self._lock:
            self._subs[channel].add(q)
        return q

    def unsubscribe(self, channel: str, q: queue.Queue) -> None:
        with self._lock:
            self._subs[channel].discard(q)

    def publish(self, channel: str, event: str, data: dict) -> None:
        with self._lock:
            targets = list(self._subs[channel])
        for q in targets:
            try:
                q.put_nowait((event, data))
            except queue.Full:  # a dead or very slow client; drop rather than block
                pass

    def subscriber_count(self, channel: str) -> int:
        with self._lock:
            return len(self._subs[channel])
