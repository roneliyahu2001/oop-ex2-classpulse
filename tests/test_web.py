"""Integration tests: real HTTP server on a random port, real SQLite (in memory)."""
import http.cookiejar
import json
import threading
import unittest
import urllib.error
import urllib.request

from classica.web import make_server
from tests.helpers import CLASSROOM, FAR, HOMEWORK_A, HOMEWORK_B, NEAR, close_apps, make_app
from tools.simulate_class import simulate


class Client:
    """One browser = one cookie jar (so one device id). Loading the page sets the cookie."""

    def __init__(self, base):
        self.base = base
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.call("GET", "/")

    def call(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with self.opener.open(req, timeout=5) as r:
                raw = r.read()
                self.headers = r.headers
                return r.status, (json.loads(raw) if "json" in r.headers.get("Content-Type", "") else raw)
        except urllib.error.HTTPError as e:
            with e:
                return e.code, json.loads(e.read())


class WebTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = make_app()
        cls.srv = make_server(cls.app, host="127.0.0.1", port=0, quiet=True)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        close_apps()

    def lecturer(self):
        c = Client(self.base)
        self.assertEqual(c.call("POST", "/api/login", {"pin": "1234"})[0], 200)
        return c

    def new_class(self, lect, title="OOP demo"):
        st, s = lect.call("POST", "/api/sessions", {"title": title})
        self.assertEqual(st, 201)
        return s["id"]

    def token(self, lect, sid):
        return lect.call("GET", f"/api/sessions/{sid}/qr")[1]["url"].split("&t=")[1]

    def test_pages_served(self):
        c = Client(self.base)
        for path in ["/", "/lecturer", "/static/style.css", "/static/i18n.js", "/static/vendor/qrcode.min.js"]:
            self.assertEqual(c.call("GET", path)[0], 200, path)
        self.assertEqual(c.call("GET", "/static/../classica/app.py")[0], 404)
        self.assertEqual(c.call("GET", "/static/../run.py")[0], 404)

    def test_page_sets_device_cookie_and_security_headers(self):
        req = urllib.request.urlopen(self.base + "/", timeout=5)
        with req:
            self.assertIn("ca_dev=", req.headers["Set-Cookie"])
            self.assertIn("HttpOnly", req.headers["Set-Cookie"])
            self.assertIn("default-src 'self'", req.headers["Content-Security-Policy"])
            self.assertEqual(req.headers["X-Content-Type-Options"], "nosniff")

    def test_lecturer_endpoints_protected(self):
        c = Client(self.base)
        for method, path in [("POST", "/api/sessions"), ("GET", "/api/sessions"),
                             ("GET", "/api/course/attendance"), ("GET", "/api/course/attendance.xlsx"),
                             ("POST", "/api/summary"), ("POST", "/api/comments/1/moderate"),
                             ("GET", "/api/sessions/x/attendance"), ("GET", "/api/sessions/x/report.xlsx"),
                             ("POST", "/api/sessions/x/geofence"), ("POST", "/api/sessions/x/attendance")]:
            self.assertEqual(c.call(method, path, {} if method == "POST" else None)[0], 401, path)

    def test_pin_cannot_be_guessed_by_brute_force(self):
        c = Client(self.base)
        try:
            codes = [c.call("POST", "/api/login", {"pin": f"{i:04d}"})[0] for i in range(7)]
            self.assertEqual(codes, [401] * 5 + [429] * 2)
            self.assertEqual(c.call("POST", "/api/login", {"pin": "1234"})[0], 429)   # even the right one waits
        finally:
            self.app.login_limiter.reset("ip:127.0.0.1")

    def test_full_class_flow(self):
        lect = self.lecturer()
        sid = self.new_class(lect)
        token = self.token(lect, sid)

        dana, yossi = Client(self.base), Client(self.base)
        st, rec = dana.call("POST", "/api/checkin", {"session_id": sid, "token": token,
                                                    "student_id": "123456", "name": "Dana"})
        self.assertEqual((st, rec["status"], rec["method"]), (201, "on_time", "qr"))
        # Dana tries to check in her friend from the same phone
        st, err = dana.call("POST", "/api/checkin", {"session_id": sid, "token": token,
                                                    "student_id": "999999", "name": "Friend"})
        self.assertEqual((st, err["error"]), (409, "DEVICE_USED"))
        self.assertEqual(yossi.call("POST", "/api/checkin", {"session_id": sid, "token": "bad",
                                                            "student_id": "222222", "name": "Y"})[0], 403)
        # Yossi's camera is broken: he types the 6-digit code from the screen
        code = lect.call("GET", f"/api/sessions/{sid}/qr")[1]["code"]
        st, rec = yossi.call("POST", "/api/checkin", {"session_id": sid, "token": f"{code[:3]} {code[3:]}",
                                                     "student_id": "222222", "name": "Yossi"})
        self.assertEqual((st, rec["method"]), (201, "code"))
        self.assertIsNotNone(yossi.call("GET", "/api/active")[1]["session"])

        # the lecturer fixes the list by hand
        self.assertEqual(lect.call("POST", f"/api/sessions/{sid}/attendance",
                                   {"student_id": "333333", "name": "No Phone"})[0], 201)
        st, rows = lect.call("GET", f"/api/sessions/{sid}/attendance")
        self.assertEqual([(r["student_id"], r["method"]) for r in rows],
                         [("123456", "qr"), ("222222", "code"), ("333333", "manual")])
        self.assertNotIn("ip", rows[0])
        self.assertEqual(lect.call("POST", f"/api/sessions/{sid}/attendance/333333/remove")[0], 200)
        self.assertEqual(dana.call("POST", f"/api/sessions/{sid}/attendance/222222/remove")[0], 401)

        # spreadsheets
        st, csv_bytes = lect.call("GET", f"/api/sessions/{sid}/attendance.csv")
        self.assertIn("Dana", csv_bytes.decode("utf-8-sig"))
        self.assertIn("attachment", lect.headers["Content-Disposition"])
        st, xlsx = lect.call("GET", f"/api/sessions/{sid}/report.xlsx?lang=he")
        self.assertEqual((st, xlsx[:2]), (200, b"PK"))
        st, xlsx = lect.call("GET", "/api/course/attendance.xlsx")
        self.assertEqual((st, xlsx[:2]), (200, b"PK"))
        st, matrix = lect.call("GET", "/api/course/attendance")
        self.assertIn("123456", [s["student_id"] for s in matrix["students"]])

        # poll
        st, poll = lect.call("POST", f"/api/sessions/{sid}/polls", {"question": "Clear?", "options": ["Yes", "No"]})
        self.assertEqual(st, 201)
        self.assertEqual(dana.call("GET", f"/api/sessions/{sid}")[1]["poll"]["id"], poll["id"])
        dana.call("POST", f"/api/polls/{poll['id']}/vote", {"option": 0})
        st, p = yossi.call("POST", f"/api/polls/{poll['id']}/vote", {"option": 1})
        self.assertEqual(p["votes"], [1, 1])
        self.assertEqual(dana.call("POST", f"/api/polls/{poll['id']}/vote", {"option": 1})[0], 409)
        self.assertEqual(Client(self.base).call("POST", f"/api/polls/{poll['id']}/vote", {"option": "0"})[0], 400)
        self.assertEqual(dana.call("POST", f"/api/polls/{poll['id']}/close")[0], 401)

        # comments and moderation
        st, c = dana.call("POST", f"/api/sessions/{sid}/comments", {"text": "Slower please"})
        self.assertEqual(yossi.call("POST", f"/api/comments/{c['id']}/upvote")[1]["upvotes"], 1)
        self.assertEqual(dana.call("POST", f"/api/comments/{c['id']}/moderate", {"hidden": True})[0], 401)
        self.assertTrue(lect.call("POST", f"/api/comments/{c['id']}/moderate", {"hidden": True})[1]["hidden"])
        self.assertEqual(dana.call("GET", f"/api/sessions/{sid}/comments")[1], [])
        self.assertEqual(len(lect.call("GET", f"/api/sessions/{sid}/comments")[1]), 1)

        # homework: the task comes from the lecturer, and a review is private
        lect.call("POST", f"/api/sessions/{sid}/homework-task", {"task": "Explain OOP"})
        self.assertEqual(dana.call("GET", f"/api/sessions/{sid}")[1]["session"]["homework_task"], "Explain OOP")
        dana.call("POST", f"/api/sessions/{sid}/homework", {"student_id": "123456", "name": "Dana", "text": HOMEWORK_A})
        yossi.call("POST", f"/api/sessions/{sid}/homework", {"student_id": "222222", "name": "Y", "text": HOMEWORK_B})
        st, r = dana.call("POST", f"/api/sessions/{sid}/homework/123456/review", {"lang": "he"})
        self.assertEqual(st, 200)
        self.assertNotIn("most_similar_to", r["comparison"])
        self.assertEqual(yossi.call("POST", f"/api/sessions/{sid}/homework/123456/review", {})[0], 403)
        self.assertEqual(yossi.call("POST", f"/api/sessions/{sid}/homework",
                                    {"student_id": "123456", "name": "Y", "text": HOMEWORK_B})[0], 409)
        self.assertIn("most_similar_to", lect.call("POST", f"/api/sessions/{sid}/homework/123456/review", {})[1]["comparison"])
        st, o = lect.call("GET", f"/api/sessions/{sid}/homework")
        self.assertEqual(len(o["students"]), 2)
        self.assertEqual(lect.call("POST", f"/api/sessions/{sid}/homework/222222/delete")[0], 200)

        # end class
        self.assertFalse(lect.call("POST", f"/api/sessions/{sid}/end")[1]["is_active"])
        self.assertEqual(lect.call("GET", f"/api/sessions/{sid}/qr")[0], 409)

    def test_summary_is_saved_as_a_draft_then_shared(self):
        lect, student = self.lecturer(), Client(self.base)
        sid = self.new_class(lect, "summary")
        text = "Inheritance and composition are two ways to reuse code in object oriented design. " * 5
        st, r = lect.call("POST", "/api/summary", {"transcript": text, "session_id": sid})
        self.assertEqual((st, r["method"]), (200, "extractive"))
        self.assertEqual(student.call("GET", f"/api/sessions/{sid}")[1]["session"]["summary"], "")
        st, s = lect.call("POST", f"/api/sessions/{sid}/summary", {"summary": "Edited summary", "published": True})
        self.assertTrue(s["summary_published"])
        self.assertEqual(student.call("GET", f"/api/sessions/{sid}")[1]["session"]["summary"], "Edited summary")
        lect.call("POST", f"/api/sessions/{sid}/end")

    def test_location_check_over_http(self):
        lect, far, near, silent = self.lecturer(), Client(self.base), Client(self.base), Client(self.base)
        sid = self.new_class(lect, "geo")
        st, s = lect.call("POST", f"/api/sessions/{sid}/geofence",
                          {"mode": "block", "lat": CLASSROOM[0], "lon": CLASSROOM[1], "radius": 150})
        self.assertEqual((st, s["geo_mode"], s["geo_lat"]), (200, "block", CLASSROOM[0]))
        public = far.call("GET", f"/api/sessions/{sid}")[1]["session"]
        self.assertEqual(public["geo_mode"], "block")
        self.assertNotIn("geo_lat", public)

        def checkin(client, student_id, where=None):
            body = {"session_id": sid, "token": self.token(lect, sid), "student_id": student_id, "name": "S"}
            if where:
                body.update(lat=where[0], lon=where[1], accuracy=15)
            return client.call("POST", "/api/checkin", body)

        self.assertEqual(checkin(silent, "111111")[1]["error"], "LOCATION_REQUIRED")
        self.assertEqual(checkin(far, "222222", FAR)[1]["error"], "TOO_FAR")
        st, rec = checkin(near, "333333", NEAR)
        self.assertEqual((st, rec["geo"]), (201, "ok"))
        self.assertEqual(lect.call("POST", f"/api/sessions/{sid}/geofence", {"mode": "block"})[0], 400)
        self.assertEqual(lect.call("POST", f"/api/sessions/{sid}/geofence", {"mode": "off"})[1]["geo_mode"], "off")
        self.assertEqual(checkin(silent, "111111")[0], 201)
        lect.call("POST", f"/api/sessions/{sid}/end")

    def test_head_count_over_http(self):
        lect, student = self.lecturer(), Client(self.base)
        sid = self.new_class(lect, "headcount")
        self.assertEqual(student.call("POST", f"/api/sessions/{sid}/headcount", {"count": 3})[0], 401)
        st, s = lect.call("POST", f"/api/sessions/{sid}/headcount", {"count": 24})
        self.assertEqual((st, s["headcount"]), (200, 24))
        for bad in [-5, 2.5, "24", True]:
            self.assertEqual(lect.call("POST", f"/api/sessions/{sid}/headcount", {"count": bad})[0], 400, bad)
        self.assertIsNone(lect.call("POST", f"/api/sessions/{sid}/headcount", {"count": None})[1]["headcount"])
        self.assertNotIn("headcount", student.call("GET", f"/api/sessions/{sid}")[1]["session"])
        lect.call("POST", f"/api/sessions/{sid}/end")

    def test_detection_model_is_served_and_cached(self):
        c = Client(self.base)
        for path in ["/static/vendor/tfjs/tf.min.js", "/static/vendor/tfjs/coco-ssd.min.js",
                     "/static/vendor/tfjs/ssdlite/model.json", "/static/vendor/tfjs/ssdlite/group1-shard5of5",
                     "/static/headcount.js"]:
            self.assertEqual(c.call("GET", path)[0], 200, path)
        self.assertEqual(c.headers["Cache-Control"], "no-store")                 # our own code: always fresh
        c.call("GET", "/static/vendor/tfjs/ssdlite/model.json")
        self.assertEqual(c.headers["Cache-Control"], "max-age=86400")

    def test_comment_flood_is_slowed_down(self):
        lect, spammer, other = self.lecturer(), Client(self.base), Client(self.base)
        sid = self.new_class(lect, "spam")
        codes = [spammer.call("POST", f"/api/sessions/{sid}/comments", {"text": f"spam {i}"})[0] for i in range(6)]
        self.assertEqual(codes, [201] * 5 + [429])
        self.assertEqual(other.call("POST", f"/api/sessions/{sid}/comments", {"text": "a real question"})[0], 201)
        lect.call("POST", f"/api/sessions/{sid}/end")

    def test_bad_requests(self):
        def post(path, data, headers=None):
            req = urllib.request.Request(self.base + path, data=data, method="POST", headers=headers or {})
            try:
                with urllib.request.urlopen(req, timeout=5) as r:
                    return r.status
            except urllib.error.HTTPError as e:
                with e:
                    return e.code
        self.assertEqual(post("/api/sessions/zzz/comments", b"{not json"), 400)
        self.assertEqual(post("/api/sessions/zzz/comments", b"[1, 2]"), 400)
        self.assertEqual(post("/api/sessions/zzz/comments", b'{"text": "hi"}'), 404)
        self.assertEqual(post("/api/nothing", b"{}"), 404)

    def test_live_stream_keeps_names_away_from_students(self):
        lect = self.lecturer()
        sid = self.new_class(lect, "sse")
        student = Client(self.base)
        student_stream = student.opener.open(self.base + f"/api/sessions/{sid}/events", timeout=5)
        staff_stream = lect.opener.open(self.base + f"/api/sessions/{sid}/events", timeout=5)
        try:
            for stream in (student_stream, staff_stream):
                self.assertEqual(stream.readline(), b"event: hello\n")
                stream.readline(); stream.readline()
            student.call("POST", "/api/checkin", {"session_id": sid, "token": self.token(lect, sid),
                                                  "student_id": "123456", "name": "Dana"})
            student.call("POST", f"/api/sessions/{sid}/comments", {"text": "hi"})
            # The dashboard hears about the check-in (a count, no names); the phone only gets the comment.
            self.assertEqual(staff_stream.readline(), b"event: attendance\n")
            self.assertEqual(json.loads(staff_stream.readline()[len(b"data: "):]), {"count": 1})
            self.assertEqual(student_stream.readline(), b"event: comment\n")
            self.assertIn(b'"text": "hi"', student_stream.readline())
        finally:
            student_stream.close()
            staff_stream.close()
            lect.call("POST", f"/api/sessions/{sid}/end")

    def test_simulated_class_of_phones(self):
        lect = self.lecturer()
        sid = self.new_class(lect, "simulated")
        r = simulate(self.base, "1234", students=12, session_id=sid, homework=3, seed=1, out=lambda *a: None)
        self.assertEqual((r["checked_in"], r["poll_reached"], r["votes"], r["homework"]), (12, 12, 12, 3))
        self.assertGreaterEqual(r["comments"], 1)
        self.assertEqual(len(lect.call("GET", f"/api/sessions/{sid}/attendance")[1]), 12)
        lect.call("POST", f"/api/sessions/{sid}/end")


if __name__ == "__main__":
    unittest.main()
