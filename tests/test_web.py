"""Integration tests: real HTTP server on a random port, real SQLite (in memory)."""
import http.cookiejar
import json
import threading
import unittest
import urllib.error
import urllib.request

from classpulse.web import make_server
from tests.helpers import HOMEWORK_A, HOMEWORK_B, make_app


class Client:
    """One browser = one cookie jar (so one device id)."""

    def __init__(self, base):
        self.base = base
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def call(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with self.opener.open(req, timeout=5) as r:
                raw = r.read()
                ctype = r.headers.get("Content-Type", "")
                return r.status, (json.loads(raw) if "json" in ctype else raw)
        except urllib.error.HTTPError as e:
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
        cls.app.repo.close()

    def lecturer(self):
        c = Client(self.base)
        self.assertEqual(c.call("POST", "/api/login", {"pin": "1234"})[0], 200)
        return c

    def test_pages_served(self):
        c = Client(self.base)
        for path in ["/", "/lecturer", "/static/style.css", "/static/vendor/qrcode.min.js"]:
            self.assertEqual(c.call("GET", path)[0], 200, path)
        self.assertEqual(c.call("GET", "/static/../classpulse/app.py")[0], 404)

    def test_lecturer_endpoints_protected(self):
        c = Client(self.base)
        self.assertEqual(c.call("POST", "/api/sessions", {"title": "x"})[0], 401)
        self.assertEqual(c.call("POST", "/api/login", {"pin": "0000"})[0], 401)

    def test_full_class_flow(self):
        lect = self.lecturer()
        st, s = lect.call("POST", "/api/sessions", {"title": "OOP demo"})
        self.assertEqual(st, 201)
        sid = s["id"]

        st, qr = lect.call("GET", f"/api/sessions/{sid}/qr")
        token = qr["url"].split("&t=")[1]

        dana, yossi = Client(self.base), Client(self.base)
        st, rec = dana.call("POST", "/api/checkin", {"session_id": sid, "token": token,
                                                    "student_id": "123456", "name": "Dana"})
        self.assertEqual(st, 201)
        # Dana tries to check in her friend from the same phone
        st, err = dana.call("POST", "/api/checkin", {"session_id": sid, "token": token,
                                                    "student_id": "999999", "name": "Friend"})
        self.assertEqual((st, err["error"]), (409, "DEVICE_USED"))
        self.assertEqual(yossi.call("POST", "/api/checkin", {"session_id": sid, "token": "bad",
                                                            "student_id": "222222", "name": "Y"})[0], 403)

        st, rows = lect.call("GET", f"/api/sessions/{sid}/attendance")
        self.assertEqual([r["student_id"] for r in rows], ["123456"])
        st, csv_bytes = lect.call("GET", f"/api/sessions/{sid}/attendance.csv")
        self.assertIn("Dana", csv_bytes.decode("utf-8-sig"))

        # poll
        st, poll = lect.call("POST", f"/api/sessions/{sid}/polls", {"question": "Clear?", "options": ["Yes", "No"]})
        self.assertEqual(st, 201)
        self.assertEqual(dana.call("GET", f"/api/sessions/{sid}")[1]["poll"]["id"], poll["id"])
        dana.call("POST", f"/api/polls/{poll['id']}/vote", {"option": 0})
        st, p = yossi.call("POST", f"/api/polls/{poll['id']}/vote", {"option": 1})
        self.assertEqual(p["votes"], [1, 1])
        self.assertEqual(dana.call("POST", f"/api/polls/{poll['id']}/vote", {"option": 1})[0], 409)

        # comments
        st, c = dana.call("POST", f"/api/sessions/{sid}/comments", {"text": "Slower please"})
        self.assertEqual(yossi.call("POST", f"/api/comments/{c['id']}/upvote")[1]["upvotes"], 1)

        # homework
        dana.call("POST", f"/api/sessions/{sid}/homework", {"student_id": "123456", "name": "Dana", "text": HOMEWORK_A})
        yossi.call("POST", f"/api/sessions/{sid}/homework", {"student_id": "222222", "name": "Y", "text": HOMEWORK_B})
        st, r = dana.call("POST", f"/api/sessions/{sid}/homework/123456/review", {})
        self.assertEqual(st, 200)
        self.assertNotIn("most_similar_to", r["comparison"])
        st, o = lect.call("GET", f"/api/sessions/{sid}/homework")
        self.assertEqual(len(o["students"]), 2)

        # end class
        self.assertFalse(lect.call("POST", f"/api/sessions/{sid}/end")[1]["is_active"])
        self.assertEqual(lect.call("GET", f"/api/sessions/{sid}/qr")[0], 409)

    def test_summary_endpoint(self):
        lect = self.lecturer()
        text = "Inheritance and composition are two ways to reuse code in object oriented design. " * 5
        st, r = lect.call("POST", "/api/summary", {"transcript": text})
        self.assertEqual((st, r["method"]), (200, "extractive"))

    def test_bad_json(self):
        req = urllib.request.Request(self.base + "/api/checkin", data=b"{not json", method="POST")
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(e.exception.code, 400)

    def test_sse_stream_delivers_events(self):
        lect = self.lecturer()
        sid = lect.call("POST", "/api/sessions", {"title": "sse"})[1]["id"]
        resp = urllib.request.urlopen(self.base + f"/api/sessions/{sid}/events", timeout=5)
        self.assertEqual(resp.readline(), b"event: hello\n")
        resp.readline(); resp.readline()
        Client(self.base).call("POST", f"/api/sessions/{sid}/comments", {"text": "hi"})
        self.assertEqual(resp.readline(), b"event: comment\n")
        self.assertIn(b'"text": "hi"', resp.readline())
        resp.close()


if __name__ == "__main__":
    unittest.main()
