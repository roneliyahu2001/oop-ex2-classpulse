"""HTTP layer: a tiny router over the standard library's ThreadingHTTPServer.

Controllers only translate HTTP <-> service calls; all rules live in services.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import mimetypes
import queue
import re
import secrets
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .app import ClassicaApp
from .events import staff_channel
from .models import DomainError
from .ratelimit import RateLimiter

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
MAX_BODY = 2 * 1024 * 1024
DEVICE_COOKIE = "ca_dev"
LECTURER_COOKIE = "ca_lect"
LOOPBACK = ("127.0.0.1", "::1", "::ffff:127.0.0.1")
XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
CSP = "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:"

ROUTES: list[tuple[str, re.Pattern, str, bool]] = []  # (method, pattern, handler name, lecturer only)


def route(method: str, pattern: str, lecturer: bool = False):
    def deco(fn):
        ROUTES.append((method, re.compile("^" + pattern + "$"), fn.__name__, lecturer))
        return fn
    return deco


def _number(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _flag(value) -> bool | None:
    return value if isinstance(value, bool) else None


class Handler(BaseHTTPRequestHandler):
    app: ClassicaApp  # injected by make_server
    protocol_version = "HTTP/1.1"
    server_version = "Classica/2.0"
    quiet = False

    # ---- plumbing -------------------------------------------------------
    def log_message(self, fmt, *args):  # quieter console during the demo
        if not self.quiet and "/events" not in self.path and "/qr" not in self.path:
            super().log_message(fmt, *args)

    def _cookies(self) -> cookies.SimpleCookie:
        try:
            return cookies.SimpleCookie(self.headers.get("Cookie", ""))
        except cookies.CookieError:
            return cookies.SimpleCookie()

    def _lecturer_token(self) -> str:
        return hmac.new(self.app.secret, self.app.config.lecturer_pin.encode(), hashlib.sha256).hexdigest()

    def is_lecturer(self) -> bool:
        c = self._cookies().get(LECTURER_COOKIE)
        return bool(c) and hmac.compare_digest(c.value.encode(), self._lecturer_token().encode())

    def _device_cookie(self) -> str | None:
        c = self._cookies().get(DEVICE_COOKIE)
        return c.value if c and re.fullmatch(r"[0-9a-f]{32}", c.value) else None

    def device_id(self) -> str:
        """The phone's identity: a random cookie, created on first contact."""
        existing = self._device_cookie()
        if existing:
            return existing
        if not hasattr(self, "_new_device"):
            self._new_device = secrets.token_hex(16)
        return self._new_device

    def peer_ip(self) -> str:
        ip = self.client_address[0]
        forwarded = self.headers.get("X-Forwarded-For")
        if forwarded and ip in LOOPBACK:  # only a tunnel running on this laptop is trusted
            return forwarded.split(",")[0].strip()
        return ip

    def lan_ip(self) -> str:
        """Address for the "same phone twice?" hint. Empty when it says nothing (tunnel, this laptop)."""
        ip = self.client_address[0]
        return "" if ip in LOOPBACK else ip

    def limit(self, limiter: RateLimiter, key: str | None = None) -> None:
        # A phone is counted by its cookie; a client without one, by its address.
        key = key or self._device_cookie() or "ip:" + self.peer_ip()
        if not limiter.allow(key):
            raise DomainError("RATE_LIMITED", "Too many attempts - wait a moment and try again", 429)

    def lang(self, body: dict | None = None) -> str:
        chosen = (body or {}).get("lang") or self.query.get("lang")
        return "he" if chosen == "he" else "en"

    def body(self) -> dict:
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = -1
        if n < 0 or n > MAX_BODY:
            self.close_connection = True  # the unread body would corrupt the next request
            raise DomainError("TOO_LARGE", "Request too large", 413)
        if n == 0:
            return {}
        try:
            data = json.loads(self.rfile.read(n))
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise DomainError("BAD_JSON", "Body must be JSON")
        if not isinstance(data, dict):
            raise DomainError("BAD_JSON", "Body must be a JSON object")
        return data

    def send(self, status: int, payload: bytes, ctype: str, extra: dict | None = None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        cacheable = self.path.startswith("/static/vendor/")  # 20 MB of libraries and model: load once
        self.send_header("Cache-Control", "max-age=86400" if cacheable else "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if hasattr(self, "_new_device"):
            self.send_header("Set-Cookie", f"{DEVICE_COOKIE}={self._new_device}; Path=/; "
                                           "Max-Age=31536000; SameSite=Lax; HttpOnly")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(payload)

    def json(self, obj, status: int = 200, extra: dict | None = None):
        self.send(status, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8", extra)

    def download(self, payload: bytes, ctype: str, filename: str):
        self.send(200, payload, ctype, {"Content-Disposition": f'attachment; filename="{filename}"'})

    def dispatch(self, method: str):
        url = urlparse(self.path)
        self.query = {k: v[0] for k, v in parse_qs(url.query).items()}
        try:
            for m, pat, name, lecturer in ROUTES:
                match = pat.match(url.path)
                if m == method and match:
                    if lecturer and not self.is_lecturer():
                        raise DomainError("LECTURER_ONLY", "Lecturer login required", 401)
                    return getattr(self, name)(*match.groups())
            if method == "GET":
                return self.static(url.path)
            raise DomainError("NOT_FOUND", "Not found", 404)
        except DomainError as e:
            self.json({"error": e.code, "message": e.message}, e.status)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:  # last line of defence; never leak a stack trace
            self.log_error("internal error: %r", e)
            self.json({"error": "INTERNAL", "message": "Unexpected server error"}, 500)

    def do_GET(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")

    # ---- static files ---------------------------------------------------
    def static(self, path: str):
        pages = {"/": "student.html", "/lecturer": "lecturer.html"}
        rel = pages.get(path) or path.removeprefix("/static/")
        f = (STATIC_DIR / rel).resolve()
        if STATIC_DIR not in f.parents or not f.is_file():
            raise DomainError("NOT_FOUND", "Not found", 404)
        ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith("javascript"):
            ctype += "; charset=utf-8"
        extra = None
        if path in pages:
            self.device_id()  # every phone gets its identity cookie with the first page
            extra = {"Content-Security-Policy": CSP}
        self.send(200, f.read_bytes(), ctype, extra)

    # ---- auth -----------------------------------------------------------
    @route("POST", "/api/login")
    def login(self):
        self.limit(self.app.login_limiter, "ip:" + self.peer_ip())
        pin = str(self.body().get("pin", ""))
        if not hmac.compare_digest(pin.encode(), self.app.config.lecturer_pin.encode()):
            raise DomainError("BAD_PIN", "Wrong PIN", 401)
        self.app.login_limiter.reset("ip:" + self.peer_ip())
        self.json({"ok": True}, extra={"Set-Cookie": f"{LECTURER_COOKIE}={self._lecturer_token()}; "
                                                     "Path=/; SameSite=Lax; HttpOnly"})

    @route("GET", "/api/me")
    def me(self):
        self.json({"lecturer": self.is_lecturer(), "llm": self.app.llm_enabled})

    # ---- sessions -------------------------------------------------------
    @route("POST", "/api/sessions", lecturer=True)
    def start_session(self):
        self.json(self.app.sessions.start(str(self.body().get("title", ""))).to_dict(lecturer=True), 201)

    @route("GET", "/api/sessions", lecturer=True)
    def list_sessions(self):
        self.json([s.to_dict(lecturer=True) for s in self.app.sessions.list()])

    @route("GET", "/api/active")
    def active_session(self):
        """Lets a student who typed the address (no QR) find the class that is open now."""
        s = self.app.sessions.active()
        self.json({"session": s.to_dict() if s else None})

    @route("POST", r"/api/sessions/(\w+)/end", lecturer=True)
    def end_session(self, sid):
        self.json(self.app.sessions.end(sid).to_dict(lecturer=True))

    @route("POST", r"/api/sessions/(\w+)/homework-task", lecturer=True)
    def set_homework_task(self, sid):
        task = str(self.body().get("task", ""))
        self.json(self.app.sessions.set_homework_task(sid, task).to_dict(lecturer=True))

    @route("POST", r"/api/sessions/(\w+)/geofence", lecturer=True)
    def set_geofence(self, sid):
        b = self.body()
        s = self.app.sessions.set_geofence(sid, str(b.get("mode", "")), _number(b.get("lat")),
                                           _number(b.get("lon")), int(_number(b.get("radius")) or 150))
        self.json(s.to_dict(lecturer=True))

    @route("POST", r"/api/sessions/(\w+)/headcount", lecturer=True)
    def set_headcount(self, sid):
        raw = self.body().get("count")
        count = _number(raw)
        if raw is not None and (count is None or count != int(count)):
            raise DomainError("BAD_HEADCOUNT", "count must be a whole number")
        self.json(self.app.sessions.set_headcount(sid, None if raw is None else int(count)).to_dict(lecturer=True))

    @route("GET", r"/api/sessions/(\w+)/qr", lecturer=True)
    def qr(self, sid):
        self.app.sessions.require_active(sid)
        self.json({"url": self.app.checkin_url(sid), "code": self.app.rotator.current_code(sid),
                   "base": self.app.config.public_url, "expires_in": self.app.rotator.seconds_left(),
                   "period": self.app.rotator.period})

    @route("GET", r"/api/sessions/(\w+)")
    def session_public(self, sid):
        s = self.app.sessions.get(sid)
        poll = self.app.polls.open_poll(sid)
        self.json({"session": s.to_dict(), "poll": poll.to_dict() if poll else None})

    # ---- attendance -----------------------------------------------------
    @route("POST", "/api/checkin")
    def checkin(self):
        self.limit(self.app.checkin_limiter)
        b = self.body()
        lat, lon = _number(b.get("lat")), _number(b.get("lon"))
        location = (lat, lon, _number(b.get("accuracy")) or 0.0) if lat is not None and lon is not None else None
        rec = self.app.attendance.check_in(str(b.get("session_id", "")), str(b.get("token", "")),
                                           str(b.get("student_id", "")), str(b.get("name", "")),
                                           self.device_id(), self.lan_ip(), location)
        self.json(rec.to_dict(), 201)

    @route("GET", r"/api/sessions/(\w+)/attendance", lecturer=True)
    def attendance(self, sid):
        self.json(self.app.attendance.list_for_lecturer(sid))

    @route("POST", r"/api/sessions/(\w+)/attendance", lecturer=True)
    def add_attendance(self, sid):
        b = self.body()
        rec = self.app.attendance.add_manual(sid, str(b.get("student_id", "")), str(b.get("name", "")))
        self.json(rec.to_dict(), 201)

    @route("POST", r"/api/sessions/(\w+)/attendance/(\w+)/remove", lecturer=True)
    def remove_attendance(self, sid, student_id):
        self.app.attendance.remove(sid, student_id)
        self.json({"ok": True})

    @route("GET", r"/api/sessions/(\w+)/attendance\.csv", lecturer=True)
    def attendance_csv(self, sid):
        self.download(self.app.attendance.export_csv(sid, self.lang()), "text/csv; charset=utf-8",
                      f"attendance-{sid}.csv")

    @route("GET", r"/api/sessions/(\w+)/report\.xlsx", lecturer=True)
    def session_report(self, sid):
        self.download(self.app.reports.session_workbook(sid, self.lang()), XLSX_TYPE, f"class-{sid}.xlsx")

    @route("GET", "/api/course/attendance", lecturer=True)
    def course_attendance(self):
        self.json(self.app.reports.course_matrix())

    @route("GET", r"/api/course/attendance\.xlsx", lecturer=True)
    def course_report(self):
        self.download(self.app.reports.course_workbook(self.lang()), XLSX_TYPE, "attendance-all-classes.xlsx")

    # ---- comments -------------------------------------------------------
    @route("GET", r"/api/sessions/(\w+)/comments")
    def comments(self, sid):
        self.json([c.to_dict() for c in self.app.comments.list(sid, include_hidden=self.is_lecturer())])

    @route("POST", r"/api/sessions/(\w+)/comments")
    def post_comment(self, sid):
        self.limit(self.app.comment_limiter)
        b = self.body()
        self.json(self.app.comments.post(sid, str(b.get("text", "")), str(b.get("author", ""))).to_dict(), 201)

    @route("POST", r"/api/comments/(\d+)/upvote")
    def upvote(self, cid):
        self.json(self.app.comments.upvote(int(cid), self.device_id()).to_dict())

    @route("POST", r"/api/comments/(\d+)/moderate", lecturer=True)
    def moderate(self, cid):
        b = self.body()
        self.json(self.app.comments.moderate(int(cid), _flag(b.get("answered")), _flag(b.get("hidden"))).to_dict())

    # ---- polls ----------------------------------------------------------
    @route("GET", r"/api/sessions/(\w+)/polls", lecturer=True)
    def polls(self, sid):
        self.json([p.to_dict() for p in self.app.polls.list(sid)])

    @route("POST", r"/api/sessions/(\w+)/polls", lecturer=True)
    def create_poll(self, sid):
        b = self.body()
        opts = b.get("options") or []
        if not isinstance(opts, list):
            raise DomainError("BAD_OPTIONS", "options must be a list")
        self.json(self.app.polls.create(sid, str(b.get("question", "")), [str(o) for o in opts]).to_dict(), 201)

    @route("POST", r"/api/polls/(\d+)/vote")
    def vote(self, pid):
        option = _number(self.body().get("option"))
        if option is None or option != int(option):
            raise DomainError("BAD_OPTION", "option must be a whole number")
        self.json(self.app.polls.vote(int(pid), int(option), self.device_id()).to_dict())

    @route("POST", r"/api/polls/(\d+)/close", lecturer=True)
    def close_poll(self, pid):
        self.json(self.app.polls.close(int(pid)).to_dict())

    # ---- AI features ----------------------------------------------------
    @route("POST", "/api/summary", lecturer=True)
    def summary(self):
        b = self.body()
        result = self.app.summary.summarize(str(b.get("transcript", "")), self.lang(b))
        if b.get("session_id"):  # keep it as a draft of that class; sharing is a separate step
            self.app.sessions.save_summary(str(b["session_id"]), result["summary"], published=False)
        self.json(result)

    @route("POST", r"/api/sessions/(\w+)/summary", lecturer=True)
    def save_summary(self, sid):
        b = self.body()
        s = self.app.sessions.save_summary(sid, str(b.get("summary", "")), b.get("published") is True)
        self.json(s.to_dict(lecturer=True))

    @route("POST", r"/api/sessions/(\w+)/homework")
    def submit_homework(self, sid):
        b = self.body()
        s = self.app.reviews.submit(sid, str(b.get("student_id", "")), str(b.get("name", "")),
                                    str(b.get("text", "")), self.device_id())
        self.json({"id": s.id, "submitted_at": s.submitted_at}, 201)

    @route("POST", r"/api/sessions/(\w+)/homework/(\w+)/review")
    def review(self, sid, student_id):
        b = self.body()
        self.json(self.app.reviews.review_student(sid, student_id, str(b.get("task", "")),
                                                  lecturer=self.is_lecturer(), device_id=self.device_id(),
                                                  lang=self.lang(b)))

    @route("POST", r"/api/sessions/(\w+)/homework/(\w+)/delete", lecturer=True)
    def delete_homework(self, sid, student_id):
        self.app.reviews.delete(sid, student_id)
        self.json({"ok": True})

    @route("GET", r"/api/sessions/(\w+)/homework", lecturer=True)
    def homework_overview(self, sid):
        self.json(self.app.reviews.class_overview(sid))

    # ---- live updates (Server-Sent Events) -----------------------------
    @route("GET", r"/api/sessions/(\w+)/events")
    def events(self, sid):
        self.app.sessions.get(sid)
        channels = [sid, staff_channel(sid)] if self.is_lecturer() else [sid]
        q = self.app.bus.subscribe(*channels)
        self.close_connection = True
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Accel-Buffering", "no")  # asks proxies and tunnels not to buffer
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(b"event: hello\ndata: {}\n\n")
            self.wfile.flush()
            while True:
                try:
                    ev, data = q.get(timeout=15)
                    msg = f"event: {ev}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
                except queue.Empty:
                    msg = ": ping\n\n"  # keeps proxies and phones from dropping the stream
                self.wfile.write(msg.encode())
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            self.app.bus.unsubscribe(q)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 128  # a whole class scans within the same few seconds


def make_server(app: ClassicaApp, host: str = "0.0.0.0", port: int = 8000,
                quiet: bool = False) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {"app": app, "quiet": quiet})
    return Server((host, port), handler)
