"""In-process publish/subscribe used to push live updates over Server-Sent Events.

Each session has two channels: a public one every phone listens to, and a
staff one only the lecturer's dashboard may join. Anything that would reveal
who is in the class goes to the staff channel.
"""
from __future__ import annotations

import queue
import threading
from collections import defaultdict


def staff_channel(session_id: str) -> str:
    return f"{session_id}#staff"


class EventBus:
    def __init__(self):
        self._subs: dict[str, set[queue.Queue]] = defaultdict(set)
        self._lock = threading.Lock()

    def subscribe(self, *channels: str) -> queue.Queue:
        """One queue that receives the events of all the given channels."""
        q: queue.Queue = queue.Queue(maxsize=100)
        with self._lock:
            for channel in channels:
                self._subs[channel].add(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            for subs in self._subs.values():
                subs.discard(q)

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
