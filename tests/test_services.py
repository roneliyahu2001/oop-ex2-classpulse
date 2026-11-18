"""Unit tests per class (see docs/08-testing-strategy.md, section 8.3)."""
import csv
import io
import os
import sqlite3
import tempfile
import unittest
import zipfile
from xml.etree import ElementTree

from classica.events import EventBus, staff_channel
from classica.geo import GeoFence, haversine_m, valid_coordinates
from classica.llm import FakeLLMClient
from classica.models import DomainError, Submission
from classica.ratelimit import RateLimiter
from classica.repository import Repository
from classica.services.attendance import safe_cell
from classica.services.review import SimilarityAnalyzer
from classica.services.summary import ExtractiveSummarizer, LLMSummarizer, SummaryService
from classica.text_tools import split_chunks, transcript_to_text
from classica.tokens import TokenRotator
from classica.xlsx import Workbook, column_letter

from tests.helpers import (CLASSROOM, FAR, HOMEWORK_A, HOMEWORK_B, HOMEWORK_SHORT, NEAR, FakeClock,
                           close_apps, make_app)


def tearDownModule():
    close_apps()


class ServiceTestCase(unittest.TestCase):
    def assertCode(self, code, fn):
        with self.assertRaises(DomainError) as e:
            fn()
        self.assertEqual(e.exception.code, code)
        return e.exception


class TokenRotatorTest(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock(1000.0)
        self.r = TokenRotator(b"secret", period=20, clock=self.clock)

    def test_current_token_is_valid(self):
        self.assertTrue(self.r.is_valid("s1", self.r.current("s1")))

    def test_previous_window_still_accepted(self):
        t = self.r.current("s1")
        self.clock.advance(20)
        self.assertTrue(self.r.is_valid("s1", t))

    def test_token_expires_after_two_windows(self):
        t, code = self.r.current("s1"), self.r.current_code("s1")
        self.clock.advance(40)
        self.assertFalse(self.r.is_valid("s1", t))
        self.assertFalse(self.r.is_valid("s1", code))

    def test_token_bound_to_session(self):
        self.assertFalse(self.r.is_valid("s2", self.r.current("s1")))

    def test_seconds_left(self):
        self.clock.t = 1005.0
        self.assertEqual(self.r.seconds_left(), 15)

    def test_typed_code_is_six_digits_and_tells_the_method(self):
        code = self.r.current_code("s1")
        self.assertRegex(code, r"^\d{6}$")
        self.assertEqual(self.r.match("s1", code), "code")
        self.assertEqual(self.r.match("s1", f"{code[:3]} {code[3:]}"), "code")
        self.assertEqual(self.r.match("s1", self.r.current("s1")), "qr")

    def test_garbage_input_is_rejected_not_crashing(self):
        for bad in ["", "000000x", "קוד", "😀" * 5]:
            self.assertIsNone(self.r.match("s1", bad))


class RateLimiterTest(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.limiter = RateLimiter(3, 60, self.clock)

    def test_blocks_after_the_limit(self):
        self.assertEqual([self.limiter.allow("a") for _ in range(4)], [True, True, True, False])

    def test_keys_are_independent(self):
        for _ in range(3):
            self.limiter.allow("a")
        self.assertTrue(self.limiter.allow("b"))

    def test_window_slides(self):
        for _ in range(3):
            self.limiter.allow("a")
        self.clock.advance(59)
        self.assertFalse(self.limiter.allow("a"))
        self.clock.advance(1)
        self.assertTrue(self.limiter.allow("a"))

    def test_reset(self):
        for _ in range(3):
            self.limiter.allow("a")
        self.limiter.reset("a")
        self.assertTrue(self.limiter.allow("a"))


class GeoTest(unittest.TestCase):
    def test_haversine_one_degree_of_latitude(self):
        self.assertAlmostEqual(haversine_m(32.0, 34.8, 33.0, 34.8), 111_195, delta=100)
        self.assertEqual(haversine_m(32.0, 34.8, 32.0, 34.8), 0)

    def test_fence_contains(self):
        fence = GeoFence(*CLASSROOM, 150)
        self.assertTrue(fence.contains(*NEAR))
        self.assertFalse(fence.contains(*FAR))

    def test_accuracy_gives_limited_benefit_of_the_doubt(self):
        fence = GeoFence(*CLASSROOM, 30)
        self.assertFalse(fence.contains(*NEAR))                  # about 55 m away, 30 m radius
        self.assertTrue(fence.contains(*NEAR, accuracy_m=40))    # a 40 m error explains it
        self.assertFalse(fence.contains(*FAR, accuracy_m=50_000))  # "accuracy 50 km" earns only 100 m

    def test_valid_coordinates(self):
        self.assertTrue(valid_coordinates(32.1, 34.8))
        for lat, lon in [(91, 0), (0, 181), (float("nan"), 0), (float("inf"), 0)]:
            self.assertFalse(valid_coordinates(lat, lon))


class EventBusTest(unittest.TestCase):
    def test_publish_reaches_only_channel_subscribers(self):
        bus = EventBus()
        a, b = bus.subscribe("x"), bus.subscribe("y")
        bus.publish("x", "poll", {"id": 1})
        self.assertEqual(a.get_nowait(), ("poll", {"id": 1}))
        self.assertTrue(b.empty())

    def test_one_queue_can_follow_two_channels(self):
        bus = EventBus()
        q = bus.subscribe("x", staff_channel("x"))
        bus.publish(staff_channel("x"), "attendance", {"count": 1})
        bus.publish("x", "poll", {})
        self.assertEqual([q.get_nowait()[0], q.get_nowait()[0]], ["attendance", "poll"])

    def test_unsubscribe(self):
        bus = EventBus()
        q = bus.subscribe("x", "y")
        bus.unsubscribe(q)
        self.assertEqual((bus.subscriber_count("x"), bus.subscriber_count("y")), (0, 0))


class RepositoryMigrationTest(unittest.TestCase):
    def test_database_file_from_version_1_keeps_working(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "old.db")
            old = sqlite3.connect(path)
            old.executescript("""
                CREATE TABLE sessions (id TEXT PRIMARY KEY, title TEXT NOT NULL,
                                       started_at REAL NOT NULL, ended_at REAL);
                CREATE TABLE attendance (session_id TEXT NOT NULL, student_id TEXT NOT NULL,
                    name TEXT NOT NULL, device_id TEXT NOT NULL, checked_in_at REAL NOT NULL,
                    PRIMARY KEY (session_id, student_id));
                INSERT INTO sessions VALUES ('abc', 'Old lecture', 1.0, 2.0);
                INSERT INTO attendance VALUES ('abc', '123456', 'Dana', 'd1', 1.5);
            """)
            old.commit()
            old.close()
            repo = Repository(path)
            s = repo.get_session("abc")
            self.assertEqual((s.title, s.geo_mode, s.summary_published), ("Old lecture", "off", False))
            rec = repo.list_attendance("abc")[0]
            self.assertEqual((rec.name, rec.status, rec.method, rec.geo), ("Dana", "on_time", "qr", ""))
            repo.close()


class SessionServiceTest(ServiceTestCase):
    def setUp(self):
        self.app = make_app()

    def test_start_and_end(self):
        s = self.app.sessions.start("  OOP 1 ")
        self.assertEqual(s.title, "OOP 1")
        self.assertTrue(s.is_active)
        self.assertFalse(self.app.sessions.end(s.id).is_active)

    def test_empty_title_rejected(self):
        self.assertCode("TITLE_REQUIRED", lambda: self.app.sessions.start("  "))

    def test_cannot_end_twice(self):
        s = self.app.sessions.start("x")
        self.app.sessions.end(s.id)
        self.assertCode("SESSION_CLOSED", lambda: self.app.sessions.end(s.id))

    def test_unknown_session(self):
        self.assertEqual(self.assertCode("SESSION_NOT_FOUND", lambda: self.app.sessions.get("nope")).status, 404)

    def test_active_is_the_newest_open_class(self):
        self.assertIsNone(self.app.sessions.active())
        a = self.app.sessions.start("a")
        b = self.app.sessions.start("b")
        self.assertEqual(self.app.sessions.active().id, b.id)
        self.app.sessions.end(b.id)
        self.assertEqual(self.app.sessions.active().id, a.id)

    def test_summary_is_a_draft_until_published(self):
        s = self.app.sessions.start("x")
        q = self.app.bus.subscribe(s.id)
        draft = self.app.sessions.save_summary(s.id, "Key points...", published=False)
        self.assertEqual(draft.to_dict()["summary"], "")                    # what students get
        self.assertEqual(draft.to_dict(lecturer=True)["summary"], "Key points...")
        self.assertEqual(q.get_nowait()[1]["summary"], "")
        shared = self.app.sessions.save_summary(s.id, "Key points...", published=True)
        self.assertEqual(shared.to_dict()["summary"], "Key points...")
        self.assertFalse(self.app.sessions.save_summary(s.id, "  ", published=True).summary_published)

    def test_head_count(self):
        s = self.app.sessions.start("x")
        counted = self.app.sessions.set_headcount(s.id, 27)
        self.assertEqual((counted.headcount, counted.headcount_at), (27, self.app.sessions._clock()))
        self.assertNotIn("headcount", counted.to_dict())                     # students never see it
        self.assertEqual(counted.to_dict(lecturer=True)["headcount"], 27)
        self.assertIsNone(self.app.sessions.set_headcount(s.id, None).headcount)  # cleared
        self.assertCode("BAD_HEADCOUNT", lambda: self.app.sessions.set_headcount(s.id, -1))
        self.assertCode("BAD_HEADCOUNT", lambda: self.app.sessions.set_headcount(s.id, 2001))

    def test_homework_task(self):
        s = self.app.sessions.start("x")
        self.assertEqual(self.app.sessions.set_homework_task(s.id, " Explain SRP ").homework_task, "Explain SRP")

    def test_geofence_settings(self):
        s = self.app.sessions.start("x")
        on = self.app.sessions.set_geofence(s.id, "block", *CLASSROOM, radius=5)
        self.assertEqual((on.geo_mode, on.geo_radius), ("block", 30))        # radius is clamped
        self.assertNotIn("geo_lat", on.to_dict())                           # students never get the point
        self.assertEqual(on.to_dict()["geo_mode"], "block")
        self.assertCode("BAD_LOCATION", lambda: self.app.sessions.set_geofence(s.id, "block"))
        self.assertCode("BAD_LOCATION", lambda: self.app.sessions.set_geofence(s.id, "flag", 95.0, 0.0))
        self.assertCode("BAD_LOCATION", lambda: self.app.sessions.set_geofence(s.id, "nonsense"))
        off = self.app.sessions.set_geofence(s.id, "off")
        self.assertEqual((off.geo_mode, off.geo_lat), ("off", None))


class AttendanceServiceTest(ServiceTestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.app = make_app(self.clock)
        self.s = self.app.sessions.start("Lecture")

    def checkin(self, sid="123456", name="Dana Levi", dev="d1", tok=None, **kw):
        return self.app.attendance.check_in(self.s.id, tok or self.app.rotator.current(self.s.id),
                                            sid, name, dev, **kw)

    def test_happy_path(self):
        rec = self.checkin()
        self.assertEqual((rec.name, rec.status, rec.method), ("Dana Levi", "on_time", "qr"))
        self.assertNotIn("device_id", rec.to_dict())
        self.assertNotIn("ip", rec.to_dict())

    def test_names_travel_only_on_the_staff_channel(self):
        public = self.app.bus.subscribe(self.s.id)
        staff = self.app.bus.subscribe(staff_channel(self.s.id))
        self.checkin()
        self.assertTrue(public.empty())
        self.assertEqual(staff.get_nowait(), ("attendance", {"count": 1}))

    def test_rescan_same_device_is_idempotent(self):
        a = self.checkin()
        b = self.checkin()
        self.assertEqual(a.checked_in_at, b.checked_in_at)
        self.assertEqual(len(self.app.attendance.list(self.s.id)), 1)

    def test_same_student_other_device_rejected(self):
        self.checkin()
        self.assertCode("ALREADY_CHECKED_IN", lambda: self.checkin(dev="d2"))

    def test_one_device_cannot_check_in_two_students(self):
        self.checkin()
        self.assertCode("DEVICE_USED", lambda: self.checkin(sid="654321", name="Friend"))

    def test_expired_token(self):
        tok = self.app.rotator.current(self.s.id)
        self.clock.advance(60)
        self.assertCode("TOKEN_EXPIRED", lambda: self.checkin(tok=tok))

    def test_typed_code(self):
        rec = self.checkin(tok=self.app.rotator.current_code(self.s.id))
        self.assertEqual(rec.method, "code")

    def test_late_after_fifteen_minutes(self):
        self.clock.advance(14 * 60)
        self.assertEqual(self.checkin().status, "on_time")
        self.clock.advance(2 * 60)
        self.assertEqual(self.checkin(sid="654321", dev="d2").status, "late")

    def test_validation(self):
        self.assertCode("BAD_STUDENT_ID", lambda: self.checkin(sid="12a"))
        self.assertCode("NAME_REQUIRED", lambda: self.checkin(name="   "))

    def test_closed_session(self):
        self.app.sessions.end(self.s.id)
        self.assertCode("SESSION_CLOSED", self.checkin)

    def test_lecturer_adds_and_removes_by_hand(self):
        self.app.sessions.end(self.s.id)                       # fixing the list after class is allowed
        rec = self.app.attendance.add_manual(self.s.id, "777777", "No Phone")
        self.assertEqual(rec.method, "manual")
        self.assertCode("ALREADY_CHECKED_IN", lambda: self.app.attendance.add_manual(self.s.id, "777777", "X"))
        self.assertCode("BAD_STUDENT_ID", lambda: self.app.attendance.add_manual(self.s.id, "7", "X"))
        self.app.attendance.remove(self.s.id, "777777")
        self.assertEqual(self.app.attendance.list(self.s.id), [])
        self.assertCode("NOT_CHECKED_IN", lambda: self.app.attendance.remove(self.s.id, "777777"))

    def test_two_checkins_from_one_address_are_flagged(self):
        self.checkin(ip="10.0.0.7")
        self.checkin(sid="654321", dev="d2", ip="10.0.0.7")
        self.checkin(sid="111111", dev="d3", ip="10.0.0.9")
        self.checkin(sid="222222", dev="d4")                    # unknown address (tunnel): never flagged
        flags = {r["student_id"]: r["shared_ip"] for r in self.app.attendance.list_for_lecturer(self.s.id)}
        self.assertEqual(flags, {"123456": True, "654321": True, "111111": False, "222222": False})

    def test_csv_export_has_bom_and_hebrew(self):
        self.checkin(name="רון אליהו")
        data = self.app.attendance.export_csv(self.s.id)
        self.assertTrue(data.startswith(b"\xef\xbb\xbf"))
        rows = list(csv.reader(io.StringIO(data.decode("utf-8-sig"))))
        self.assertEqual(rows[0][:3], ["#", "Student ID", "Name"])
        self.assertEqual(rows[1][1:3], ["123456", "רון אליהו"])
        hebrew = list(csv.reader(io.StringIO(self.app.attendance.export_csv(self.s.id, "he").decode("utf-8-sig"))))
        self.assertEqual((hebrew[0][2], hebrew[1][4]), ("שם", "בזמן"))

    def test_csv_cannot_smuggle_a_formula(self):
        self.checkin(name='=HYPERLINK("http://evil","click")')
        text = self.app.attendance.export_csv(self.s.id).decode("utf-8-sig")
        self.assertIn("'=HYPERLINK", text)
        self.assertEqual(safe_cell("Dana"), "Dana")

    # ---- location check ----
    def test_location_ignored_when_check_is_off(self):
        rec = self.checkin(location=(*FAR, 10.0))
        self.assertEqual((rec.geo, rec.distance_m), ("", None))

    def test_block_mode(self):
        self.app.sessions.set_geofence(self.s.id, "block", *CLASSROOM, radius=150)
        self.assertEqual(self.assertCode("LOCATION_REQUIRED", self.checkin).status, 403)
        self.assertCode("TOO_FAR", lambda: self.checkin(location=(*FAR, 10.0)))
        self.assertCode("LOCATION_REQUIRED", lambda: self.checkin(location=(999.0, 0.0, 0.0)))
        self.assertEqual(self.app.attendance.list(self.s.id), [])
        rec = self.checkin(location=(*NEAR, 10.0))
        self.assertEqual(rec.geo, "ok")
        self.assertAlmostEqual(rec.distance_m, 56, delta=3)

    def test_flag_mode_lets_everyone_in_and_marks_them(self):
        self.app.sessions.set_geofence(self.s.id, "flag", *CLASSROOM, radius=150)
        self.assertEqual(self.checkin(location=(*NEAR, 10.0)).geo, "ok")
        far = self.checkin(sid="654321", dev="d2", location=(*FAR, 10.0))
        self.assertEqual(far.geo, "far")
        self.assertAlmostEqual(far.distance_m, 11_120, delta=50)
        self.assertEqual(self.checkin(sid="111111", dev="d3").geo, "none")
        self.assertIn("Far (", self.app.attendance.export_csv(self.s.id).decode("utf-8-sig"))

    def test_lecturer_can_always_add_by_hand(self):
        self.app.sessions.set_geofence(self.s.id, "block", *CLASSROOM)
        self.assertEqual(self.app.attendance.add_manual(self.s.id, "777777", "No Phone").geo, "")


class CommentServiceTest(ServiceTestCase):
    def setUp(self):
        self.app = make_app()
        self.s = self.app.sessions.start("L")

    def test_post_anonymous_by_default(self):
        c = self.app.comments.post(self.s.id, "Can you repeat slide 4?")
        self.assertEqual(c.author, "Anonymous")

    def test_upvote_once_per_device(self):
        c = self.app.comments.post(self.s.id, "q")
        self.assertEqual(self.app.comments.upvote(c.id, "d1").upvotes, 1)
        self.assertCode("ALREADY_UPVOTED", lambda: self.app.comments.upvote(c.id, "d1"))
        self.assertEqual(self.app.comments.upvote(c.id, "d2").upvotes, 2)

    def test_offline_comment_after_class_end_allowed(self):
        self.app.sessions.end(self.s.id)
        self.app.comments.post(self.s.id, "Thanks, great lecture")
        self.assertEqual(len(self.app.comments.list(self.s.id)), 1)

    def test_validation(self):
        self.assertCode("EMPTY_COMMENT", lambda: self.app.comments.post(self.s.id, ""))
        self.assertCode("COMMENT_TOO_LONG", lambda: self.app.comments.post(self.s.id, "x" * 501))

    def test_lecturer_marks_answered_and_hides(self):
        c = self.app.comments.post(self.s.id, "rude words")
        q = self.app.bus.subscribe(self.s.id)
        self.assertTrue(self.app.comments.moderate(c.id, answered=True).answered)
        hidden = self.app.comments.moderate(c.id, hidden=True)
        self.assertTrue(hidden.hidden and hidden.answered)               # one flag does not reset the other
        self.assertEqual(q.get_nowait()[0], "comment")                   # phones are told right away
        self.assertEqual(self.app.comments.list(self.s.id), [])
        self.assertEqual(len(self.app.comments.list(self.s.id, include_hidden=True)), 1)
        self.assertCode("COMMENT_NOT_FOUND", lambda: self.app.comments.upvote(c.id, "d1"))
        self.assertCode("COMMENT_NOT_FOUND", lambda: self.app.comments.moderate(999, hidden=True))


class PollServiceTest(ServiceTestCase):
    def setUp(self):
        self.app = make_app()
        self.s = self.app.sessions.start("L")

    def test_vote_counts(self):
        p = self.app.polls.create(self.s.id, "Clear?", ["Yes", "No", " "])
        self.assertEqual(p.options, ["Yes", "No"])
        self.app.polls.vote(p.id, 0, "d1")
        p = self.app.polls.vote(p.id, 0, "d2")
        self.assertEqual(p.votes, [2, 0])
        self.assertEqual(p.total_votes, 2)

    def test_one_vote_per_device(self):
        p = self.app.polls.create(self.s.id, "Q", ["a", "b"])
        self.app.polls.vote(p.id, 0, "d1")
        self.assertCode("ALREADY_VOTED", lambda: self.app.polls.vote(p.id, 1, "d1"))

    def test_new_poll_closes_previous(self):
        p1 = self.app.polls.create(self.s.id, "Q1", ["a", "b"])
        p2 = self.app.polls.create(self.s.id, "Q2", ["a", "b"])
        self.assertFalse(self.app.polls.get(p1.id).is_open)
        self.assertEqual(self.app.polls.open_poll(self.s.id).id, p2.id)

    def test_closed_poll_rejects_votes(self):
        p = self.app.polls.create(self.s.id, "Q", ["a", "b"])
        self.app.polls.close(p.id)
        self.assertCode("POLL_CLOSED", lambda: self.app.polls.vote(p.id, 0, "d1"))

    def test_validation(self):
        self.assertCode("BAD_OPTIONS", lambda: self.app.polls.create(self.s.id, "Q", ["only one"]))
        self.assertCode("BAD_OPTIONS", lambda: self.app.polls.create(self.s.id, "Q", list("abcdefg")))
        p = self.app.polls.create(self.s.id, "Q", ["a", "b"])
        self.assertCode("BAD_OPTION", lambda: self.app.polls.vote(p.id, 5, "d1"))
        self.assertCode("BAD_OPTION", lambda: self.app.polls.vote(p.id, -1, "d1"))


def read_xlsx(data: bytes) -> dict:
    """{sheet name: [[cell text, ...], ...]} read back from a workbook, parsing every XML part."""
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        parts = {name: ElementTree.fromstring(z.read(name)) for name in z.namelist()}
    names = [s.get("name") for s in parts["xl/workbook.xml"].find("m:sheets", ns)]
    out = {}
    for i, name in enumerate(names, 1):
        rows = []
        for row in parts[f"xl/worksheets/sheet{i}.xml"].iter("{%s}row" % ns["m"]):
            rows.append(["".join(c.itertext()) for c in row])
        out[name] = rows
    return out


class WorkbookTest(unittest.TestCase):
    def test_column_letters(self):
        self.assertEqual([column_letter(i) for i in (0, 25, 26, 27, 701, 702)],
                         ["A", "Z", "AA", "AB", "ZZ", "AAA"])

    def test_cells_survive_a_round_trip(self):
        wb = Workbook()
        wb.add_sheet("Data", [["ID", "Name", "n"], ["012345678", "רון <&> \"x\"", 7], ["", None, 2.5]])
        sheets = read_xlsx(wb.to_bytes())
        self.assertEqual(sheets["Data"][1], ["012345678", "רון <&> \"x\"", "7"])   # leading zero kept

    def test_ids_are_text_and_numbers_are_numbers(self):
        wb = Workbook()
        wb.add_sheet("S", [["h"], ["012"], [12]])
        with zipfile.ZipFile(io.BytesIO(wb.to_bytes())) as z:
            xml = z.read("xl/worksheets/sheet1.xml").decode()
        self.assertIn('<c r="A2" t="inlineStr">', xml)
        self.assertIn('<c r="A3"><v>12</v></c>', xml)
        self.assertNotIn("rightToLeft", xml)

    def test_sheet_names_are_made_legal_and_unique(self):
        wb = Workbook(rtl=True)
        wb.add_sheet("a/b:c", [["x"]])
        wb.add_sheet("a b c", [["x"]])
        wb.add_sheet("x" * 40, [["x"]])
        data = wb.to_bytes()
        self.assertEqual(list(read_xlsx(data)), ["a b c", "a b c (2)", "x" * 31])
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            self.assertIn('rightToLeft="1"', z.read("xl/worksheets/sheet1.xml").decode())


class ReportServiceTest(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.app = make_app(self.clock)
        self.s1 = self.app.sessions.start("Lecture 1")
        self.checkin(self.s1, "012345678", "Dana", "d1")
        self.checkin(self.s1, "222222", "Yossi", "d2")
        self.clock.advance(7 * 86400)
        self.s2 = self.app.sessions.start("Lecture 2")
        self.clock.advance(20 * 60)
        self.checkin(self.s2, "012345678", "Dana Levi", "d1")       # late, and a fuller name

    def checkin(self, s, sid, name, dev):
        self.app.attendance.check_in(s.id, self.app.rotator.current(s.id), sid, name, dev)

    def test_course_matrix(self):
        m = self.app.reports.course_matrix()
        self.assertEqual([s["title"] for s in m["sessions"]], ["Lecture 1", "Lecture 2"])
        self.assertEqual([s["count"] for s in m["sessions"]], [2, 1])
        dana, yossi = m["students"]
        self.assertEqual((dana["name"], dana["marks"], dana["present"], dana["percent"]),
                         ("Dana Levi", ["on_time", "late"], 2, 100))
        self.assertEqual((yossi["marks"], yossi["percent"]), (["on_time", ""], 50))

    def test_course_workbook(self):
        rows = read_xlsx(self.app.reports.course_workbook())["Attendance summary"]
        self.assertEqual(rows[0][:2] + rows[0][-2:], ["Student ID", "Name", "Present", "% present"])
        self.assertEqual(rows[1], ["012345678", "Dana Levi", "✓", "Late", "2", "100"])
        self.assertEqual(rows[2], ["222222", "Yossi", "✓", "1", "50"])            # empty cells are omitted

    def test_session_workbook_has_four_sheets(self):
        p = self.app.polls.create(self.s1.id, "Clear?", ["Yes", "No"])
        self.app.polls.vote(p.id, 0, "d1")
        self.app.comments.post(self.s1.id, "Nice")
        hidden = self.app.comments.post(self.s1.id, "rude")
        self.app.comments.moderate(hidden.id, hidden=True)
        sheets = read_xlsx(self.app.reports.session_workbook(self.s1.id))
        self.assertEqual(list(sheets), ["Overview", "Attendance", "Polls", "Comments"])
        self.assertIn(["Checked in", "2"], sheets["Overview"])
        self.assertIn(["People in the class photo", "No photo counted"], sheets["Overview"])
        self.assertEqual(sheets["Attendance"][1][:3], ["1", "012345678", "Dana"])
        self.assertEqual(sheets["Polls"][1], ["Clear?", "Yes", "1", "100"])
        self.assertEqual(len(sheets["Comments"]), 2)                               # header + visible one
        self.assertEqual(list(read_xlsx(self.app.reports.session_workbook(self.s1.id, "he"))),
                         ["סיכום", "נוכחות", "סקרים", "שאלות והערות"])

    def test_head_count_is_compared_with_check_ins(self):
        self.app.sessions.set_headcount(self.s1.id, 1)
        overview = read_xlsx(self.app.reports.session_workbook(self.s1.id))["Overview"]
        self.assertIn(["People in the class photo", "1"], overview)
        self.assertIn(["Check-ins minus people in the photo", "1"], overview)   # 2 checked in, 1 in the photo
        self.assertEqual(self.app.reports.course_matrix()["sessions"][0]["headcount"], 1)


VTT = """WEBVTT

1
00:00:01.000 --> 00:00:04.000
<v Lecturer>Today we talk about the strategy design pattern.

2
00:00:04.000 --> 00:00:09.000
The strategy pattern lets us swap an algorithm at runtime behind a common interface.
"""


class SummaryTest(ServiceTestCase):
    LONG = " ".join(["The strategy pattern defines a family of algorithms and makes them interchangeable."] * 3
                    + ["Composition over inheritance reduces coupling between classes in the design."] * 3)

    def test_vtt_parsing(self):
        text = transcript_to_text(VTT)
        self.assertNotIn("-->", text)
        self.assertNotIn("<v", text)
        self.assertTrue(text.startswith("Today we talk"))

    def test_extractive_summary_offline(self):
        r = SummaryService(None).summarize(self.LONG)
        self.assertEqual(r["method"], "extractive")
        self.assertIn("strategy", r["summary"].lower())
        self.assertIn("נושאים מרכזיים", SummaryService(None).summarize(self.LONG, "he")["summary"])

    def test_llm_summary_used_when_available(self):
        fake = FakeLLMClient("Overview: strategy pattern")
        r = SummaryService(LLMSummarizer(fake)).summarize(self.LONG)
        self.assertEqual(r["method"], "llm")
        self.assertEqual(len(fake.calls), 1)
        self.assertIn("<transcript>", fake.calls[0][1])

    def test_long_lecture_is_summarised_in_parts_then_combined(self):
        fake = FakeLLMClient("- point")
        summarizer = LLMSummarizer(fake)
        summarizer.CHUNK_CHARS = 200
        summarizer.summarize(self.LONG)                      # about 480 characters -> 3 parts
        self.assertEqual(len(fake.calls), 4)
        self.assertIn("Part 1 of 3", fake.calls[0][1])
        self.assertIn("<notes>", fake.calls[-1][1])

    def test_split_chunks_loses_nothing(self):
        chunks = split_chunks(self.LONG, 100)
        self.assertTrue(all(len(c) <= 100 for c in chunks))
        self.assertEqual(" ".join(chunks).split(), self.LONG.split())
        self.assertEqual(split_chunks("short", 100), ["short"])

    def test_falls_back_when_llm_fails(self):
        class Broken(LLMSummarizer):
            def summarize(self, text, lang="en"):
                raise ConnectionError("offline")
        r = SummaryService(Broken(FakeLLMClient())).summarize(self.LONG)
        self.assertEqual(r["method"], "extractive")
        self.assertIn("ConnectionError", r["note"])

    def test_too_short(self):
        self.assertCode("TRANSCRIPT_TOO_SHORT", lambda: SummaryService(None).summarize("hello world"))

    def test_extractive_limits_sentences(self):
        out = ExtractiveSummarizer(sentences=2).summarize(self.LONG)
        self.assertEqual(out.count("\n- "), 2)


class ReviewTest(ServiceTestCase):
    def setUp(self):
        self.app = make_app()
        self.s = self.app.sessions.start("HW")
        sub = self.app.reviews.submit
        sub(self.s.id, "111111", "A", HOMEWORK_A, "devA")
        sub(self.s.id, "222222", "B", HOMEWORK_B, "devB")
        sub(self.s.id, "333333", "C", HOMEWORK_SHORT, "devC")

    def test_resubmission_from_the_same_phone_replaces(self):
        staff = self.app.bus.subscribe(staff_channel(self.s.id))
        self.app.reviews.submit(self.s.id, "111111", "A", HOMEWORK_B, "devA")
        self.assertEqual(staff.get_nowait(), ("homework", {"student_id": "111111"}))
        self.assertEqual(len(self.app.repo.list_submissions(self.s.id)), 3)

    def test_nobody_else_can_overwrite_a_submission(self):
        self.assertEqual(self.assertCode("SUBMISSION_LOCKED", lambda: self.app.reviews.submit(
            self.s.id, "111111", "Impostor", HOMEWORK_B, "devX")).status, 409)
        self.app.reviews.delete(self.s.id, "111111")                    # the lecturer unlocks it
        self.app.reviews.submit(self.s.id, "111111", "A", HOMEWORK_A, "devX")
        self.assertCode("NO_SUBMISSION", lambda: self.app.reviews.delete(self.s.id, "999999"))

    def test_short_submission_rejected(self):
        self.assertCode("SUBMISSION_TOO_SHORT", lambda: self.app.reviews.submit(self.s.id, "9", "x", "too short"))

    def test_student_view_hides_identities(self):
        r = self.app.reviews.review_student(self.s.id, "333333", device_id="devC")
        self.assertNotIn("most_similar_to", r["comparison"])
        self.assertEqual(r["method"], "heuristic")
        self.assertIn("short", r["review"])

    def test_a_student_cannot_read_someone_elses_review(self):
        self.assertEqual(self.assertCode("NOT_YOUR_SUBMISSION", lambda: self.app.reviews.review_student(
            self.s.id, "111111", device_id="devC")).status, 403)

    def test_lecturer_view_shows_identities(self):
        r = self.app.reviews.review_student(self.s.id, "111111", lecturer=True)
        self.assertIn("most_similar_to", r["comparison"])

    def test_offline_review_in_hebrew(self):
        r = self.app.reviews.review_student(self.s.id, "333333", device_id="devC", lang="he")
        self.assertIn("קצרה", r["review"])

    def test_first_submitter_has_no_comparison_yet(self):
        s = self.app.sessions.start("HW2")
        self.app.reviews.submit(s.id, "111111", "A", HOMEWORK_A, "devA")
        r = self.app.reviews.review_student(s.id, "111111", device_id="devA")
        self.assertIn("first to submit", r["review"])
        self.assertEqual(r["comparison"]["unique_concepts"], [])

    def test_copy_detection(self):
        self.app.reviews.submit(self.s.id, "444444", "D", HOMEWORK_A + " Thanks.", "devD")
        o = self.app.reviews.class_overview(self.s.id)
        pairs = {(p["a"], p["b"]) for p in o["flagged_pairs"]}
        self.assertIn(("111111", "444444"), pairs)
        self.assertEqual(len(o["matrix"]), 4)

    def test_missing_concepts(self):
        cmp = SimilarityAnalyzer().compare(
            Submission(0, "s", "3", "C", HOMEWORK_SHORT, 0),
            [Submission(1, "s", "1", "A", HOMEWORK_A, 0), Submission(2, "s", "2", "B", HOMEWORK_B, 0)])
        self.assertIn("encapsulation", cmp.missing_concepts)
        self.assertIn("polymorphism", cmp.missing_concepts)

    def test_llm_review_gets_task_and_comparison(self):
        fake = FakeLLMClient("Strengths: ...")
        app = make_app(llm=fake)
        s = app.sessions.start("HW")
        app.sessions.set_homework_task(s.id, "Explain OOP")           # set once by the lecturer
        app.reviews.submit(s.id, "1", "A", HOMEWORK_A, "devA")
        app.reviews.submit(s.id, "2", "B", HOMEWORK_B, "devB")
        r = app.reviews.review_student(s.id, "1", device_id="devA")
        self.assertEqual(r["method"], "llm")
        self.assertIn("Assignment: Explain OOP", fake.calls[0][1])
        self.assertIn("classmates", fake.calls[0][1])

    def test_no_submission(self):
        self.assertCode("NO_SUBMISSION", lambda: self.app.reviews.review_student(self.s.id, "000000"))


if __name__ == "__main__":
    unittest.main()
