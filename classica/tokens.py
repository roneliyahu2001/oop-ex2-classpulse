"""Rotating check-in secrets shown on the lecturer's screen.

Each time window has two forms of the same secret: a token embedded in the QR
link, and a 6-digit code a student can type when the camera fails. Both are an
HMAC of (session id, time window) and change every `period` seconds, so a
photo of the screen sent to a friend at home expires quickly. The previous
window is also accepted to tolerate slow scans.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import time
from typing import Callable


class TokenRotator:
    def __init__(self, secret: bytes, period: int = 20, clock: Callable[[], float] = time.time):
        self._secret = secret
        self.period = period
        self._clock = clock

    def _window(self) -> int:
        return int(self._clock() // self.period)

    def _digest(self, session_id: str, window: int) -> str:
        msg = f"{session_id}:{window}".encode()
        return hmac.new(self._secret, msg, hashlib.sha256).hexdigest()

    def _token_for(self, session_id: str, window: int) -> str:
        return self._digest(session_id, window)[:10]

    def _code_for(self, session_id: str, window: int) -> str:
        return f"{int(self._digest(session_id, window)[10:20], 16) % 1_000_000:06d}"

    def current(self, session_id: str) -> str:
        return self._token_for(session_id, self._window())

    def current_code(self, session_id: str) -> str:
        return self._code_for(session_id, self._window())

    def seconds_left(self) -> int:
        return self.period - int(self._clock() % self.period)

    def match(self, session_id: str, given: str) -> str | None:
        """Returns how the student proved presence: "qr", "code", or None if invalid."""
        given = re.sub(r"[\s-]", "", given).encode()
        w = self._window()
        for window in (w, w - 1):
            if hmac.compare_digest(given, self._token_for(session_id, window).encode()):
                return "qr"
            if hmac.compare_digest(given, self._code_for(session_id, window).encode()):
                return "code"
        return None

    def is_valid(self, session_id: str, given: str) -> bool:
        return self.match(session_id, given) is not None
