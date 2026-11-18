"""SQLite persistence. The only module that knows SQL."""
from __future__ import annotations

import json
import sqlite3
import threading

from .models import AttendanceRecord, ClassSession, Comment, Poll, Submission

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY, title TEXT NOT NULL,
    started_at REAL NOT NULL, ended_at REAL
);
CREATE TABLE IF NOT EXISTS attendance (
    session_id TEXT NOT NULL, student_id TEXT NOT NULL, name TEXT NOT NULL,
    device_id TEXT NOT NULL, checked_in_at REAL NOT NULL,
    PRIMARY KEY (session_id, student_id)
);
CREATE TABLE IF NOT EXISTS comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
    text TEXT NOT NULL, author TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS comment_upvotes (
    comment_id INTEGER NOT NULL, device_id TEXT NOT NULL,
    PRIMARY KEY (comment_id, device_id)
);
CREATE TABLE IF NOT EXISTS polls (
    id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
    question TEXT NOT NULL, options TEXT NOT NULL,
    created_at REAL NOT NULL, is_open INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS poll_votes (
    poll_id INTEGER NOT NULL, device_id TEXT NOT NULL, option_index INTEGER NOT NULL,
    PRIMARY KEY (poll_id, device_id)
);
CREATE TABLE IF NOT EXISTS submissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
    student_id TEXT NOT NULL, name TEXT NOT NULL, text TEXT NOT NULL,
    submitted_at REAL NOT NULL, UNIQUE (session_id, student_id)
);
"""

# Columns added after the first version. Applied to old database files on start,
# so a classica.db from an earlier lecture keeps working.
MIGRATIONS = [
    ("sessions", "homework_task", "TEXT NOT NULL DEFAULT ''"),
    ("sessions", "summary", "TEXT NOT NULL DEFAULT ''"),
    ("sessions", "summary_published", "INTEGER NOT NULL DEFAULT 0"),
    ("sessions", "geo_mode", "TEXT NOT NULL DEFAULT 'off'"),
    ("sessions", "geo_lat", "REAL"),
    ("sessions", "geo_lon", "REAL"),
    ("sessions", "geo_radius", "INTEGER NOT NULL DEFAULT 0"),
    ("sessions", "headcount", "INTEGER"),
    ("sessions", "headcount_at", "REAL"),
    ("attendance", "status", "TEXT NOT NULL DEFAULT 'on_time'"),
    ("attendance", "method", "TEXT NOT NULL DEFAULT 'qr'"),
    ("attendance", "ip", "TEXT NOT NULL DEFAULT ''"),
    ("attendance", "geo", "TEXT NOT NULL DEFAULT ''"),
    ("attendance", "distance_m", "INTEGER"),
    ("comments", "answered", "INTEGER NOT NULL DEFAULT 0"),
    ("comments", "hidden", "INTEGER NOT NULL DEFAULT 0"),
    ("submissions", "device_id", "TEXT NOT NULL DEFAULT ''"),
]

_COMMENT_SELECT = ("SELECT c.*, (SELECT COUNT(*) FROM comment_upvotes u WHERE u.comment_id=c.id) "
                   "AS upvotes FROM comments c ")


def _session(r: sqlite3.Row) -> ClassSession:
    return ClassSession(r["id"], r["title"], r["started_at"], r["ended_at"], r["homework_task"],
                        r["summary"], bool(r["summary_published"]), r["geo_mode"],
                        r["geo_lat"], r["geo_lon"], r["geo_radius"], r["headcount"], r["headcount_at"])


def _attendance(r: sqlite3.Row) -> AttendanceRecord:
    return AttendanceRecord(r["session_id"], r["student_id"], r["name"], r["device_id"],
                            r["checked_in_at"], r["status"], r["method"], r["ip"],
                            r["geo"], r["distance_m"])


def _comment(r: sqlite3.Row) -> Comment:
    return Comment(r["id"], r["session_id"], r["text"], r["author"], r["created_at"],
                   r["upvotes"], bool(r["answered"]), bool(r["hidden"]))


def _submission(r: sqlite3.Row) -> Submission:
    return Submission(r["id"], r["session_id"], r["student_id"], r["name"], r["text"],
                      r["submitted_at"], r["device_id"])


class Repository:
    """Thread-safe data access object over a single SQLite connection."""

    def __init__(self, path: str = ":memory:"):
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._db.executescript(SCHEMA)
            self._migrate()

    def _migrate(self) -> None:
        for table, column, definition in MIGRATIONS:
            existing = {r["name"] for r in self._db.execute(f"PRAGMA table_info({table})")}
            if column not in existing:
                self._db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def _exec(self, sql: str, args: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            try:
                cur = self._db.execute(sql, args)
                self._db.commit()
                return cur
            except sqlite3.Error:
                self._db.rollback()
                raise

    def _all(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._db.execute(sql, args).fetchall()

    def _one(self, sql: str, args: tuple = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._db.execute(sql, args).fetchone()

    # ---- sessions -------------------------------------------------------
    def add_session(self, s: ClassSession) -> None:
        self._exec("INSERT INTO sessions (id,title,started_at,ended_at) VALUES (?,?,?,?)",
                   (s.id, s.title, s.started_at, s.ended_at))

    def get_session(self, session_id: str) -> ClassSession | None:
        r = self._one("SELECT * FROM sessions WHERE id=?", (session_id,))
        return _session(r) if r else None

    def list_sessions(self) -> list[ClassSession]:
        """Newest first."""
        return [_session(r) for r in self._all("SELECT * FROM sessions ORDER BY started_at DESC, rowid DESC")]

    def end_session(self, session_id: str, ended_at: float) -> None:
        self._exec("UPDATE sessions SET ended_at=? WHERE id=?", (ended_at, session_id))

    def set_homework_task(self, session_id: str, task: str) -> None:
        self._exec("UPDATE sessions SET homework_task=? WHERE id=?", (task, session_id))

    def set_summary(self, session_id: str, summary: str, published: bool) -> None:
        self._exec("UPDATE sessions SET summary=?, summary_published=? WHERE id=?",
                   (summary, int(published), session_id))

    def set_geofence(self, session_id: str, mode: str, lat: float | None, lon: float | None,
                     radius: int) -> None:
        self._exec("UPDATE sessions SET geo_mode=?, geo_lat=?, geo_lon=?, geo_radius=? WHERE id=?",
                   (mode, lat, lon, radius, session_id))

    def set_headcount(self, session_id: str, count: int | None, at: float | None) -> None:
        self._exec("UPDATE sessions SET headcount=?, headcount_at=? WHERE id=?", (count, at, session_id))

    # ---- attendance -----------------------------------------------------
    def add_attendance(self, a: AttendanceRecord) -> bool:
        """Returns False if this student is already checked in (also under a race)."""
        try:
            self._exec("INSERT INTO attendance (session_id,student_id,name,device_id,checked_in_at,"
                       "status,method,ip,geo,distance_m) VALUES (?,?,?,?,?,?,?,?,?,?)",
                       (a.session_id, a.student_id, a.name, a.device_id, a.checked_in_at,
                        a.status, a.method, a.ip, a.geo, a.distance_m))
            return True
        except sqlite3.IntegrityError:
            return False

    def find_attendance(self, session_id: str, *, student_id: str | None = None,
                        device_id: str | None = None) -> AttendanceRecord | None:
        if student_id is not None:
            r = self._one("SELECT * FROM attendance WHERE session_id=? AND student_id=?",
                          (session_id, student_id))
        else:
            r = self._one("SELECT * FROM attendance WHERE session_id=? AND device_id=?",
                          (session_id, device_id))
        return _attendance(r) if r else None

    def list_attendance(self, session_id: str) -> list[AttendanceRecord]:
        rows = self._all("SELECT * FROM attendance WHERE session_id=? ORDER BY checked_in_at",
                         (session_id,))
        return [_attendance(r) for r in rows]

    def delete_attendance(self, session_id: str, student_id: str) -> bool:
        cur = self._exec("DELETE FROM attendance WHERE session_id=? AND student_id=?",
                         (session_id, student_id))
        return cur.rowcount > 0

    # ---- comments -------------------------------------------------------
    def add_comment(self, session_id: str, text: str, author: str, created_at: float) -> Comment:
        cur = self._exec("INSERT INTO comments (session_id,text,author,created_at) VALUES (?,?,?,?)",
                         (session_id, text, author, created_at))
        return Comment(cur.lastrowid, session_id, text, author, created_at)

    def get_comment(self, comment_id: int) -> Comment | None:
        r = self._one(_COMMENT_SELECT + "WHERE c.id=?", (comment_id,))
        return _comment(r) if r else None

    def list_comments(self, session_id: str) -> list[Comment]:
        rows = self._all(_COMMENT_SELECT + "WHERE c.session_id=? ORDER BY c.created_at", (session_id,))
        return [_comment(r) for r in rows]

    def add_upvote(self, comment_id: int, device_id: str) -> bool:
        """Returns False if this device already upvoted the comment."""
        try:
            self._exec("INSERT INTO comment_upvotes VALUES (?,?)", (comment_id, device_id))
            return True
        except sqlite3.IntegrityError:
            return False

    def set_comment_flags(self, comment_id: int, answered: bool, hidden: bool) -> None:
        self._exec("UPDATE comments SET answered=?, hidden=? WHERE id=?",
                   (int(answered), int(hidden), comment_id))

    # ---- polls ----------------------------------------------------------
    def add_poll(self, session_id: str, question: str, options: list[str], created_at: float) -> Poll:
        cur = self._exec("INSERT INTO polls (session_id,question,options,created_at) VALUES (?,?,?,?)",
                         (session_id, question, json.dumps(options), created_at))
        return Poll(cur.lastrowid, session_id, question, options, created_at, True, [0] * len(options))

    def _poll_from_row(self, r: sqlite3.Row) -> Poll:
        options = json.loads(r["options"])
        votes = [0] * len(options)
        for v in self._all("SELECT option_index, COUNT(*) n FROM poll_votes WHERE poll_id=? "
                           "GROUP BY option_index", (r["id"],)):
            votes[v["option_index"]] = v["n"]
        return Poll(r["id"], r["session_id"], r["question"], options, r["created_at"],
                    bool(r["is_open"]), votes)

    def get_poll(self, poll_id: int) -> Poll | None:
        r = self._one("SELECT * FROM polls WHERE id=?", (poll_id,))
        return self._poll_from_row(r) if r else None

    def list_polls(self, session_id: str) -> list[Poll]:
        rows = self._all("SELECT * FROM polls WHERE session_id=? ORDER BY created_at, id", (session_id,))
        return [self._poll_from_row(r) for r in rows]

    def close_poll(self, poll_id: int) -> None:
        self._exec("UPDATE polls SET is_open=0 WHERE id=?", (poll_id,))

    def add_vote(self, poll_id: int, device_id: str, option_index: int) -> bool:
        """Returns False if this device already voted in the poll."""
        try:
            self._exec("INSERT INTO poll_votes VALUES (?,?,?)", (poll_id, device_id, option_index))
            return True
        except sqlite3.IntegrityError:
            return False

    # ---- homework submissions ------------------------------------------
    def upsert_submission(self, session_id: str, student_id: str, name: str, text: str,
                          submitted_at: float, device_id: str = "") -> Submission:
        self._exec("""INSERT INTO submissions (session_id,student_id,name,text,submitted_at,device_id)
                      VALUES (?,?,?,?,?,?) ON CONFLICT(session_id,student_id)
                      DO UPDATE SET name=excluded.name, text=excluded.text,
                                    submitted_at=excluded.submitted_at, device_id=excluded.device_id""",
                   (session_id, student_id, name, text, submitted_at, device_id))
        return self.get_submission(session_id, student_id)

    def get_submission(self, session_id: str, student_id: str) -> Submission | None:
        r = self._one("SELECT * FROM submissions WHERE session_id=? AND student_id=?",
                      (session_id, student_id))
        return _submission(r) if r else None

    def list_submissions(self, session_id: str) -> list[Submission]:
        rows = self._all("SELECT * FROM submissions WHERE session_id=? ORDER BY submitted_at, id",
                         (session_id,))
        return [_submission(r) for r in rows]

    def delete_submission(self, session_id: str, student_id: str) -> bool:
        cur = self._exec("DELETE FROM submissions WHERE session_id=? AND student_id=?",
                         (session_id, student_id))
        return cur.rowcount > 0
