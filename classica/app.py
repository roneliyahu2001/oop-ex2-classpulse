"""Composition root: wires repositories, services and strategies together."""
from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from typing import Callable

from .events import EventBus
from .llm import LLMClient
from .ratelimit import RateLimiter
from .repository import Repository
from .services.attendance import AttendanceService
from .services.comments import CommentService
from .services.polls import PollService
from .services.reports import ReportService
from .services.review import LLMReviewer, ReviewService
from .services.sessions import SessionService
from .services.summary import LLMSummarizer, SummaryService
from .tokens import TokenRotator


@dataclass
class Config:
    db_path: str = "classica.db"
    lecturer_pin: str = ""
    public_url: str = "http://localhost:8000"
    token_period: int = 20
    late_after_minutes: int = 15
    secret: bytes = b""


class ClassicaApp:
    def __init__(self, config: Config, llm: LLMClient | None = None,
                 clock: Callable[[], float] = time.time):
        self.config = config
        self.secret = config.secret or secrets.token_bytes(32)
        self.bus = EventBus()
        self.repo = Repository(config.db_path)
        self.rotator = TokenRotator(self.secret, config.token_period, clock)
        self.sessions = SessionService(self.repo, self.bus, clock)
        self.attendance = AttendanceService(self.repo, self.sessions, self.rotator, self.bus, clock,
                                            config.late_after_minutes)
        self.comments = CommentService(self.repo, self.sessions, self.bus, clock)
        self.polls = PollService(self.repo, self.sessions, self.bus, clock)
        self.reports = ReportService(self.repo, self.sessions)
        self.summary = SummaryService(LLMSummarizer(llm) if llm else None)
        self.reviews = ReviewService(self.repo, self.sessions, LLMReviewer(llm) if llm else None,
                                     clock=clock, bus=self.bus)
        self.llm_enabled = llm is not None
        # Guessing the 4-digit PIN or the 6-digit code must be hopeless; flooding the board, dull.
        self.login_limiter = RateLimiter(5, 60, clock)
        self.checkin_limiter = RateLimiter(10, 60, clock)
        self.comment_limiter = RateLimiter(5, 30, clock)

    def checkin_url(self, session_id: str) -> str:
        return f"{self.config.public_url}/?s={session_id}&t={self.rotator.current(session_id)}"
