"""The lecturer's spreadsheets: one workbook per class, and one for the whole course."""
from __future__ import annotations

from datetime import datetime

from ..i18n import tr
from ..repository import Repository
from ..xlsx import Workbook
from .sessions import SessionService


def _hhmm(t: float) -> str:
    return datetime.fromtimestamp(t).strftime("%H:%M:%S")


def _date(t: float) -> str:
    return datetime.fromtimestamp(t).strftime("%Y-%m-%d")


class ReportService:
    def __init__(self, repo: Repository, sessions: SessionService):
        self._repo = repo
        self._sessions = sessions

    def session_workbook(self, session_id: str, lang: str = "en") -> bytes:
        """Everything that happened in one class: attendance, polls and comments."""
        session = self._sessions.get(session_id)
        L = lambda key, **kw: tr(lang, key, **kw)  # noqa: E731
        wb = Workbook(rtl=lang == "he")

        checked_in = len(self._repo.list_attendance(session_id))
        rows = [[L("session"), session.title], [L("date"), _date(session.started_at)],
                [L("checked_in"), checked_in]]
        if session.headcount is None:
            rows.append([L("headcount"), L("not_counted")])
        else:
            rows += [[L("headcount"), session.headcount], [L("headcount_gap"), checked_in - session.headcount]]
        wb.add_sheet(L("overview"), rows, [36, 40])

        rows = [[L("num"), L("student_id"), L("name"), L("time"), L("status"), L("method"), L("location")]]
        for i, r in enumerate(self._repo.list_attendance(session_id), 1):
            rows.append([i, r.student_id, r.name, _hhmm(r.checked_in_at), L(r.status), L(r.method),
                         L("geo_" + r.geo, m=r.distance_m)])
        wb.add_sheet(L("attendance"), rows, [5, 14, 28, 13, 10, 20, 16])

        rows = [[L("question"), L("option"), L("votes"), L("percent")]]
        for p in self._repo.list_polls(session_id):
            for option, votes in zip(p.options, p.votes):
                rows.append([p.question, option, votes,
                             round(100 * votes / p.total_votes) if p.total_votes else 0])
        wb.add_sheet(L("polls"), rows, [40, 24, 8, 6])

        rows = [[L("time"), L("author"), L("comment"), L("upvotes"), L("answered")]]
        for c in self._repo.list_comments(session_id):
            if not c.hidden:
                rows.append([_hhmm(c.created_at), L(c.author) if c.author == "Anonymous" else c.author,
                             c.text, c.upvotes, L("yes") if c.answered else L("no")])
        wb.add_sheet(L("comments"), rows, [10, 18, 70, 10, 10])
        return wb.to_bytes()

    def course_matrix(self) -> dict:
        """Students x classes. A student is identified by ID; the latest name wins."""
        sessions = list(reversed(self._repo.list_sessions()))  # oldest first
        students: dict[str, dict] = {}
        for col, s in enumerate(sessions):
            for r in self._repo.list_attendance(s.id):
                st = students.setdefault(r.student_id, {"student_id": r.student_id, "name": r.name,
                                                        "marks": [""] * len(sessions)})
                st["name"] = r.name
                st["marks"][col] = r.status
        rows = sorted(students.values(), key=lambda st: st["name"])
        for st in rows:
            st["present"] = sum(1 for m in st["marks"] if m)
            st["percent"] = round(100 * st["present"] / len(sessions)) if sessions else 0
        return {"sessions": [{"id": s.id, "title": s.title, "date": _date(s.started_at),
                              "count": sum(1 for st in rows if st["marks"][col]),
                              "headcount": s.headcount}
                             for col, s in enumerate(sessions)],
                "students": rows}

    def course_workbook(self, lang: str = "en") -> bytes:
        L = lambda key: tr(lang, key)  # noqa: E731
        m = self.course_matrix()
        header = ([L("student_id"), L("name")] + [f"{s['date']} {s['title']}" for s in m["sessions"]]
                  + [L("present"), L("percent_present")])
        mark = {"on_time": "✓", "late": L("late"), "": ""}
        rows = [header] + [[st["student_id"], st["name"]] + [mark[x] for x in st["marks"]]
                           + [st["present"], st["percent"]] for st in m["students"]]
        wb = Workbook(rtl=lang == "he")
        wb.add_sheet(L("summary_sheet"), rows, [14, 28] + [22] * len(m["sessions"]) + [10, 12])
        return wb.to_bytes()
