# 10. Conclusions

> Fill in the measured numbers from the real class demo (the fields marked ▢).

## Results
- **All 5 features are implemented** in one web app that needs zero installs (Python standard library only, about 2,000 lines including the front-end).
- **Attendance, the main feature,** works with a rotating QR (HMAC token, 20 s) and enforces one check-in per student and one per phone. The lecturer gets a live table and an Excel-ready CSV.
  - Demo in class: ▢ students checked in within ▢ seconds. ▢ failures, caused by ▢.
- **Polls and comments** update live over Server-Sent Events. Comments survive an offline phone thanks to a local outbox.
- **AI features** (summary and homework review) sit behind Strategy interfaces with an offline fallback. The demo never depends on internet access or an API key.
- **Quality:** 48 automated tests (unit and integration) run in about 0.5 s. Every SRS "Must" requirement traces to a class and a test (SRS section 5).

## What worked well
- **Designing first** (SRS, then classes, then tests) made the build fast. The design documents told us exactly which classes to write.
- **Vibe coding vs. find and compose:** we composed existing building blocks (the qrcode-generator library, the Claude API, SQLite, the browser's built-in EventSource) and wrote only the glue and domain logic.
- **Dependency injection** (clock, LLM) made "hard" behaviour easy to test, such as token expiry and LLM failure.

## Limitations and lessons
- The server must be reachable from the phones. Campus Wi-Fi with client isolation is the main operational risk, so a hotspot or tunnel is needed.
- A device cookie can be cleared by a determined student. Stronger options (geofencing, a per-student secret) were left out on purpose to keep the app simple and avoid collecting personal data.
- 3-gram similarity catches copy-paste but not paraphrasing. Embeddings would be the next step.
- An LLM grade suggestion is advice only. The lecturer stays the decision maker.

## Future work
1. Export directly to Google Sheets (OAuth), in addition to CSV.
2. Deploy to a small cloud VM with HTTPS so it works without the LAN.
3. An automated load test with 100 simulated phones.
4. Multi-course support and lecturer accounts.
