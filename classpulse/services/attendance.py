from __future__ import annotations

import csv
import io
import re
import time
from datetime import datetime
from typing import Callable

from ..events import EventBus
from ..models import AttendanceRecord, DomainError
from ..repository import Repository
from ..tokens import TokenRotator
from .sessions import SessionService

STUDENT_ID_RE = re.compile(r"^\d{5,10}$")


class AttendanceService:
    """Feature 1 (main): QR check-in and the lecturer's spreadsheet."""

    def __init__(self, repo: Repository, sessions: SessionService, rotator: TokenRotator,
                 bus: EventBus, clock: Callable[[], float] = time.time):
        self._repo = repo
        self._sessions = sessions
        self._rotator = rotator
        self._bus = bus
        self._clock = clock

    def check_in(self, session_id: str, token: str, student_id: str, name: str,
                 device_id: str) -> AttendanceRecord:
        self._sessions.require_active(session_id)
        student_id, name = student_id.strip(), " ".join(name.split())
        if not STUDENT_ID_RE.match(student_id):
            raise DomainError("BAD_STUDENT_ID", "Student ID must be 5-10 digits")
        if not name:
            raise DomainError("NAME_REQUIRED", "Name is required")
        if not self._rotator.is_valid(session_id, token):
            raise DomainError("TOKEN_EXPIRED", "QR code expired - scan the screen again", 403)

        existing = self._repo.find_attendance(session_id, student_id=student_id)
        if existing:
            if existing.device_id == device_id:
                return existing  # idempotent: re-scanning is harmless
            raise DomainError("ALREADY_CHECKED_IN", "This student ID already checked in", 409)
        if self._repo.find_attendance(session_id, device_id=device_id):
            raise DomainError("DEVICE_USED", "This phone already checked in another student", 409)

        rec = AttendanceRecord(session_id, student_id, name[:80], device_id, self._clock())
        self._repo.add_attendance(rec)
        self._bus.publish(session_id, "attendance", rec.to_dict())
        return rec

    def list(self, session_id: str) -> list[AttendanceRecord]:
        self._sessions.get(session_id)
        return self._repo.list_attendance(session_id)

    def export_csv(self, session_id: str) -> bytes:
        """UTF-8 with BOM so Excel shows Hebrew names correctly."""
        session = self._sessions.get(session_id)
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["#", "Student ID", "Name", "Check-in time", "Session", "Date"])
        date = datetime.fromtimestamp(session.started_at).strftime("%Y-%m-%d")
        for i, r in enumerate(self._repo.list_attendance(session_id), 1):
            t = datetime.fromtimestamp(r.checked_in_at).strftime("%H:%M:%S")
            w.writerow([i, r.student_id, r.name, t, session.title, date])
        return ("﻿" + out.getvalue()).encode("utf-8")
