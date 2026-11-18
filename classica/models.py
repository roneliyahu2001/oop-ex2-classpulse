"""Domain entities. Plain dataclasses with no I/O, so they are trivial to test."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict


@dataclass
class ClassSession:
    id: str
    title: str
    started_at: float
    ended_at: float | None = None
    homework_task: str = ""
    summary: str = ""
    summary_published: bool = False
    geo_mode: str = "off"           # "off", "flag" (mark far students) or "block" (reject them)
    geo_lat: float | None = None
    geo_lon: float | None = None
    geo_radius: int = 0             # metres
    headcount: int | None = None    # people the lecturer's class photo shows (counted in the browser)
    headcount_at: float | None = None

    @property
    def is_active(self) -> bool:
        return self.ended_at is None

    def to_dict(self, lecturer: bool = False) -> dict:
        d = asdict(self)
        d["is_active"] = self.is_active
        if not lecturer:
            d.pop("geo_lat")        # students only need to know that a check exists
            d.pop("geo_lon")
            d.pop("headcount")      # lecturer's own check on the class
            d.pop("headcount_at")
            if not self.summary_published:
                d["summary"] = ""   # drafts stay with the lecturer
        return d


@dataclass
class AttendanceRecord:
    session_id: str
    student_id: str
    name: str
    device_id: str
    checked_in_at: float
    status: str = "on_time"         # or "late"
    method: str = "qr"              # "qr", "code" (typed) or "manual" (added by the lecturer)
    ip: str = ""
    geo: str = ""                   # "" (no check), "ok", "far" or "none" (phone sent no location)
    distance_m: int | None = None   # distance from the classroom; coordinates are never stored

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("device_id")  # never leaked to clients
        d.pop("ip")
        return d


@dataclass
class Comment:
    id: int
    session_id: str
    text: str
    author: str          # "Anonymous" when the student chose not to sign
    created_at: float
    upvotes: int = 0
    answered: bool = False
    hidden: bool = False

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
    device_id: str = ""  # the phone that submitted; only it (or the lecturer) may replace or review

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("device_id")
        return d


class DomainError(Exception):
    """A rule of the domain was broken. `code` is stable and shown to clients."""

    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
