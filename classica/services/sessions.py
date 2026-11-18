from __future__ import annotations

import secrets
import time
from typing import Callable

from ..events import EventBus
from ..geo import valid_coordinates
from ..models import ClassSession, DomainError
from ..repository import Repository

GEO_MODES = ("off", "flag", "block")
MIN_RADIUS_M, MAX_RADIUS_M = 30, 5000
MAX_HEADCOUNT = 2000


class SessionService:
    """Opens and closes class meetings. Every other feature hangs off a session."""

    def __init__(self, repo: Repository, bus: EventBus, clock: Callable[[], float] = time.time):
        self._repo = repo
        self._bus = bus
        self._clock = clock

    def start(self, title: str) -> ClassSession:
        title = title.strip()
        if not title:
            raise DomainError("TITLE_REQUIRED", "Session title is required")
        s = ClassSession(id=secrets.token_hex(3), title=title[:120], started_at=self._clock())
        self._repo.add_session(s)
        return s

    def get(self, session_id: str) -> ClassSession:
        s = self._repo.get_session(session_id)
        if s is None:
            raise DomainError("SESSION_NOT_FOUND", "No such session", 404)
        return s

    def require_active(self, session_id: str) -> ClassSession:
        s = self.get(session_id)
        if not s.is_active:
            raise DomainError("SESSION_CLOSED", "This class session has ended", 409)
        return s

    def active(self) -> ClassSession | None:
        """The class that is open right now (the newest one, if the lecturer left several open)."""
        return next((s for s in self._repo.list_sessions() if s.is_active), None)

    def end(self, session_id: str) -> ClassSession:
        self.require_active(session_id)
        self._repo.end_session(session_id, self._clock())
        return self._changed(session_id)

    def list(self) -> list[ClassSession]:
        return self._repo.list_sessions()

    def set_homework_task(self, session_id: str, task: str) -> ClassSession:
        self.get(session_id)
        self._repo.set_homework_task(session_id, task.strip()[:2000])
        return self._changed(session_id)

    def save_summary(self, session_id: str, summary: str, published: bool) -> ClassSession:
        """Stores the lesson summary. Students see it only once it is published."""
        self.get(session_id)
        summary = summary.strip()[:30_000]
        self._repo.set_summary(session_id, summary, published and bool(summary))
        return self._changed(session_id)

    def set_geofence(self, session_id: str, mode: str, lat: float | None = None,
                     lon: float | None = None, radius: int = 150) -> ClassSession:
        """Turns the location check on (around the given point) or off."""
        self.get(session_id)
        if mode not in GEO_MODES:
            raise DomainError("BAD_LOCATION", "Unknown location-check mode")
        if mode == "off":
            self._repo.set_geofence(session_id, "off", None, None, 0)
        else:
            if lat is None or lon is None or not valid_coordinates(lat, lon):
                raise DomainError("BAD_LOCATION", "The classroom location is missing or invalid")
            radius = max(MIN_RADIUS_M, min(int(radius), MAX_RADIUS_M))
            self._repo.set_geofence(session_id, mode, lat, lon, radius)
        return self._changed(session_id)

    def set_headcount(self, session_id: str, count: int | None) -> ClassSession:
        """Stores how many people the lecturer's class photo shows. Only the number is kept:
        the photo is analysed in the lecturer's browser and never uploaded."""
        self.get(session_id)
        if count is not None and not 0 <= count <= MAX_HEADCOUNT:
            raise DomainError("BAD_HEADCOUNT", f"The head count must be 0 to {MAX_HEADCOUNT}")
        self._repo.set_headcount(session_id, count, None if count is None else self._clock())
        return self.get(session_id)  # nothing public changed, so no event

    def _changed(self, session_id: str) -> ClassSession:
        s = self.get(session_id)
        self._bus.publish(session_id, "session", s.to_dict())
        return s
