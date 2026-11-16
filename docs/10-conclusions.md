# 10. Conclusions

> Fill in the measured numbers from the real class demo (the fields marked ▢).

## Results
- **All 5 features are implemented** in one web app that needs zero installs (Python standard library only; about 2,300 lines of Python, 1,400 of front-end and 1,000 of tests).
- **Attendance, the main feature,** works with a rotating QR and a typed 6-digit code (HMAC, 20 s). It enforces one check-in per student and one per phone, marks late arrivals, lets the lecturer fix the list by hand, and can check the phone's location. The lecturer gets a live table, an Excel workbook per class, a CSV and a students × classes report.
  - Demo in class: ▢ students checked in within ▢ seconds. ▢ failures, caused by ▢.
- **Polls and comments** update live over Server-Sent Events. Comments survive an offline phone thanks to a local outbox, and the lecturer can mark them answered or hide them.
- **AI features** (summary and homework review) sit behind Strategy interfaces with an offline fallback. The demo never depends on internet access or an API key. A summary can be edited and shared to the students' phones.
- **Hebrew and English**, including right-to-left screens and spreadsheets.
- **Quality:** 93 automated tests (unit and integration) run in about 1 s. Every SRS "Must" requirement traces to a class and a test (SRS section 5). A simulator played 200 phones against the server on one laptop: every check-in succeeded and a live poll reached all of them in 20 ms.

## What worked well
- **Designing first** (SRS, then classes, then tests) made the build fast. The design documents told us exactly which classes to write.
- **Vibe coding vs. find and compose:** we composed existing building blocks (the qrcode-generator library, the Claude API, SQLite, the browser's built-in EventSource and Geolocation) and wrote only the glue and domain logic.
- **Dependency injection** (clock, LLM) made "hard" behaviour easy to test, such as token expiry, late marking and LLM failure.
- **The layered design held up when the project grew.** The second round added a typed code, late marking, a location check, Excel reports, moderation, rate limits and Hebrew. Each landed in one service or one new small class, and the 48 original tests kept passing.

## What a second look found (and fixed)
Reviewing the first version critically was worth it. Three real problems came up:
1. **Privacy leak:** attendance events, with names and IDs, were pushed to every phone listening to the class. Now they go to a staff-only channel and carry only a count.
2. **The lecturer PIN could be guessed** (4 digits, unlimited tries). Now there is a rate limit.
3. **The typed address under the QR did not work** (it had no token), so a student with a broken camera was stuck. Now there is a rotating 6-digit code.

## Limitations and lessons
- The server must be reachable from the phones. Campus Wi-Fi with client isolation is the main operational risk, so a hotspot or tunnel is needed.
- **The location check is a deterrent, not proof.** It needs an HTTPS address, indoor accuracy is tens of metres, and a determined student can fake a location (tools report, 1.3).
- A device cookie can be cleared by a determined student. The same-address hint catches the simple cases on a local network.
- 3-gram similarity catches copy-paste but not paraphrasing. Embeddings would be the next step.
- An LLM grade suggestion is advice only. The lecturer stays the decision maker.
- Not yet tried on real phones, with the real Claude API, or in Microsoft Excel itself (testing strategy, 8.7).

## Future work
1. Deploy to a small cloud VM with HTTPS, so it works without the LAN and the location check works on every phone.
2. Export directly to Google Sheets (OAuth), in addition to Excel and CSV.
3. A course roster, so absent students are listed by name and not only counted.
4. Multi-course support and lecturer accounts.
