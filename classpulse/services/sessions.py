from __future__ import annotations

import secrets
import time
from typing import Callable

from ..events import EventBus
from ..models import ClassSession, DomainError
from ..repository import Repository


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

    def end(self, session_id: str) -> ClassSession:
        self.require_active(session_id)
        self._repo.end_session(session_id, self._clock())
        s = self.get(session_id)
        self._bus.publish(session_id, "session", s.to_dict())
        return s

    def list(self) -> list[ClassSession]:
        return self._repo.list_sessions()
