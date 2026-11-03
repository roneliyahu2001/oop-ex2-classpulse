from __future__ import annotations

import time
from typing import Callable

from ..events import EventBus
from ..models import DomainError, Poll
from ..repository import Repository
from .sessions import SessionService


class PollService:
    """Feature 3: on-the-spot polls. KISS: one question, 2-6 options, one vote per phone."""

    def __init__(self, repo: Repository, sessions: SessionService, bus: EventBus,
                 clock: Callable[[], float] = time.time):
        self._repo = repo
        self._sessions = sessions
        self._bus = bus
        self._clock = clock

    def create(self, session_id: str, question: str, options: list[str]) -> Poll:
        self._sessions.require_active(session_id)
        question = question.strip()
        options = [o.strip() for o in options if o and o.strip()]
        if not question:
            raise DomainError("QUESTION_REQUIRED", "Question is required")
        if not 2 <= len(options) <= 6:
            raise DomainError("BAD_OPTIONS", "A poll needs 2 to 6 options")
        # Only one open poll at a time keeps the student screen simple.
        for p in self._repo.list_polls(session_id):
            if p.is_open:
                self._repo.close_poll(p.id)
        poll = self._repo.add_poll(session_id, question[:200], [o[:80] for o in options], self._clock())
        self._bus.publish(session_id, "poll", poll.to_dict())
        return poll

    def get(self, poll_id: int) -> Poll:
        p = self._repo.get_poll(poll_id)
        if p is None:
            raise DomainError("POLL_NOT_FOUND", "No such poll", 404)
        return p

    def vote(self, poll_id: int, option_index: int, device_id: str) -> Poll:
        p = self.get(poll_id)
        if not p.is_open:
            raise DomainError("POLL_CLOSED", "This poll is closed", 409)
        if not 0 <= option_index < len(p.options):
            raise DomainError("BAD_OPTION", "No such option")
        if not self._repo.add_vote(poll_id, device_id, option_index):
            raise DomainError("ALREADY_VOTED", "You already voted", 409)
        p = self.get(poll_id)
        self._bus.publish(p.session_id, "poll", p.to_dict())
        return p

    def close(self, poll_id: int) -> Poll:
        self.get(poll_id)
        self._repo.close_poll(poll_id)
        p = self.get(poll_id)
        self._bus.publish(p.session_id, "poll", p.to_dict())
        return p

    def list(self, session_id: str) -> list[Poll]:
        self._sessions.get(session_id)
        return self._repo.list_polls(session_id)

    def open_poll(self, session_id: str) -> Poll | None:
        return next((p for p in reversed(self.list(session_id)) if p.is_open), None)
