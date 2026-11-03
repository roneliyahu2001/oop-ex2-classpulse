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

from .app import ClassPulseApp
from .models import DomainError

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
MAX_BODY = 2 * 1024 * 1024
DEVICE_COOKIE = "cp_dev"
LECTURER_COOKIE = "cp_lect"

ROUTES: list[tuple[str, re.Pattern, str, bool]] = []  # (method, pattern, handler name, lecturer only)


def route(method: str, pattern: str, lecturer: bool = False):
    def deco(fn):
        ROUTES.append((method, re.compile("^" + pattern + "$"), fn.__name__, lecturer))
        return fn
    return deco


class Handler(BaseHTTPRequestHandler):
    app: ClassPulseApp  # injected by make_server
    protocol_version = "HTTP/1.1"
    server_version = "ClassPulse/1.0"
    quiet = False

    # ---- plumbing -------------------------------------------------------
    def log_message(self, fmt, *args):  # quieter console during the demo
        if not self.quiet and "/events" not in self.path and "/qr" not in self.path:
            super().log_message(fmt, *args)

    def _cookies(self) -> cookies.SimpleCookie:
        return cookies.SimpleCookie(self.headers.get("Cookie", ""))

    def _lecturer_token(self) -> str:
        return hmac.new(self.app.secret, self.app.config.lecturer_pin.encode(), hashlib.sha256).hexdigest()

    def is_lecturer(self) -> bool:
        c = self._cookies().get(LECTURER_COOKIE)
        return bool(c) and hmac.compare_digest(c.value, self._lecturer_token())

    def device_id(self) -> str:
        c = self._cookies().get(DEVICE_COOKIE)
        if c and re.fullmatch(r"[0-9a-f]{32}", c.value):
            return c.value
        if not hasattr(self, "_new_device"):
            self._new_device = secrets.token_hex(16)
        return self._new_device

    def body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            raise DomainError("TOO_LARGE", "Request too large", 413)
        if n == 0:
            return {}
        try:
            data = json.loads(self.rfile.read(n))
        except json.JSONDecodeError:
            raise DomainError("BAD_JSON", "Body must be JSON")
        if not isinstance(data, dict):
            raise DomainError("BAD_JSON", "Body must be a JSON object")
        return data

    def send(self, status: int, payload: bytes, ctype: str, extra: dict | None = None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        if hasattr(self, "_new_device"):
            self.send_header("Set-Cookie", f"{DEVICE_COOKIE}={self._new_device}; Path=/; "
                                           "Max-Age=31536000; SameSite=Lax; HttpOnly")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(payload)

    def json(self, obj, status: int = 200, extra: dict | None = None):
        self.send(status, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8", extra)

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
        self.send(200, f.read_bytes(), ctype)

    # ---- auth -----------------------------------------------------------
    @route("POST", "/api/login")
    def login(self):
        pin = str(self.body().get("pin", ""))
        if not hmac.compare_digest(pin, self.app.config.lecturer_pin):
            raise DomainError("BAD_PIN", "Wrong PIN", 401)
        self.json({"ok": True}, extra={"Set-Cookie": f"{LECTURER_COOKIE}={self._lecturer_token()}; "
                                                     "Path=/; SameSite=Lax; HttpOnly"})

    @route("GET", "/api/me")
    def me(self):
        self.json({"lecturer": self.is_lecturer(), "llm": self.app.llm_enabled})

    # ---- sessions -------------------------------------------------------
    @route("POST", "/api/sessions", lecturer=True)
    def start_session(self):
        self.json(self.app.sessions.start(str(self.body().get("title", ""))).to_dict(), 201)

    @route("GET", "/api/sessions", lecturer=True)
    def list_sessions(self):
        self.json([s.to_dict() for s in self.app.sessions.list()])

    @route("POST", r"/api/sessions/(\w+)/end", lecturer=True)
    def end_session(self, sid):
        self.json(self.app.sessions.end(sid).to_dict())

    @route("GET", r"/api/sessions/(\w+)/qr", lecturer=True)
    def qr(self, sid):
        self.app.sessions.require_active(sid)
        self.json({"url": self.app.checkin_url(sid), "expires_in": self.app.rotator.seconds_left(),
                   "period": self.app.rotator.period})

    @route("GET", r"/api/sessions/(\w+)")
    def session_public(self, sid):
        s = self.app.sessions.get(sid)
        poll = self.app.polls.open_poll(sid)
        self.json({"session": s.to_dict(), "poll": poll.to_dict() if poll else None})

    # ---- attendance -----------------------------------------------------
    @route("POST", "/api/checkin")
    def checkin(self):
        b = self.body()
        rec = self.app.attendance.check_in(str(b.get("session_id", "")), str(b.get("token", "")),
                                           str(b.get("student_id", "")), str(b.get("name", "")),
                                           self.device_id())
        self.json(rec.to_dict(), 201)

    @route("GET", r"/api/sessions/(\w+)/attendance", lecturer=True)
    def attendance(self, sid):
        self.json([r.to_dict() for r in self.app.attendance.list(sid)])

    @route("GET", r"/api/sessions/(\w+)/attendance\.csv", lecturer=True)
    def attendance_csv(self, sid):
        self.send(200, self.app.attendance.export_csv(sid), "text/csv; charset=utf-8",
                  {"Content-Disposition": f'attachment; filename="attendance-{sid}.csv"'})

    # ---- comments -------------------------------------------------------
    @route("GET", r"/api/sessions/(\w+)/comments")
    def comments(self, sid):
        self.json([c.to_dict() for c in self.app.comments.list(sid)])

    @route("POST", r"/api/sessions/(\w+)/comments")
    def post_comment(self, sid):
        b = self.body()
        self.json(self.app.comments.post(sid, str(b.get("text", "")), str(b.get("author", ""))).to_dict(), 201)

    @route("POST", r"/api/comments/(\d+)/upvote")
    def upvote(self, cid):
        self.json(self.app.comments.upvote(int(cid), self.device_id()).to_dict())

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
        try:
            option = int(self.body().get("option"))
        except (TypeError, ValueError):
            raise DomainError("BAD_OPTION", "option must be a number")
        self.json(self.app.polls.vote(int(pid), option, self.device_id()).to_dict())

    @route("POST", r"/api/polls/(\d+)/close", lecturer=True)
    def close_poll(self, pid):
        self.json(self.app.polls.close(int(pid)).to_dict())

    # ---- AI features ----------------------------------------------------
    @route("POST", "/api/summary", lecturer=True)
    def summary(self):
        self.json(self.app.summary.summarize(str(self.body().get("transcript", ""))))

    @route("POST", r"/api/sessions/(\w+)/homework")
    def submit_homework(self, sid):
        b = self.body()
        s = self.app.reviews.submit(sid, str(b.get("student_id", "")), str(b.get("name", "")),
                                    str(b.get("text", "")))
        self.json({"id": s.id, "submitted_at": s.submitted_at}, 201)

    @route("POST", r"/api/sessions/(\w+)/homework/(\w+)/review")
    def review(self, sid, student_id):
        b = self.body()
        self.json(self.app.reviews.review_student(sid, student_id, str(b.get("task", "")),
                                                  lecturer=self.is_lecturer()))

    @route("GET", r"/api/sessions/(\w+)/homework", lecturer=True)
    def homework_overview(self, sid):
        self.json(self.app.reviews.class_overview(sid))

    # ---- live updates (Server-Sent Events) -----------------------------
    @route("GET", r"/api/sessions/(\w+)/events")
    def events(self, sid):
        self.app.sessions.get(sid)
        q = self.app.bus.subscribe(sid)
        self.close_connection = True
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
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
            self.app.bus.unsubscribe(sid, q)


def make_server(app: ClassPulseApp, host: str = "0.0.0.0", port: int = 8000,
                quiet: bool = False) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {"app": app, "quiet": quiet})
    srv = ThreadingHTTPServer((host, port), handler)
    srv.daemon_threads = True
    return srv
