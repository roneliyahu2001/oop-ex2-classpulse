"""Rotating check-in tokens shown inside the lecturer's QR code.

A token is an HMAC of (session id, time window). It changes every `period`
seconds, so a photo of the QR sent to a friend at home expires quickly.
The previous window is also accepted to tolerate slow scans.
"""
from __future__ import annotations

import hashlib
import hmac
import time
from typing import Callable


class TokenRotator:
    def __init__(self, secret: bytes, period: int = 20, clock: Callable[[], float] = time.time):
        self._secret = secret
        self.period = period
        self._clock = clock

    def _window(self) -> int:
        return int(self._clock() // self.period)

    def _token_for(self, session_id: str, window: int) -> str:
        msg = f"{session_id}:{window}".encode()
        return hmac.new(self._secret, msg, hashlib.sha256).hexdigest()[:10]

    def current(self, session_id: str) -> str:
        return self._token_for(session_id, self._window())

    def seconds_left(self) -> int:
        return self.period - int(self._clock() % self.period)

    def is_valid(self, session_id: str, token: str) -> bool:
        w = self._window()
        return any(hmac.compare_digest(token, self._token_for(session_id, x)) for x in (w, w - 1))
