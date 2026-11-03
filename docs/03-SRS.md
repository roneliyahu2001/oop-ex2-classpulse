# 3. Software Requirements Specification (SRS): ClassPulse

## 1. Introduction
**1.1 Purpose.** This document specifies the requirements for ClassPulse, a web-based teaching tool used in class.
**1.2 Audience.** The course staff, the developers, and the testers.
**1.3 Definitions.**
- **Session**: one class meeting.
- **Check-in**: a student marking attendance.
- **Token**: the rotating code embedded in the QR.
- **SSE**: Server-Sent Events.
- **LLM**: a large language model (Claude).

## 2. Overall description
**2.1 Product perspective.** ClassPulse is a standalone web app served from the lecturer's laptop. It has no external integrations.

**2.2 Users**
| User | Device | Technical level | Needs |
|---|---|---|---|
| Student | Smartphone browser | Any | Check in with one scan, vote, ask questions, get feedback |
| Lecturer | Laptop and projector | Medium | An attendance sheet, a quick feel for the class, summaries, review help |

**2.3 Operating environment.** The server needs Python 3.10 or newer on macOS, Windows or Linux. Clients are any modern mobile or desktop browser.

**2.4 Constraints**
- No Moodle, Zoom or Google Classroom integration.
- No personal data beyond student ID and name.
- Video is summarised from its exported transcript. Raw audio is not processed.
- The app must run with no package installs.

**2.5 Assumptions.** Phones can reach the laptop over the network. The lecturer can project the dashboard.

## 3. Functional requirements

### 3.1 Sessions
| ID | Requirement | Priority |
|---|---|---|
| FR-S1 | The lecturer logs in with a PIN that is printed on the server console. | Must |
| FR-S2 | The lecturer starts a session with a title. The session gets a short unique ID. | Must |
| FR-S3 | The lecturer ends a session. After that, check-in and new polls are rejected. | Must |
| FR-S4 | The lecturer can reopen the data (attendance, polls, comments) of past sessions. | Should |

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

### 3.3 Comments
| ID | Requirement | Priority |
|---|---|---|
| FR-C1 | A student posts a comment of 1–500 characters. It is anonymous by default and can optionally be signed. | Must |
| FR-C2 | Comments appear live on the dashboard and on other phones. | Must |
| FR-C3 | Comments are accepted after the session ends (offline feedback). | Must |
| FR-C4 | A comment written while the phone is offline is queued and sent automatically when the phone reconnects. | Should |
| FR-C5 | Students upvote comments, once per phone. The dashboard sorts comments by upvotes. | Should |

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

### 3.6 Homework review (LLM)
| ID | Requirement | Priority |
|---|---|---|
| FR-H1 | A student submits a homework text (at least 10 words). Resubmitting replaces the previous text. | Must |
| FR-H2 | The system compares the submission with classmates' submissions: length versus the average, concepts the class covered that are missing, unique concepts, and the maximum 3-gram overlap. | Must |
| FR-H3 | The LLM writes the review (strengths, weaknesses, improvements, suggested grade). There is a heuristic fallback. | Must |
| FR-H4 | Students see classmates only as anonymous statistics. The lecturer sees identities and the pairs flagged for overlap of 50% or more. | Must |

## 4. Non-functional requirements
| ID | Category | Requirement |
|---|---|---|
| NFR-1 | Usability (KISS) | Check-in takes 2 taps or fewer after the first time. There is no install and no student account. |
| NFR-2 | Performance | Supports 100 concurrent phones on one laptop. Live updates arrive in under 2 s. |
| NFR-3 | Availability | All non-AI features work with no internet, given a local network. |
| NFR-4 | Security | Lecturer endpoints require the PIN cookie. Tokens are HMAC-signed. Responses never include device IDs. Static file serving blocks path traversal. |
| NFR-5 | Privacy | Only the student ID and name are stored. Data stays in a local SQLite file. |
| NFR-6 | Portability | Uses only the Python standard library and runs on macOS, Windows and Linux. |
| NFR-7 | Maintainability | Layered design (web → services → repository). Dependencies are injected so every service has unit tests. |
| NFR-8 | Localisation | Hebrew names work end to end (UI, database, CSV). |

## 5. Traceability (requirement → class → test)
| Requirement | Class | Test |
|---|---|---|
| FR-A2 | `TokenRotator` | `TokenRotatorTest` |
| FR-A4, FR-A5 | `AttendanceService.check_in` | `test_rescan_same_device_is_idempotent`, `test_one_device_cannot_check_in_two_students` |
| FR-A7 | `AttendanceService.export_csv` | `test_csv_export_has_bom_and_hebrew` |
| FR-C3 | `CommentService.post` | `test_offline_comment_after_class_end_allowed` |
| FR-P2, FR-P3 | `PollService` | `test_new_poll_closes_previous`, `test_one_vote_per_device` |
| FR-M3 | `SummaryService` | `test_falls_back_when_llm_fails` |
| FR-H4 | `ReviewService`, `Comparison.to_dict` | `test_student_view_hides_identities` |
| NFR-4 | `Handler` | `test_lecturer_endpoints_protected`, `test_pages_served` |
