#!/usr/bin/env python3
"""Simulates a class of student phones against a running Classica server.

Use it to rehearse the demo alone (the dashboard fills up as if a real class
scanned the QR), and as a load test that prints response times.

    python3 run.py --pin 1234                              # terminal 1
    python3 tools/simulate_class.py --pin 1234 --students 30   # terminal 2
"""
from __future__ import annotations

import argparse
import http.client
import http.cookiejar
import json
import random
import socket
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

FIRST = ["נועה", "דניאל", "יעל", "איתי", "מאיה", "עומר", "שירה", "יונתן", "תמר", "אורי",
         "Dana", "Yossi", "Maya", "Amit", "Lior", "Noa", "Omer", "Tal", "Roni", "Gal"]
LAST = ["כהן", "לוי", "מזרחי", "פרץ", "ביטון", "אברהם", "פרידמן", "דהן", "Shapiro", "Katz", "Golan", "Peretz"]
QUESTIONS = ["אפשר דוגמה נוספת?", "Can you repeat the last slide?", "מה ההבדל בין ירושה להרכבה?",
             "Will this be in the exam?", "אפשר להאט קצת?", "Where can we find the slides?"]
ANSWERS = [
    "The strategy pattern defines a family of algorithms behind one interface so the algorithm can be "
    "swapped at runtime. The observer pattern lets objects subscribe to a subject and get notified on changes.",
    "Strategy is when you have an interface and several classes that implement it, and you choose one when the "
    "program runs, like sorting with quicksort or mergesort. Observer is publish and subscribe.",
    "Design patterns are reusable solutions. Strategy swaps behaviour using composition instead of inheritance, "
    "and observer decouples the publisher of an event from all of its listeners.",
]


class Client:
    """One browser: its own cookie jar, so the server sees it as one device."""

    def __init__(self, base: str):
        self.base = base.rstrip("/")
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def call(self, method: str, path: str, body: dict | None = None):
        """Returns (status, parsed JSON or raw bytes). Never raises on HTTP errors."""
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with self.opener.open(req, timeout=20) as r:
                raw = r.read()
                return r.status, json.loads(raw) if "json" in r.headers.get("Content-Type", "") else raw
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw)
            except ValueError:
                return e.code, raw


class Phone(Client):
    def __init__(self, base: str, student_id: str, name: str):
        super().__init__(base)
        self.student_id, self.name = student_id, name
        self.checked_in = False
        self.poll_seen_at: float | None = None
        self._conn = None

    def check_in(self, session_id: str, token: str) -> tuple[bool, float, str]:
        self.call("GET", "/")  # loading the page gives the phone its identity cookie
        t0 = time.perf_counter()
        status, data = self.call("POST", "/api/checkin", {"session_id": session_id, "token": token,
                                                         "student_id": self.student_id, "name": self.name})
        self.checked_in = status == 201
        return self.checked_in, time.perf_counter() - t0, "" if self.checked_in else str(data)

    def listen(self, session_id: str) -> None:
        """Keeps the live-update stream open, like a phone showing the class page."""
        u = urlparse(self.base)
        connection = http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection
        self._conn = connection(u.netloc, timeout=60)
        self._conn.request("GET", f"/api/sessions/{session_id}/events")
        stream = self._conn.getresponse()

        def pump():
            try:
                for line in stream:
                    if line.startswith(b"event: poll") and self.poll_seen_at is None:
                        self.poll_seen_at = time.perf_counter()
            except (OSError, ValueError, http.client.HTTPException):
                pass
            finally:
                self._conn.close()
        threading.Thread(target=pump, daemon=True).start()

    def hang_up(self) -> None:
        # Shutting the socket down wakes the reader thread; closing from here would wait for it.
        if self._conn is not None and self._conn.sock is not None:
            try:
                self._conn.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


def _ms(seconds: list[float]) -> str:
    if not seconds:
        return "-"
    s = sorted(seconds)
    p95 = s[min(len(s) - 1, int(len(s) * 0.95))]
    return f"median {statistics.median(s) * 1000:.0f} ms, 95% under {p95 * 1000:.0f} ms, slowest {s[-1] * 1000:.0f} ms"


def simulate(url: str, pin: str, students: int = 30, session_id: str | None = None,
             homework: int = 3, seed: int | None = None, out=print) -> dict:
    """Runs the whole scenario and returns the measurements."""
    rnd = random.Random(seed)
    lecturer = Client(url)
    status, _ = lecturer.call("POST", "/api/login", {"pin": pin})
    if status != 200:
        raise SystemExit(f"Lecturer login failed (HTTP {status}). Is the PIN right?")

    if not session_id:
        active = lecturer.call("GET", "/api/active")[1]["session"]
        session_id = active["id"] if active else lecturer.call(
            "POST", "/api/sessions", {"title": "Simulated class"})[1]["id"]
    out(f"Class {session_id}: {students} simulated phones")

    base_id = rnd.randrange(200_000_000, 900_000_000)
    phones = [Phone(url, str(base_id + i), f"{rnd.choice(FIRST)} {rnd.choice(LAST)}")
              for i in range(students)]

    def join(phone: Phone):
        token = lecturer.call("GET", f"/api/sessions/{session_id}/qr")[1]["url"].split("&t=")[1]
        return phone.check_in(session_id, token)

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=min(32, students)) as pool:
        results = list(pool.map(join, phones))
    checkin_wall = time.perf_counter() - t0
    present = [p for p in phones if p.checked_in]
    failures = [msg for ok, _, msg in results if not ok]
    out(f"Check-in : {len(present)}/{students} succeeded in {checkin_wall:.1f} s  ({_ms([t for ok, t, _ in results if ok])})")
    for msg in failures[:3]:
        out(f"           failed: {msg}")

    for p in present:
        p.listen(session_id)
    time.sleep(0.5)  # let every stream connect

    t_poll = time.perf_counter()
    poll = lecturer.call("POST", f"/api/sessions/{session_id}/polls",
                         {"question": "Did you understand? (simulated)", "options": ["Yes", "Mostly", "Not yet"]})[1]
    deadline = time.time() + 10
    while time.time() < deadline and any(p.poll_seen_at is None for p in present):
        time.sleep(0.02)
    seen = [p.poll_seen_at - t_poll for p in present if p.poll_seen_at is not None]
    out(f"Live poll: reached {len(seen)}/{len(present)} phones  ({_ms(seen)})")

    def vote(phone: Phone):
        t = time.perf_counter()
        status, _ = phone.call("POST", f"/api/polls/{poll['id']}/vote",
                               {"option": rnd.choices([0, 1, 2], weights=[5, 3, 2])[0]})
        return status == 200, time.perf_counter() - t

    with ThreadPoolExecutor(max_workers=min(32, max(1, len(present)))) as pool:
        votes = list(pool.map(vote, present))
    out(f"Votes    : {sum(ok for ok, _ in votes)}/{len(present)} counted  ({_ms([t for ok, t in votes if ok])})")

    commenters = present[: max(1, len(present) // 6)] if present else []
    posted = []
    for p in commenters:
        status, c = p.call("POST", f"/api/sessions/{session_id}/comments", {"text": rnd.choice(QUESTIONS)})
        if status == 201:
            posted.append(c["id"])
    for p in present[: len(present) // 3]:
        if posted:
            p.call("POST", f"/api/comments/{rnd.choice(posted)}/upvote")
    out(f"Comments : {len(posted)} posted")

    submitted = 0
    for i, p in enumerate(present[:homework]):
        status, _ = p.call("POST", f"/api/sessions/{session_id}/homework",
                           {"student_id": p.student_id, "name": p.name, "text": ANSWERS[i % len(ANSWERS)]})
        submitted += status == 201
    out(f"Homework : {submitted} submitted")

    for p in phones:
        p.hang_up()
    return {"session_id": session_id, "students": students, "checked_in": len(present),
            "checkin_seconds": checkin_wall, "poll_reached": len(seen),
            "poll_latency_max": max(seen) if seen else None,
            "votes": sum(ok for ok, _ in votes), "comments": len(posted), "homework": submitted}


def main() -> None:
    p = argparse.ArgumentParser(description="Simulate student phones against a running Classica server")
    p.add_argument("--url", default="http://localhost:8000")
    p.add_argument("--pin", required=True, help="the lecturer PIN printed by run.py")
    p.add_argument("--students", type=int, default=30)
    p.add_argument("--session", help="class id; default: the class that is open now, or a new one")
    p.add_argument("--homework", type=int, default=3, help="how many phones submit homework")
    a = p.parse_args()
    r = simulate(a.url, a.pin, a.students, a.session, a.homework)
    ok = r["checked_in"] == r["students"] and r["poll_reached"] == r["checked_in"] == r["votes"]
    print("RESULT   :", "all good" if ok else "some steps failed (see above)")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
