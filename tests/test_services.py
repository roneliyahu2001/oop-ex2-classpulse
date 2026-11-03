"""Unit tests per class (see docs/08-testing-strategy.md, section 3)."""
import csv
import io
import unittest

from classpulse.events import EventBus
from classpulse.llm import FakeLLMClient
from classpulse.models import DomainError
from classpulse.services.review import SimilarityAnalyzer
from classpulse.services.summary import ExtractiveSummarizer, LLMSummarizer, SummaryService
from classpulse.text_tools import transcript_to_text
from classpulse.tokens import TokenRotator
from classpulse.models import Submission

from tests.helpers import HOMEWORK_A, HOMEWORK_B, HOMEWORK_SHORT, FakeClock, make_app


def tearDownModule():
    import gc
    gc.collect()


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
        t = self.r.current("s1")
        self.clock.advance(40)
        self.assertFalse(self.r.is_valid("s1", t))

    def test_token_bound_to_session(self):
        self.assertFalse(self.r.is_valid("s2", self.r.current("s1")))

    def test_seconds_left(self):
        self.clock.t = 1005.0
        self.assertEqual(self.r.seconds_left(), 15)


class EventBusTest(unittest.TestCase):
    def test_publish_reaches_only_channel_subscribers(self):
        bus = EventBus()
        a, b = bus.subscribe("x"), bus.subscribe("y")
        bus.publish("x", "poll", {"id": 1})
        self.assertEqual(a.get_nowait(), ("poll", {"id": 1}))
        self.assertTrue(b.empty())

    def test_unsubscribe(self):
        bus = EventBus()
        q = bus.subscribe("x")
        bus.unsubscribe("x", q)
        self.assertEqual(bus.subscriber_count("x"), 0)


class SessionServiceTest(unittest.TestCase):
    def setUp(self):
        self.app = make_app()

    def test_start_and_end(self):
        s = self.app.sessions.start("  OOP 1 ")
        self.assertEqual(s.title, "OOP 1")
        self.assertTrue(s.is_active)
        self.assertFalse(self.app.sessions.end(s.id).is_active)

    def test_empty_title_rejected(self):
        with self.assertRaises(DomainError) as e:
            self.app.sessions.start("  ")
        self.assertEqual(e.exception.code, "TITLE_REQUIRED")

    def test_cannot_end_twice(self):
        s = self.app.sessions.start("x")
        self.app.sessions.end(s.id)
        with self.assertRaises(DomainError) as e:
            self.app.sessions.end(s.id)
        self.assertEqual(e.exception.code, "SESSION_CLOSED")

    def test_unknown_session(self):
        with self.assertRaises(DomainError) as e:
            self.app.sessions.get("nope")
        self.assertEqual(e.exception.status, 404)


class AttendanceServiceTest(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.app = make_app(self.clock)
        self.s = self.app.sessions.start("Lecture")
        self.tok = self.app.rotator.current(self.s.id)

    def checkin(self, sid="123456", name="Dana Levi", dev="d1", tok=None):
        return self.app.attendance.check_in(self.s.id, tok or self.tok, sid, name, dev)

    def assertCode(self, code, fn):
        with self.assertRaises(DomainError) as e:
            fn()
        self.assertEqual(e.exception.code, code)

    def test_happy_path_and_event(self):
        q = self.app.bus.subscribe(self.s.id)
        rec = self.checkin()
        self.assertEqual(rec.name, "Dana Levi")
        self.assertEqual(q.get_nowait()[0], "attendance")
        self.assertNotIn("device_id", rec.to_dict())

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
        self.clock.advance(60)
        self.assertCode("TOKEN_EXPIRED", self.checkin)

    def test_validation(self):
        self.assertCode("BAD_STUDENT_ID", lambda: self.checkin(sid="12a"))
        self.assertCode("NAME_REQUIRED", lambda: self.checkin(name="   "))

    def test_closed_session(self):
        self.app.sessions.end(self.s.id)
        self.assertCode("SESSION_CLOSED", self.checkin)

    def test_csv_export_has_bom_and_hebrew(self):
        self.checkin(name="רון אליהו")
        data = self.app.attendance.export_csv(self.s.id)
        self.assertTrue(data.startswith(b"\xef\xbb\xbf"))
        rows = list(csv.reader(io.StringIO(data.decode("utf-8-sig"))))
        self.assertEqual(rows[0][:3], ["#", "Student ID", "Name"])
        self.assertEqual(rows[1][1:3], ["123456", "רון אליהו"])


class CommentServiceTest(unittest.TestCase):
    def setUp(self):
        self.app = make_app()
        self.s = self.app.sessions.start("L")

    def test_post_anonymous_by_default(self):
        c = self.app.comments.post(self.s.id, "Can you repeat slide 4?")
        self.assertEqual(c.author, "Anonymous")

    def test_upvote_once_per_device(self):
        c = self.app.comments.post(self.s.id, "q")
        self.assertEqual(self.app.comments.upvote(c.id, "d1").upvotes, 1)
        with self.assertRaises(DomainError):
            self.app.comments.upvote(c.id, "d1")
        self.assertEqual(self.app.comments.upvote(c.id, "d2").upvotes, 2)

    def test_offline_comment_after_class_end_allowed(self):
        self.app.sessions.end(self.s.id)
        self.app.comments.post(self.s.id, "Thanks, great lecture")
        self.assertEqual(len(self.app.comments.list(self.s.id)), 1)

    def test_validation(self):
        for text in ["", "x" * 501]:
            with self.assertRaises(DomainError):
                self.app.comments.post(self.s.id, text)


class PollServiceTest(unittest.TestCase):
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
        with self.assertRaises(DomainError) as e:
            self.app.polls.vote(p.id, 1, "d1")
        self.assertEqual(e.exception.code, "ALREADY_VOTED")

    def test_new_poll_closes_previous(self):
        p1 = self.app.polls.create(self.s.id, "Q1", ["a", "b"])
        p2 = self.app.polls.create(self.s.id, "Q2", ["a", "b"])
        self.assertFalse(self.app.polls.get(p1.id).is_open)
        self.assertEqual(self.app.polls.open_poll(self.s.id).id, p2.id)

    def test_closed_poll_rejects_votes(self):
        p = self.app.polls.create(self.s.id, "Q", ["a", "b"])
        self.app.polls.close(p.id)
        with self.assertRaises(DomainError):
            self.app.polls.vote(p.id, 0, "d1")

    def test_validation(self):
        with self.assertRaises(DomainError):
            self.app.polls.create(self.s.id, "Q", ["only one"])
        with self.assertRaises(DomainError):
            self.app.polls.create(self.s.id, "Q", list("abcdefg"))
        p = self.app.polls.create(self.s.id, "Q", ["a", "b"])
        with self.assertRaises(DomainError):
            self.app.polls.vote(p.id, 5, "d1")


VTT = """WEBVTT

1
00:00:01.000 --> 00:00:04.000
<v Lecturer>Today we talk about the strategy design pattern.

2
00:00:04.000 --> 00:00:09.000
The strategy pattern lets us swap an algorithm at runtime behind a common interface.
"""


class SummaryTest(unittest.TestCase):
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

    def test_llm_summary_used_when_available(self):
        fake = FakeLLMClient("Overview: strategy pattern")
        r = SummaryService(LLMSummarizer(fake)).summarize(self.LONG)
        self.assertEqual(r["method"], "llm")
        self.assertIn("<transcript>", fake.calls[0][1])

    def test_falls_back_when_llm_fails(self):
        class Broken(LLMSummarizer):
            def summarize(self, text):
                raise ConnectionError("offline")
        r = SummaryService(Broken(FakeLLMClient())).summarize(self.LONG)
        self.assertEqual(r["method"], "extractive")
        self.assertIn("ConnectionError", r["note"])

    def test_too_short(self):
        with self.assertRaises(DomainError):
            SummaryService(None).summarize("hello world")

    def test_extractive_limits_sentences(self):
        out = ExtractiveSummarizer(sentences=2).summarize(self.LONG)
        self.assertEqual(out.count("\n- "), 2)


class ReviewTest(unittest.TestCase):
    def setUp(self):
        self.app = make_app()
        self.s = self.app.sessions.start("HW")
        sub = self.app.reviews.submit
        sub(self.s.id, "111111", "A", HOMEWORK_A)
        sub(self.s.id, "222222", "B", HOMEWORK_B)
        sub(self.s.id, "333333", "C", HOMEWORK_SHORT)

    def test_resubmission_replaces(self):
        self.app.reviews.submit(self.s.id, "111111", "A", HOMEWORK_B)
        self.assertEqual(len(self.app.repo.list_submissions(self.s.id)), 3)

    def test_short_submission_rejected(self):
        with self.assertRaises(DomainError):
            self.app.reviews.submit(self.s.id, "9", "x", "too short")

    def test_student_view_hides_identities(self):
        r = self.app.reviews.review_student(self.s.id, "333333")
        self.assertNotIn("most_similar_to", r["comparison"])
        self.assertEqual(r["method"], "heuristic")
        self.assertIn("short", r["review"])

    def test_lecturer_view_shows_identities(self):
        r = self.app.reviews.review_student(self.s.id, "111111", lecturer=True)
        self.assertIn("most_similar_to", r["comparison"])

    def test_copy_detection(self):
        self.app.reviews.submit(self.s.id, "444444", "D", HOMEWORK_A + " Thanks.")
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

    def test_llm_review_gets_comparison_in_prompt(self):
        fake = FakeLLMClient("Strengths: ...")
        app = make_app(llm=fake)
        s = app.sessions.start("HW")
        app.reviews.submit(s.id, "1", "A", HOMEWORK_A)
        app.reviews.submit(s.id, "2", "B", HOMEWORK_B)
        r = app.reviews.review_student(s.id, "1", task="Explain OOP")
        self.assertEqual(r["method"], "llm")
        self.assertIn("Explain OOP", fake.calls[0][1])
        self.assertIn("classmates", fake.calls[0][1])

    def test_no_submission(self):
        with self.assertRaises(DomainError) as e:
            self.app.reviews.review_student(self.s.id, "000000")
        self.assertEqual(e.exception.code, "NO_SUBMISSION")


if __name__ == "__main__":
    unittest.main()
