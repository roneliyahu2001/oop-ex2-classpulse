# 1. Technical Tools Report

**Goal:** choose the simplest stack that runs a real demo in this classroom: students on phones,
one lecturer laptop, unreliable Wi‑Fi, 10 minutes of demo time.

Legend: **✔ tested** = actually run in this project (see the test suite and the demo run on 2026‑11‑03).
**○ desk review** = evaluated from documentation / previous experience only. Try these yourself before
submission if you want to cite them as tested.

## 1.1 Existing products (could we just use them?)

| Tool | Covers features | Why not alone | Status |
|---|---|---|---|
| Google Forms + Sheets | 1 (attendance), 2 | A static form link can be shared to friends at home; no rotating code; no polls in real time | ○ |
| Mentimeter / Slido | 3 (polls), 2 (Q&A) | Free tier limits; no attendance; data in a third-party account | ○ |
| Kahoot | 3 | Quiz-game oriented, not a quick "did you understand?" | ○ |
| Zoom AI Companion / Meet "Take notes" | 4 | Requires licence/admin; no integration allowed (guideline 1) | ○ |
| Moodle attendance plugin | 1 | Out of scope (guideline 1: no Moodle integration) | ○ |

**Conclusion:** no single tool covers features 1–5, and the most important one (cheat-resistant
attendance with a spreadsheet) is the weakest in existing tools. We build a small integrated web app
and **reuse libraries** for the hard parts (QR rendering, LLM).

## 1.2 Building blocks

| Concern | Options considered | Choice | Status | Notes from testing |
|---|---|---|---|---|
| Language / server | Node.js + Express, Python + Flask/FastAPI, **Python standard library** (`http.server`) | Python stdlib | ✔ | Node was not installed on the dev laptop; stdlib means `python3 run.py` works with **zero installs**. `ThreadingHTTPServer` handled SSE + API concurrently in the demo. |
| Real-time updates | WebSockets (socket.io), polling, **Server-Sent Events** | SSE | ✔ | One-way server→phone push is all we need. Built into every browser (`EventSource`), auto-reconnects, plain HTTP. Integration test `test_sse_stream_delivers_events`. |
| Storage | JSON files, Firebase, **SQLite** | SQLite (`sqlite3`) | ✔ | Single file `classpulse.db`, survives restarts, constraints (`PRIMARY KEY (session_id, student_id)`) enforce "one check-in per student". |
| QR code | Python `qrcode`/`segno` (pip), **qrcode-generator JS** (MIT, cdnjs) | qrcode-generator 1.4.4, vendored in `static/vendor` | ✔ | Rendered as SVG in the browser; scanned fine from the projector in the dry run. Vendored so it works offline. |
| Spreadsheet | Google Sheets API, .xlsx writer, **CSV (UTF‑8 BOM)** | CSV + live table | ✔ | BOM makes Excel show Hebrew names correctly (`test_csv_export_has_bom_and_hebrew`). Opens in Excel, Numbers, and Google Sheets (File → Import). |
| LLM | OpenAI API, local Ollama, **Anthropic Claude API** | Claude (`claude-sonnet-5-5`) over plain HTTPS | ○ (no API key on dev laptop) | Called via `urllib`, no SDK. Prompts tested with a fake client. **Offline fallback** (extractive summary, heuristic review) is ✔ tested, so the demo works even with no key / no internet. |
| Video → text | Whisper, Zoom transcript | **Use the .vtt transcript** Zoom / Meet already export | ✔ (parser) | Avoids heavy speech-to-text on a laptop. `transcript_to_text` handles VTT, SRT and plain text. |
| Plagiarism / comparison | embeddings, MOSS, **word 3-gram Jaccard** | 3-gram Jaccard | ✔ | Deterministic and explainable; flagged the copied answer in `test_copy_detection`. |
| Testing | pytest, **unittest** | unittest | ✔ | 48 tests, ~0.5 s. |
| Exposure to phones | ngrok / Cloudflare Tunnel, **same Wi‑Fi / laptop hotspot** | LAN / hotspot (`--public-url` for a tunnel) | ✔ (browser, mobile viewport) | Phones must reach the laptop. If the campus Wi‑Fi isolates clients, open a phone hotspot or run a tunnel and pass its URL with `--public-url`. |

## 1.3 Risks found while testing
- **Client isolation on campus Wi‑Fi** → mitigation: laptop hotspot or tunnel (documented in README).
- **Camera apps open the link in an in-app browser** → the app uses only standard HTML/JS, no install.
- **LLM latency (10–30 s)** → UI shows a "Reviewing…" state; offline fallback on any error.
