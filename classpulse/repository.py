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


class Repository:
    """Thread-safe data access object over a single SQLite connection."""

    def __init__(self, path: str = ":memory:"):
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._db.executescript(SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def _exec(self, sql: str, args: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._db.execute(sql, args)
            self._db.commit()
            return cur

    def _all(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._db.execute(sql, args).fetchall()

    def _one(self, sql: str, args: tuple = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._db.execute(sql, args).fetchone()

    # ---- sessions -------------------------------------------------------
    def add_session(self, s: ClassSession) -> None:
        self._exec("INSERT INTO sessions VALUES (?,?,?,?)",
                   (s.id, s.title, s.started_at, s.ended_at))

    def get_session(self, session_id: str) -> ClassSession | None:
        r = self._one("SELECT * FROM sessions WHERE id=?", (session_id,))
        return ClassSession(**dict(r)) if r else None

    def list_sessions(self) -> list[ClassSession]:
        rows = self._all("SELECT * FROM sessions ORDER BY started_at DESC")
        return [ClassSession(**dict(r)) for r in rows]

    def end_session(self, session_id: str, ended_at: float) -> None:
        self._exec("UPDATE sessions SET ended_at=? WHERE id=?", (ended_at, session_id))

    # ---- attendance -----------------------------------------------------
    def add_attendance(self, a: AttendanceRecord) -> None:
        self._exec("INSERT INTO attendance VALUES (?,?,?,?,?)",
                   (a.session_id, a.student_id, a.name, a.device_id, a.checked_in_at))

    def find_attendance(self, session_id: str, *, student_id: str | None = None,
                        device_id: str | None = None) -> AttendanceRecord | None:
        if student_id is not None:
            r = self._one("SELECT * FROM attendance WHERE session_id=? AND student_id=?",
                          (session_id, student_id))
        else:
            r = self._one("SELECT * FROM attendance WHERE session_id=? AND device_id=?",
                          (session_id, device_id))
        return AttendanceRecord(**dict(r)) if r else None

    def list_attendance(self, session_id: str) -> list[AttendanceRecord]:
        rows = self._all("SELECT * FROM attendance WHERE session_id=? ORDER BY checked_in_at",
                         (session_id,))
        return [AttendanceRecord(**dict(r)) for r in rows]

    # ---- comments -------------------------------------------------------
    def add_comment(self, session_id: str, text: str, author: str, created_at: float) -> Comment:
        cur = self._exec("INSERT INTO comments (session_id,text,author,created_at) VALUES (?,?,?,?)",
                         (session_id, text, author, created_at))
        return Comment(cur.lastrowid, session_id, text, author, created_at, 0)

    def get_comment(self, comment_id: int) -> Comment | None:
        r = self._one("""SELECT c.*, (SELECT COUNT(*) FROM comment_upvotes u WHERE u.comment_id=c.id)
                         AS upvotes FROM comments c WHERE c.id=?""", (comment_id,))
        return Comment(**dict(r)) if r else None

    def list_comments(self, session_id: str) -> list[Comment]:
        rows = self._all("""SELECT c.*, (SELECT COUNT(*) FROM comment_upvotes u WHERE u.comment_id=c.id)
                            AS upvotes FROM comments c WHERE c.session_id=? ORDER BY c.created_at""",
                         (session_id,))
        return [Comment(**dict(r)) for r in rows]

    def add_upvote(self, comment_id: int, device_id: str) -> bool:
        """Returns False if this device already upvoted the comment."""
        try:
            self._exec("INSERT INTO comment_upvotes VALUES (?,?)", (comment_id, device_id))
            return True
        except sqlite3.IntegrityError:
            return False

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
        rows = self._all("SELECT * FROM polls WHERE session_id=? ORDER BY created_at", (session_id,))
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
                          submitted_at: float) -> Submission:
        self._exec("""INSERT INTO submissions (session_id,student_id,name,text,submitted_at)
                      VALUES (?,?,?,?,?) ON CONFLICT(session_id,student_id)
                      DO UPDATE SET name=excluded.name, text=excluded.text,
                                    submitted_at=excluded.submitted_at""",
                   (session_id, student_id, name, text, submitted_at))
        r = self._one("SELECT * FROM submissions WHERE session_id=? AND student_id=?",
                      (session_id, student_id))
        return Submission(**dict(r))

    def list_submissions(self, session_id: str) -> list[Submission]:
        rows = self._all("SELECT * FROM submissions WHERE session_id=? ORDER BY submitted_at",
                         (session_id,))
        return [Submission(**dict(r)) for r in rows]
