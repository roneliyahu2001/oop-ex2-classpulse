# 8. Testing Strategy

## 8.1 Goals
1. The **main feature (attendance)** must never fail in class, so it has the most tests, especially the anti-cheating rules.
2. Every class in the class diagrams (section 6) has unit tests, or is covered by integration tests where it is pure glue.
3. The tests are fast (about 1 s) and need no network and no API key, so they run before every commit and right before the demo.
4. What was **not** tested is written down (8.7), so nobody mistakes it for tested.

## 8.2 Test levels
| Level | What | Tooling | Where |
|---|---|---|---|
| Unit | One class, with collaborators replaced by fakes (`FakeClock`, `FakeLLMClient`, in-memory SQLite) | `unittest` | `tests/test_services.py` (84 tests) |
| Integration | A real `ThreadingHTTPServer` on a random port, real HTTP, cookies (one cookie jar per simulated phone), real SSE streams | `unittest` + `urllib` | `tests/test_web.py` (13 tests) |
| Load / rehearsal | N simulated phones against a running server, with timings | `tools/simulate_class.py` | Results in the tools report, 1.4 |
| System / manual | The full flow in a browser: desktop dashboard plus a phone-size viewport, in Hebrew and English | Browser, real phones | Checklist in 8.6 |
| Acceptance | The live demo against the SoW acceptance criteria | Real class | `docs/09-demo-script.md` |

Run them all with:
```bash
python3 -m unittest discover -s tests -t .
```
Current result: **97 tests, all passing, about 1.2 s.**
A ready GitHub Actions workflow is kept in `ci/github-actions-tests.yml`. It runs the same command on Python 3.10 and 3.13. It is **not active yet**: to turn it on, add it on the GitHub website as `.github/workflows/tests.yml`.

## 8.3 Unit tests per class (maps to the class diagrams)
| Class | Technique | Test cases |
|---|---|---|
| `TokenRotator` | Inject `FakeClock`, boundary values | valid now; valid in the previous window (+20 s); token and code invalid after 2 windows (+40 s); bound to its session; `seconds_left`; the 6-digit code and `match` tell QR from typed code; garbage and non-ASCII input is rejected without crashing |
| `RateLimiter` | Boundary values with `FakeClock` | blocks after the limit; keys are independent; the window slides at exactly 60 s; `reset` |
| `GeoFence`, `haversine_m` | Known distances | one degree of latitude ≈ 111.2 km; inside and outside the circle; the accuracy credit helps a near phone and is capped at 100 m for a far one; invalid coordinates |
| `EventBus` | State | publish reaches only that channel's subscribers; one queue follows two channels (public + staff); unsubscribe |
| `Repository` | Migration test on a real file, plus constraints through the services | a version-1 database file is upgraded and readable; uniqueness constraints (attendance, vote, upvote, submission) |
| `SessionService` | Equivalence classes | head count saved, hidden from students, cleared with `None`, out-of-range rejected; start trims the title; empty title is rejected; can't end twice; unknown ID gives 404; `active()` is the newest open class; a summary is a draft until published and an empty one can't be published; homework task; geofence validation, radius clamping, coordinates hidden from students |
| `AttendanceService` | Decision table (token × session × duplicate student × duplicate device × location mode) | happy path; names only on the staff channel; re-scan is idempotent; same student on another device; one device for two students; expired token; typed code; late after 15 minutes; invalid ID or name; closed session; manual add and remove; shared-address hint; CSV BOM, Hebrew headers and formula escaping; location off / block (far, missing, invalid, near) / mark (far, none, ok); manual add bypasses the location check |
| `CommentService` | Equivalence and boundary (0 and 501 chars) | anonymous by default; one upvote per device; posting after the class ends; answered and hidden flags are independent; a hidden comment is not listed and can't be upvoted |
| `PollService` | State machine (open → closed) | vote counts; one vote per device; a new poll closes the old one; closed poll rejects votes; 1 or 7 options rejected; bad option index (too high, negative) |
| `Workbook` | Round trip: write, unzip, parse every XML part | column letters up to AAA; Hebrew, `<&>"` and empty cells survive; IDs stay text and numbers stay numbers; illegal sheet names are fixed and made unique; right-to-left flag |
| `ReportService` | Fixture of two classes a week apart | course matrix (marks, counts, percentages, latest name wins, head count); course workbook rows; session workbook has four sheets (overview with check-ins vs. head count), omits hidden comments, Hebrew sheet names |
| `text_tools` | Example-based | VTT timestamps and `<v>` tags removed; `split_chunks` respects the size and loses no words |
| `SummaryService`, `ExtractiveSummarizer`, `LLMSummarizer` | Strategy substitution, fault injection | offline summary (English and Hebrew labels); LLM used when present (one call); a long lecture makes n + 1 calls; **fallback when the LLM raises**; too short; sentence limit |
| `ReviewService`, `SimilarityAnalyzer`, `HeuristicReviewer`, `LLMReviewer` | Fixture texts (good, different, short, copied) | resubmit from the same phone replaces and notifies the dashboard; another phone can't overwrite until the lecturer deletes; too short; student view hides identities; a student can't read someone else's review; lecturer view shows identities; Hebrew offline review; first submitter gets no comparison; copy detection flags the pair; missing concepts found; the LLM prompt contains the lecturer's task and the comparison; no submission gives 404 |
| `AnthropicClient` | Not unit-tested (it calls an external API) | Covered by a manual smoke test with a real key (8.6) |

## 8.4 Integration tests (`tests/test_web.py`)
| Test | What it proves |
|---|---|
| `test_pages_served` | Pages and static files load; path traversal gives 404 |
| `test_page_sets_device_cookie_and_security_headers` | The device cookie is HttpOnly; CSP and nosniff headers are present |
| `test_lecturer_endpoints_protected` | Ten lecturer-only endpoints answer 401 without the PIN cookie |
| `test_pin_cannot_be_guessed_by_brute_force` | Five wrong PINs, then 429 even for the right one |
| `test_full_class_flow` | Check-in by QR and by typed code; friend check-in blocked; manual add and remove; CSV, Excel and course report; poll, vote, double vote, bad vote; comment, upvote, hide; homework task, submit, private review, overwrite blocked, lecturer review and delete; end of class |
| `test_summary_is_saved_as_a_draft_then_shared` | Students don't see a draft; they see the edited summary once shared |
| `test_location_check_over_http` | Block mode over real HTTP: no location, far and near phones; coordinates never reach students; switching off |
| `test_head_count_over_http` | Only the lecturer can save a head count; non-integers are rejected; students never see it |
| `test_detection_model_is_served_and_cached` | The detector's files are served, and cached by the browser while our own code is not |
| `test_comment_flood_is_slowed_down` | The sixth comment from one phone gets 429; another phone is unaffected |
| `test_bad_requests` | Broken JSON, a JSON list, an unknown class and an unknown path give 400 / 404, never 500 |
| `test_live_stream_keeps_names_away_from_students` | The dashboard stream gets the attendance event (a count); the student stream gets only the comment |
| `test_simulated_class_of_phones` | The simulator itself: 12 phones check in, receive a live poll, vote, comment and submit homework |

## 8.5 Test doubles
- **`FakeClock`**: lets us "wait" 40 s or a week instantly (token expiry, late marking, rate-limit windows).
- **`FakeLLMClient`**: records prompts and returns a canned answer. It lets us test prompt content, chunking and the fallback with no network and no cost.
- **In-memory SQLite (`:memory:`)**: a real database engine, isolated per test.
- **Simulated coordinates**: a classroom point, a phone about 55 m away and one about 11 km away (`tests/helpers.py`).

## 8.6 Manual system test checklist (before the demo)
- [ ] `python3 run.py` prints the lecturer address and the PIN.
- [ ] Log in on the laptop and start a class. The QR progress bar moves, and the QR and the 6-digit code change every 20 s.
- [ ] Phone 1 scans and enters its details: "Checked in". The dashboard count goes to 1 within 2 s.
- [ ] Phone 1 scans again: still checked in, and no duplicate row.
- [ ] Phone 1 enters a different ID: "This phone already checked in another student".
- [ ] A photo of the QR taken 1 minute earlier: "The code expired".
- [ ] Phone 2 opens the address shown under the QR and types the 6-digit code: checked in, with a "typed code" badge.
- [ ] Add a student by hand, then remove them with ✕.
- [ ] The Excel download opens in Excel with three sheets, and Hebrew names look right. The CSV opens too.
- [ ] Poll template "Understood?": phones get it instantly, and the bars update.
- [ ] Phone in airplane mode posts a comment, then airplane mode is turned off: the comment arrives.
- [ ] Hide a comment on the dashboard: it disappears from the phones.
- [ ] Upload `demo/sample-lecture.vtt`, click Summarise, then Share: a Summary tab appears on the phones.
- [ ] Paste the 3 answers from `demo/homework-samples.md` from 3 phones: A↔C is flagged.
- [ ] Switch the language button on a phone and on the dashboard: Hebrew, right-to-left.
- [ ] With `ANTHROPIC_API_KEY` set, the summary and review report `method: llm`.
- [ ] (Only if you use it) Location check through an HTTPS tunnel: a phone in the room is accepted; with "block", a phone with location denied is rejected.
- [ ] `python3 tools/simulate_class.py --pin <PIN> --students 30` ends with `RESULT: all good`.
- [ ] Photograph the room with a few people in it: boxes appear, a click removes or adds one, Save stores the number, and the gap with the check-ins is shown.

## 8.7 What is not covered (known gaps)
- **Real phones.** Everything was run in a desktop browser (also at phone size) and by simulated phones. Scanning the projected QR with a real camera, Safari on iOS and the campus Wi-Fi have not been tried yet.
- **The location check on real hardware.** The logic is tested with simulated coordinates. It has not been tried on a real phone or through an HTTPS tunnel.
- **The real Claude API.** Prompts are tested with a fake client. The quality of the LLM output is judged by hand, not asserted.
- **Head count accuracy.** The detector was tried only on 4 sample classroom photos from Wikimedia Commons, by eye. It misses people at the back or partly hidden; there is no measured accuracy on a photo of our own class. The automatic tests cover the server side only (saving and comparing the number).
- **Microsoft Excel itself.** The .xlsx files are validated and open in macOS Quick Look; they were not opened in Excel.
- **Network delay.** The load test ran on one machine, so its numbers show server capacity, not Wi-Fi quality.
- **Other Python versions.** The tests ran only on Python 3.15 on the development laptop. The GitHub Actions workflow that would run them on 3.10 and 3.13 is written but not switched on (see 8.2).
