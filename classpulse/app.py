"""Composition root: wires repositories, services and strategies together."""
from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from typing import Callable

from .events import EventBus
from .llm import LLMClient
from .repository import Repository
from .services.attendance import AttendanceService
from .services.comments import CommentService
from .services.polls import PollService
from .services.review import LLMReviewer, ReviewService
from .services.sessions import SessionService
from .services.summary import LLMSummarizer, SummaryService
from .tokens import TokenRotator


@dataclass
class Config:
    db_path: str = "classpulse.db"
    lecturer_pin: str = ""
    public_url: str = "http://localhost:8000"
    token_period: int = 20
    secret: bytes = b""


class ClassPulseApp:
    def __init__(self, config: Config, llm: LLMClient | None = None,
                 clock: Callable[[], float] = time.time):
        self.config = config
        self.secret = config.secret or secrets.token_bytes(32)
        self.bus = EventBus()
        self.repo = Repository(config.db_path)
        self.rotator = TokenRotator(self.secret, config.token_period, clock)
        self.sessions = SessionService(self.repo, self.bus, clock)
        self.attendance = AttendanceService(self.repo, self.sessions, self.rotator, self.bus, clock)
        self.comments = CommentService(self.repo, self.sessions, self.bus, clock)
        self.polls = PollService(self.repo, self.sessions, self.bus, clock)
        self.summary = SummaryService(LLMSummarizer(llm) if llm else None)
        self.reviews = ReviewService(self.repo, self.sessions, LLMReviewer(llm) if llm else None,
                                     clock=clock)
        self.llm_enabled = llm is not None

    def checkin_url(self, session_id: str) -> str:
        return f"{self.config.public_url}/?s={session_id}&t={self.rotator.current(session_id)}"
