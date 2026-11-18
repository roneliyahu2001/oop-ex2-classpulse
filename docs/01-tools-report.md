# 1. Technical Tools Report

**Goal:** choose the simplest stack that runs a real demo in this classroom: students on phones,
one lecturer laptop, unreliable Wi‑Fi, 10 minutes of demo time.

Legend: **✔ tested** = actually run in this project (automated tests, a browser run, or the load test; last run 2026‑11‑16).
**◐ partly tested** = the logic is tested, but not on the real thing (the note says what is missing).
**○ desk review** = evaluated from documentation only. **Try these yourself before submission** if you want to cite them as tested.

## 1.1 Existing products (could we just use them?)

| Tool | Covers features | Why not alone | Status |
|---|---|---|---|
| Google Forms + Sheets | 1 (attendance), 2 | A static form link can be sent to friends at home; no rotating code; no real-time polls | ○ |
| Mentimeter / Slido | 3 (polls), 2 (Q&A) | Free-tier limits; no attendance; data sits in a third-party account | ○ |
| Kahoot | 3 | Built for quiz games, not a quick "did you understand?" | ○ |
| Zoom AI Companion / Meet "Take notes" | 4 | Needs a licence or admin rights; the assignment rules out integration | ○ |
| Moodle attendance plugin | 1 | Out of scope (no Moodle integration) | ○ |

**Conclusion:** no single tool covers features 1–5, and the most important one (cheat-resistant
attendance with a spreadsheet) is the weakest in existing tools. We build a small integrated web app
and **reuse libraries** for the hard parts (QR rendering, the LLM).

## 1.2 Building blocks

| Concern | Options considered | Choice | Status | Notes from testing |
|---|---|---|---|---|
| Language / server | Node.js + Express, Python + Flask/FastAPI, **Python standard library** (`http.server`) | Python stdlib | ✔ | Node was not installed on the dev laptop. The stdlib means `python3 run.py` works with **zero installs**. `ThreadingHTTPServer` served 200 simulated phones (see 1.4). |
| Real-time updates | WebSockets (socket.io), polling, **Server-Sent Events** | SSE | ✔ | One-way server→phone push is all we need. Built into every browser (`EventSource`), reconnects by itself, plain HTTP. A poll reached 200 listening phones in 20 ms. |
| Storage | JSON files, Firebase, **SQLite** | SQLite (`sqlite3`) | ✔ | One file, survives restarts. Constraints such as `PRIMARY KEY (session_id, student_id)` enforce "one check-in per student" even under a race. Old database files are migrated on start (tested). |
| QR code | Python `qrcode`/`segno` (pip), **qrcode-generator JS** (MIT, cdnjs) | qrcode-generator 1.4.4, vendored in `static/vendor` | ◐ | Rendered as SVG in the browser and works offline. Not yet scanned by a real phone camera from a projector. |
| Spreadsheet | Google Sheets API, openpyxl (pip), **own .xlsx writer + CSV** | `classica/xlsx.py` (about 100 lines, stdlib `zipfile`) and CSV with BOM | ◐ | The .xlsx is read back and XML-validated in the tests and opens in macOS Quick Look, with Hebrew and right-to-left sheets. Student IDs are stored as text, so a leading zero survives. Not yet opened in Microsoft Excel itself. |
| LLM | OpenAI API, local Ollama, **Anthropic Claude API** | Claude (`claude-sonnet-5-5`) over plain HTTPS | ◐ | Called with `urllib`, no SDK. Prompts and the long-lecture chunking are tested with a fake client. Not run against the real API (no key on the dev laptop). The **offline fallback** is ✔ tested, so the demo works with no key. |
| Video → text | Whisper, Zoom transcript | **Use the .vtt transcript** Zoom / Meet already export | ✔ (parser) | Avoids heavy speech-to-text on a laptop. `transcript_to_text` handles VTT, SRT and plain text. |
| Plagiarism / comparison | embeddings, MOSS, **word 3-gram Jaccard** | 3-gram Jaccard | ✔ | Deterministic and explainable. Flagged the copied answer in the tests and in the browser run. |
| Anti-cheating | static link, **rotating secret**, device binding, **location** | Rotating QR + code, one check-in per device, optional GPS circle | ✔ / ◐ | The rotating secret and device rules are ✔. The location check is ◐, see 1.3. |
| Brute-force protection | none, **rate limiting** | `RateLimiter` (sliding window) on the PIN, the check-in code and comments | ✔ | The sixth PIN guess in a minute gets HTTP 429 (integration test). |
| Languages | English only, **English + Hebrew** | Text dictionary in `static/i18n.js`, errors translated by code | ✔ | Checked in the browser in both languages, including right-to-left layout on a phone-size screen. |
| Counting people in a photo | Claude vision API (needs a key and uploads the photo), face recognition, **TensorFlow.js + COCO-SSD in the browser** | COCO-SSD lite MobileNet v2, vendored (19 MB) | ◐ | Runs offline in the lecturer's browser on WebGL; the photo is never uploaded. To find small people at the back, the photo is also scanned in 6 overlapping tiles and duplicate boxes are merged. Tried on 4 freely licensed classroom photos from Wikimedia Commons: it found most people in the front and middle rows and **missed some in the back or partly hidden** (for example 8 of about 12 in one lecture hall). It undercounts, which is why the lecturer can add or remove boxes by clicking. About 16 s the first time (loading the model), under 1 s afterwards. Not yet tried on a photo of our own class. |
| Testing | pytest, **unittest** | unittest | ✔ | 97 tests, about 1 s. |
| Reaching the phones | **same Wi‑Fi / laptop hotspot**, ngrok / Cloudflare Tunnel | LAN or hotspot; `--public-url` for a tunnel | ◐ | Tested in a browser on the same machine. Not yet tested from real phones on the campus network. The tunnel options are ○. |

## 1.3 Location check (GPS): what is and is not possible
**It is possible, with three real limits.** The feature is built and is optional per class (off / mark far students / block far students).

1. **Browsers demand HTTPS.** A phone's browser shares its location only with a secure page.
   `http://192.168.x.x:8000` on the classroom Wi‑Fi is not secure, so there the phone sends no location.
   The check therefore needs an HTTPS address: a tunnel (Cloudflare Tunnel or ngrok, both ○ desk review) or a cloud server.
   The dashboard itself works on `http://localhost`, which browsers do treat as secure, so the laptop can set the classroom point.
2. **Indoor accuracy is tens of metres.** GPS is weak inside buildings; phones fall back to Wi‑Fi positioning.
   The check answers "is the student around the building?" and not "is the student in this room?".
   That is why the radius is configurable (default 150 m) and the phone gets up to 100 m benefit of the doubt for its reported inaccuracy.
3. **A determined student can fake a location** (developer tools, mock-location apps). It raises the effort; it is not proof.

Because of limit 1 and 2 there are two modes: **mark** (everyone checks in, far or location-less students get a badge) and **block**.
Privacy: the server never stores coordinates, only the distance in metres.

Status: ◐. The distance maths, both modes and the HTTP flow are covered by tests, and the whole flow was run in a browser
with simulated coordinates (a far phone was blocked, a near one accepted). **Not tested on real phones or through a real HTTPS tunnel.**

## 1.4 Load test (measured)
`tools/simulate_class.py` plays N phones: each loads the page, checks in, keeps a live stream open, votes, and some comment and submit homework.
Run on 2026‑11‑16 on one Apple M4 laptop, with the simulator and the server on the same machine (so no real network delay is included).

| Phones | Check-in (all) | Check-in, slowest request | Poll reached all phones in | Vote, slowest |
|---|---|---|---|---|
| 30 | < 0.1 s, 30/30 | 23 ms | 7 ms | 32 ms |
| 100 | 0.1 s, 100/100 | 25 ms | 10 ms | 62 ms |
| 200 | 0.2 s, 200/200 | 36 ms | 20 ms | 128 ms |

## 1.5 Risks found while testing
- **Client isolation on campus Wi‑Fi** → mitigation: a phone hotspot or a tunnel (documented in the README and the Hebrew guide).
- **A database reset reuses poll numbers** → phones remembered "already voted" for a new poll. Fixed: votes are remembered per class and poll.
- **Names were pushed to every phone** in the first version (attendance events went to all listeners). Fixed: a separate staff channel.
- **Live streams can be held back** by some proxies and tunnels (Cloudflare's quick tunnels are documented as not supporting SSE; ○ not tried). Mitigation: the phone also re-reads the class every 15 s and whenever its screen wakes up, so polls and comments still arrive, a little later.
- **The detection library needed eval**, which the page's security policy blocks. Fixed without weakening the policy, by declaring the one global variable it was trying to create.
- **LLM latency (10–30 s)** → the UI shows a "Reviewing…" state; any error falls back to the offline result.
