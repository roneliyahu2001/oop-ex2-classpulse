from __future__ import annotations

import time
from typing import Callable

from ..events import EventBus
from ..models import Comment, DomainError
from ..repository import Repository
from .sessions import SessionService

MAX_LEN = 500


class CommentService:
    """Feature 2: questions and suggestions, live during class or offline afterwards.

    Comments are accepted on ended sessions too ("offline" feedback). The client
    keeps an outbox in localStorage and resends when the network is back.
    """

    def __init__(self, repo: Repository, sessions: SessionService, bus: EventBus,
                 clock: Callable[[], float] = time.time):
        self._repo = repo
        self._sessions = sessions
        self._bus = bus
        self._clock = clock

    def post(self, session_id: str, text: str, author: str = "") -> Comment:
        self._sessions.get(session_id)
        text = text.strip()
        if not text:
            raise DomainError("EMPTY_COMMENT", "Comment is empty")
        if len(text) > MAX_LEN:
            raise DomainError("COMMENT_TOO_LONG", f"Max {MAX_LEN} characters")
        c = self._repo.add_comment(session_id, text, author.strip()[:60] or "Anonymous", self._clock())
        self._bus.publish(session_id, "comment", c.to_dict())
        return c

    def upvote(self, comment_id: int, device_id: str) -> Comment:
        c = self._repo.get_comment(comment_id)
        if c is None:
            raise DomainError("COMMENT_NOT_FOUND", "No such comment", 404)
        if not self._repo.add_upvote(comment_id, device_id):
            raise DomainError("ALREADY_UPVOTED", "You already upvoted this", 409)
        c = self._repo.get_comment(comment_id)
        self._bus.publish(c.session_id, "comment", c.to_dict())
        return c

    def list(self, session_id: str) -> list[Comment]:
        self._sessions.get(session_id)
        return self._repo.list_comments(session_id)
