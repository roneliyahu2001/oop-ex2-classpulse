# 3. Software Requirements Specification (SRS): Classica

## 1. Introduction
**1.1 Purpose.** This document specifies the requirements for Classica, a web-based teaching tool used in class.
**1.2 Audience.** The course staff, the developers, and the testers.
**1.3 Definitions.**
- **Session**: one class meeting.
- **Check-in**: a student marking attendance.
- **Token / code**: the rotating secret on the lecturer's screen. The token is inside the QR link; the code is 6 digits a student can type.
- **Device**: one phone browser, recognised by a random cookie.
- **Geofence**: a circle around the classroom used by the optional location check.
- **SSE**: Server-Sent Events.
- **LLM**: a large language model (Claude).

## 2. Overall description
**2.1 Product perspective.** Classica is a standalone web app served from the lecturer's laptop. It has no external integrations.

**2.2 Users**
| User | Device | Technical level | Needs |
|---|---|---|---|
| Student | Smartphone browser | Any | Check in with one scan, vote, ask questions, get feedback |
| Lecturer | Laptop and projector | Medium | An attendance sheet, a quick feel for the class, summaries, review help |

**2.3 Operating environment.** The server needs Python 3.10 or newer on macOS, Windows or Linux. Clients are any modern mobile or desktop browser.

**2.4 Constraints**
- No integration with Moodle, Zoom, Google Classroom or the university's student-information system ("מידע אישי").
- Video is summarised from its exported transcript. Raw audio is not processed.
- The app must run with no package installs.
- Browsers share a phone's location only with HTTPS pages, so the location check needs an HTTPS address.

**2.5 Assumptions.** Phones can reach the laptop over the network. The lecturer can project the dashboard.

## 3. Functional requirements

### 3.1 Sessions
| ID | Requirement | Priority |
|---|---|---|
| FR-S1 | The lecturer logs in with a PIN that is printed on the server console. | Must |
| FR-S2 | The lecturer starts a session with a title. The session gets a short unique ID. | Must |
| FR-S3 | The lecturer ends a session. After that, check-in and new polls are rejected. | Must |
| FR-S4 | The lecturer can reopen the data (attendance, polls, comments) of past sessions. | Should |
| FR-S5 | A student who opens the address without scanning is taken to the session that is open now. | Should |
| FR-S6 | Every screen is available in Hebrew (right-to-left) and English. The choice is remembered per browser. | Should |

### 3.2 Attendance (main feature)
| ID | Requirement | Priority |
|---|---|---|
| FR-A1 | The dashboard shows a QR code that encodes the URL `/?s=<session>&t=<token>`. | Must |
| FR-A2 | The token rotates every 20 s. Tokens from the current and the previous window are accepted. | Must |
| FR-A3 | A student checks in with a student ID (5–10 digits) and a name. Both are remembered on the phone, so later check-ins need only one scan. | Must |
| FR-A4 | Each student ID checks in at most once per session. Re-scanning from the same phone is idempotent. | Must |
| FR-A5 | A phone (device cookie) checks in at most one student per session, which prevents checking in a friend. | Must |
| FR-A6 | The lecturer sees a live attendance table and a count, updated in under 2 s. | Must |
| FR-A7 | The lecturer downloads attendance as CSV (UTF-8 with BOM, opens in Excel or Sheets). | Must |
| FR-A8 | The dashboard also shows a 6-digit code that rotates with the QR. A student whose camera fails types it instead of scanning. | Must |
| FR-A9 | A check-in more than N minutes after the session start (default 15) is marked "late". | Should |
| FR-A10 | The lecturer adds a student by hand (dead phone) and removes a wrong record, also after the session ended. | Should |
| FR-A11 | **Location check (optional per session).** The lecturer sets a circle around the laptop's position (radius 30–5000 m). Mode "mark": everyone checks in, and students who are far or sent no location are flagged. Mode "block": such students are rejected. The server stores only the distance, never coordinates. | Should |
| FR-A12 | The lecturer's table hints when two check-ins came from the same network address (possibly one phone used twice). | Could |
| FR-A13 | The lecturer downloads an Excel workbook per session with three sheets: attendance, polls, comments. | Must |
| FR-A14 | The lecturer sees and downloads a course report: students × sessions, with a count and percentage per student. | Should |
| FR-A15 | **Head count from a photo.** The lecturer takes or chooses a photo of the class. People in it are detected in the lecturer's browser and shown as numbered boxes; the lecturer can remove a wrong box or add a missed person by clicking. The saved count is compared with the number of check-ins, and a gap of more than 2 is highlighted. The photo is never uploaded; only the number is stored. People are counted, never identified. | Should |

### 3.3 Comments
| ID | Requirement | Priority |
|---|---|---|
| FR-C1 | A student posts a comment of 1–500 characters. It is anonymous by default and can optionally be signed. | Must |
| FR-C2 | Comments appear live on the dashboard and on other phones. | Must |
| FR-C3 | Comments are accepted after the session ends (offline feedback). | Must |
| FR-C4 | A comment written while the phone is offline is queued and sent automatically when the phone reconnects. | Should |
| FR-C5 | Students upvote comments, once per phone. The dashboard sorts comments by upvotes. | Should |
| FR-C6 | The lecturer marks a comment as answered, or hides it. A hidden comment disappears from all phones at once. | Should |
| FR-C7 | A phone can post at most 5 comments in 30 seconds. | Should |

### 3.4 Polls
| ID | Requirement | Priority |
|---|---|---|
| FR-P1 | The lecturer creates a poll with one question and 2–6 options, or uses a one-click template. | Must |
| FR-P2 | Only one poll is open at a time. Creating a new poll closes the previous one. | Must |
| FR-P3 | A phone votes once per poll. Results update live for everyone. | Must |
| FR-P4 | The lecturer closes a poll. Votes on a closed poll are rejected. | Must |

### 3.5 Lesson summary (ML)
| ID | Requirement | Priority |
|---|---|---|
| FR-M1 | The lecturer uploads or pastes a transcript (.vtt, .srt or .txt). | Must |
| FR-M2 | The system removes timestamps and tags, and summarises with the LLM: overview, topics, definitions and review questions. | Must |
| FR-M3 | If the LLM is unavailable, an extractive summary is returned with a note saying so. | Must |
| FR-M4 | A transcript longer than one LLM request is summarised part by part and then combined. | Should |
| FR-M5 | The summary is saved with the session as a draft. The lecturer can edit it and share it; shared summaries appear on the students' phones. | Should |

### 3.6 Homework review (LLM)
| ID | Requirement | Priority |
|---|---|---|
| FR-H1 | A student submits a homework text (at least 10 words), typed, pasted or loaded from a text file. Resubmitting from the same phone replaces the previous text. | Must |
| FR-H2 | The system compares the submission with classmates' submissions: length versus the average, concepts the class covered that are missing, unique concepts, and the maximum 3-gram overlap. | Must |
| FR-H3 | The LLM writes the review (strengths, weaknesses, improvements, suggested grade). There is a heuristic fallback. | Must |
| FR-H4 | Students see classmates only as anonymous statistics. The lecturer sees identities and the pairs flagged for overlap of 50% or more. | Must |
| FR-H5 | Only the phone that submitted (or the lecturer) can replace a submission or read its review. | Must |
| FR-H6 | The lecturer sets the assignment question once per session; students see it and the LLM receives it. The lecturer can delete a submission. | Should |

## 4. Non-functional requirements
| ID | Category | Requirement |
|---|---|---|
| NFR-1 | Usability (KISS) | Check-in takes 2 taps or fewer after the first time. There is no install and no student account. |
| NFR-2 | Performance | Supports 100 concurrent phones on one laptop. Live updates arrive in under 2 s. Measured: 200 simulated phones, slowest live update 20 ms (tools report, 1.4). |
| NFR-3 | Availability | All non-AI features work with no internet, given a local network. |
| NFR-4 | Security | Lecturer endpoints require the PIN cookie. PIN guesses are limited to 5 per minute per address, check-in attempts to 10 per minute per phone. Tokens are HMAC-signed. Static file serving blocks path traversal. Pages carry a Content-Security-Policy. Exported cells cannot run as spreadsheet formulas. |
| NFR-5 | Privacy | Only the student ID and name are stored, in a local SQLite file. Class photos stay in the lecturer's browser; no face recognition. Names and IDs are pushed only to the lecturer's dashboard, never to other phones. Responses never include device IDs, network addresses or the classroom coordinates. |
| NFR-6 | Portability | Uses only the Python standard library and runs on macOS, Windows and Linux. |
| NFR-7 | Maintainability | Layered design (web → services → repository). Dependencies are injected so every service has unit tests. A database file from an older version is upgraded on start. |
| NFR-8 | Localisation | Hebrew works end to end: screens (right-to-left), names in the database, CSV and Excel (right-to-left sheets), and the offline AI texts. |

## 5. Traceability (requirement → class → test)
| Requirement | Class | Test |
|---|---|---|
| FR-A2, FR-A8 | `TokenRotator` | `TokenRotatorTest` |
| FR-A4, FR-A5 | `AttendanceService.check_in` | `test_rescan_same_device_is_idempotent`, `test_one_device_cannot_check_in_two_students` |
| FR-A7 | `AttendanceService.export_csv` | `test_csv_export_has_bom_and_hebrew`, `test_csv_cannot_smuggle_a_formula` |
| FR-A9 | `AttendanceService.check_in` | `test_late_after_fifteen_minutes` |
| FR-A10 | `AttendanceService.add_manual`, `remove` | `test_lecturer_adds_and_removes_by_hand` |
| FR-A11 | `GeoFence`, `AttendanceService._locate`, `SessionService.set_geofence` | `GeoTest`, `test_block_mode`, `test_flag_mode_lets_everyone_in_and_marks_them`, `test_location_check_over_http` |
| FR-A12 | `AttendanceService.list_for_lecturer` | `test_two_checkins_from_one_address_are_flagged` |
| FR-A13, FR-A14 | `ReportService`, `Workbook` | `ReportServiceTest`, `WorkbookTest` |
| FR-A15 | `SessionService.set_headcount`, `ReportService`, `static/headcount.js` | `test_head_count`, `test_head_count_is_compared_with_check_ins`, `test_head_count_over_http`, `test_detection_model_is_served_and_cached`; detection quality checked by hand (testing strategy, 8.7) |
| FR-C3 | `CommentService.post` | `test_offline_comment_after_class_end_allowed` |
| FR-C6, FR-C7 | `CommentService.moderate`, `RateLimiter` | `test_lecturer_marks_answered_and_hides`, `test_comment_flood_is_slowed_down` |
| FR-P2, FR-P3 | `PollService` | `test_new_poll_closes_previous`, `test_one_vote_per_device` |
| FR-M3, FR-M4 | `SummaryService`, `LLMSummarizer` | `test_falls_back_when_llm_fails`, `test_long_lecture_is_summarised_in_parts_then_combined` |
| FR-M5 | `SessionService.save_summary` | `test_summary_is_a_draft_until_published`, `test_summary_is_saved_as_a_draft_then_shared` |
| FR-H4, FR-H5 | `ReviewService`, `Comparison.to_dict` | `test_student_view_hides_identities`, `test_a_student_cannot_read_someone_elses_review`, `test_nobody_else_can_overwrite_a_submission` |
| NFR-2 | whole system | `test_simulated_class_of_phones`, `tools/simulate_class.py` |
| NFR-4 | `Handler`, `RateLimiter` | `test_lecturer_endpoints_protected`, `test_pin_cannot_be_guessed_by_brute_force`, `test_pages_served` |
| NFR-5 | `EventBus` (staff channel) | `test_names_travel_only_on_the_staff_channel`, `test_live_stream_keeps_names_away_from_students` |
| NFR-7 | `Repository._migrate` | `test_database_file_from_version_1_keeps_working` |
