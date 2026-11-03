# 8. Testing Strategy

## 8.1 Goals
1. The **main feature (attendance)** must never fail in class, so it has the most tests, especially anti-cheating rules.
2. Every class in the class diagrams (section 6) has unit tests, or is covered by integration tests where it is pure glue.
3. The tests are fast (under 1 s) and need no network and no API key, so they can run before every commit and right before the demo.

## 8.2 Test levels
| Level | What | Tooling | Where |
|---|---|---|---|
| Unit | One class, with collaborators replaced by fakes (`FakeClock`, `FakeLLMClient`, in-memory SQLite) | `unittest` | `tests/test_services.py` |
| Integration | A real `ThreadingHTTPServer` on a random port, real HTTP, cookies (one cookie jar per simulated phone), real SSE stream | `unittest` + `urllib` | `tests/test_web.py` |
| System / manual | The full flow in a browser: desktop dashboard plus a phone-size viewport | Browser, real phones | Checklist in 8.5 |
| Acceptance | The live demo against the SoW acceptance criteria | Real class | `docs/09-demo-script.md` |

Run them all with:
```bash
python3 -m unittest discover -s tests -t .
```
Current result: **48 tests, all passing, about 0.5 s.**

## 8.3 Unit tests per class (maps to the class diagrams)
| Class | Technique | Test cases |
|---|---|---|
| `TokenRotator` | Inject `FakeClock`, boundary values | valid now; valid in the previous window (+20 s); invalid after 2 windows (+40 s); bound to its session; `seconds_left` |
| `EventBus` | State | publish reaches only that channel's subscribers; unsubscribe |
| `SessionService` | Equivalence classes | start trims the title; empty title is rejected; can't end twice; unknown ID gives 404 |
| `AttendanceService` | Decision table (token × session × duplicate student × duplicate device) | happy path plus an event; re-scan is idempotent; same student on another device; one device for two students; expired token; invalid ID or name; closed session; CSV BOM and Hebrew |
| `CommentService` | Equivalence and boundary (0 and 501 chars) | anonymous by default; one upvote per device; posting after the class ends |
| `PollService` | State machine (open → closed) | vote counts; one vote per device; a new poll closes the old one; closed poll rejects votes; 1 or 7 options rejected; bad option index |
| `text_tools` | Example-based | VTT timestamps and `<v>` tags removed |
| `SummaryService`, `ExtractiveSummarizer`, `LLMSummarizer` | Strategy substitution, fault injection | offline summary; LLM used when present (checked through the prompt); **fallback when the LLM raises**; too short; sentence limit |
| `ReviewService`, `SimilarityAnalyzer`, `HeuristicReviewer`, `LLMReviewer` | Fixture texts (good, different, short, copied) | resubmit replaces; too short; student view hides identities; lecturer view shows them; copy detection flags the pair; missing concepts found; the LLM prompt contains the task and the comparison; no submission gives 404 |
| `Repository` | Covered through the services above plus integration | uniqueness constraints (attendance PK, vote PK, upvote PK, submission UNIQUE) |
| `Handler` (web) | Integration | pages served; path traversal gives 404; lecturer-only endpoints give 401; bad PIN; full class flow (check-in, friend check-in blocked, bad token, CSV, poll, vote, double vote, comment, upvote, homework, end); summary endpoint; bad JSON gives 400; SSE delivers events |
| `AnthropicClient` | Not unit-tested (it calls an external API) | Covered by a manual smoke test with a real key (8.5) |

## 8.4 Test doubles
- **`FakeClock`**: lets us "wait" 40 s instantly to test token expiry.
- **`FakeLLMClient`**: records prompts and returns a canned answer. It lets us test prompt content and the fallback with no network and no cost.
- **In-memory SQLite (`:memory:`)**: a real database engine, isolated per test.

## 8.5 Manual system test checklist (before the demo)
- [ ] `python3 run.py` prints the LAN URL and the PIN.
- [ ] Log in on the laptop and start a class. The QR progress bar moves and the QR changes every 20 s.
- [ ] Phone 1 scans and enters its details: "Checked in". The dashboard count goes to 1 within 2 s.
- [ ] Phone 1 scans again: still checked in, and no duplicate row.
- [ ] Phone 1 enters a different ID: "This phone already checked in another student".
- [ ] A photo of the QR taken 1 minute earlier: "QR code expired".
- [ ] The CSV download opens in Excel, and Hebrew names look right.
- [ ] Poll template "Understood?": phones get it instantly, and the bars update.
- [ ] Phone in airplane mode posts a comment, then airplane mode is turned off: the comment arrives.
- [ ] Upload `demo/sample-lecture.vtt`: a summary appears.
- [ ] Paste the 3 answers from `demo/homework-samples.md`: A↔C is flagged.
- [ ] With `ANTHROPIC_API_KEY` set, the summary and review report `method: llm`.

## 8.6 What is not covered (known gaps)
- Load testing with 100 phones is not automated yet. The plan is a simple Python script that opens 100 SSE connections and posts check-ins.
- Cross-browser automation (Safari on iOS) is checked by hand only.
- The quality of the LLM output is judged by hand. It is not asserted.
