"""Domain entities. Plain dataclasses with no I/O, so they are trivial to test."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict


@dataclass
class ClassSession:
    id: str
    title: str
    started_at: float
    ended_at: float | None = None

    @property
    def is_active(self) -> bool:
        return self.ended_at is None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["is_active"] = self.is_active
        return d


@dataclass
class AttendanceRecord:
    session_id: str
    student_id: str
    name: str
    device_id: str
    checked_in_at: float

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("device_id")  # never leaked to clients
        return d


@dataclass
class Comment:
    id: int
    session_id: str
    text: str
    author: str          # "Anonymous" when the student chose not to sign
    created_at: float
    upvotes: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Poll:
    id: int
    session_id: str
    question: str
    options: list[str]
    created_at: float
    is_open: bool = True
    votes: list[int] = field(default_factory=list)  # vote count per option

    @property
    def total_votes(self) -> int:
        return sum(self.votes)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["total_votes"] = self.total_votes
        return d


@dataclass
class Submission:
    id: int
    session_id: str
    student_id: str
    name: str
    text: str
    submitted_at: float

    def to_dict(self) -> dict:
        return asdict(self)


class DomainError(Exception):
    """A rule of the domain was broken. `code` is stable and shown to clients."""

    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
