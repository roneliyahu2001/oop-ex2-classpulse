from __future__ import annotations

import csv
import io
import re
import time
from collections import Counter
from datetime import datetime
from typing import Callable

from ..events import EventBus, staff_channel
from ..geo import GeoFence, valid_coordinates
from ..i18n import tr
from ..models import AttendanceRecord, ClassSession, DomainError
from ..repository import Repository
from ..tokens import TokenRotator
from .sessions import SessionService

STUDENT_ID_RE = re.compile(r"^\d{5,10}$")
Location = tuple[float, float, float]  # latitude, longitude, accuracy in metres


def safe_cell(value) -> str:
    """Stops a name such as "=HYPERLINK(...)" from running as a formula in Excel."""
    s = str(value)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


class AttendanceService:
    """Feature 1 (main): check-in by QR or typed code, and the lecturer's spreadsheet."""

    def __init__(self, repo: Repository, sessions: SessionService, rotator: TokenRotator,
                 bus: EventBus, clock: Callable[[], float] = time.time, late_after_minutes: int = 15):
        self._repo = repo
        self._sessions = sessions
        self._rotator = rotator
        self._bus = bus
        self._clock = clock
        self._late_after = late_after_minutes * 60

    @staticmethod
    def _clean(student_id: str, name: str) -> tuple[str, str]:
        student_id, name = student_id.strip(), " ".join(name.split())
        if not STUDENT_ID_RE.match(student_id):
            raise DomainError("BAD_STUDENT_ID", "Student ID must be 5-10 digits")
        if not name:
            raise DomainError("NAME_REQUIRED", "Name is required")
        return student_id, name[:80]

    def _locate(self, session: ClassSession, location: Location | None) -> tuple[str, int | None]:
        """Applies the session's location check. Returns (geo status, distance in metres)."""
        if session.geo_mode == "off":
            return "", None
        blocking = session.geo_mode == "block"
        if location is None or not valid_coordinates(location[0], location[1]):
            if blocking:
                raise DomainError("LOCATION_REQUIRED", "Location is needed to check in to this class", 403)
            return "none", None
        lat, lon, accuracy = location
        fence = GeoFence(session.geo_lat, session.geo_lon, session.geo_radius)
        distance = round(fence.distance_to(lat, lon))
        if fence.contains(lat, lon, accuracy):
            return "ok", distance
        if blocking:
            raise DomainError("TOO_FAR", f"You seem to be about {distance} m from the classroom", 403)
        return "far", distance

    def check_in(self, session_id: str, token: str, student_id: str, name: str, device_id: str,
                 ip: str = "", location: Location | None = None) -> AttendanceRecord:
        session = self._sessions.require_active(session_id)
        student_id, name = self._clean(student_id, name)
        method = self._rotator.match(session_id, token)
        if method is None:
            raise DomainError("TOKEN_EXPIRED", "The code expired - scan the screen again", 403)

        existing = self._repo.find_attendance(session_id, student_id=student_id)
        if existing:
            if existing.device_id == device_id:
                return existing  # idempotent: re-scanning is harmless
            raise DomainError("ALREADY_CHECKED_IN", "This student ID already checked in", 409)
        if self._repo.find_attendance(session_id, device_id=device_id):
            raise DomainError("DEVICE_USED", "This phone already checked in another student", 409)

        geo, distance = self._locate(session, location)
        now = self._clock()
        status = "late" if now - session.started_at > self._late_after else "on_time"
        rec = AttendanceRecord(session_id, student_id, name, device_id, now, status, method, ip,
                               geo, distance)
        if not self._repo.add_attendance(rec):  # lost a race with a parallel request
            raise DomainError("ALREADY_CHECKED_IN", "This student ID already checked in", 409)
        self._notify(session_id)
        return rec

    def add_manual(self, session_id: str, student_id: str, name: str) -> AttendanceRecord:
        """The lecturer adds a student whose phone is dead. Works on ended sessions too."""
        self._sessions.get(session_id)
        student_id, name = self._clean(student_id, name)
        rec = AttendanceRecord(session_id, student_id, name, f"manual:{student_id}", self._clock(),
                               "on_time", "manual")
        if not self._repo.add_attendance(rec):
            raise DomainError("ALREADY_CHECKED_IN", "This student ID already checked in", 409)
        self._notify(session_id)
        return rec

    def remove(self, session_id: str, student_id: str) -> None:
        if not self._repo.delete_attendance(session_id, student_id):
            raise DomainError("NOT_CHECKED_IN", "This student is not on the list", 404)
        self._notify(session_id)

    def _notify(self, session_id: str) -> None:
        # Names and IDs never travel on the public channel; the dashboard re-reads the list.
        count = len(self._repo.list_attendance(session_id))
        self._bus.publish(staff_channel(session_id), "attendance", {"count": count})

    def list(self, session_id: str) -> list[AttendanceRecord]:
        self._sessions.get(session_id)
        return self._repo.list_attendance(session_id)

    def list_for_lecturer(self, session_id: str) -> list[dict]:
        """Adds a hint when two check-ins came from one network address (one phone, two students?)."""
        records = self.list(session_id)
        per_ip = Counter(r.ip for r in records if r.ip)
        return [{**r.to_dict(), "shared_ip": per_ip[r.ip] > 1} for r in records]

    def export_csv(self, session_id: str, lang: str = "en") -> bytes:
        """UTF-8 with BOM so Excel shows Hebrew names correctly."""
        session = self._sessions.get(session_id)
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow([tr(lang, k) for k in ("num", "student_id", "name", "time", "status", "method",
                                          "location", "session", "date")])
        date = datetime.fromtimestamp(session.started_at).strftime("%Y-%m-%d")
        for i, r in enumerate(self._repo.list_attendance(session_id), 1):
            t = datetime.fromtimestamp(r.checked_in_at).strftime("%H:%M:%S")
            w.writerow([i, r.student_id, safe_cell(r.name), t, tr(lang, r.status), tr(lang, r.method),
                        tr(lang, "geo_" + r.geo, m=r.distance_m), safe_cell(session.title), date])
        return ("﻿" + out.getvalue()).encode("utf-8")
