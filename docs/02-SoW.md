# 2. Statement of Work (SoW): ClassPulse

## 2.1 Background
Online teaching tools are fragmented: attendance in one place, polls in another, and recordings
nobody re-watches. ClassPulse is one small, LLM-ready web app the lecturer opens on the projector
and students open on their phones by scanning a QR code.

## 2.2 Objectives
1. **Attendance (primary):** an attendance spreadsheet produced automatically during class, hard to fake from home.
2. Real-time and offline student comments.
3. One-click "KISS" polls.
4. An AI summary of a recorded lesson.
5. An AI homework review that includes a comparison with classmates.

## 2.3 Scope
**In scope**
- A responsive web app with two views: a student phone view and a lecturer dashboard.
- A Python backend with SQLite storage and Server-Sent Events.
- CSV export of attendance.
- Summaries from Zoom / Meet transcript files (.vtt / .srt / .txt).
- Homework submitted as text, with similarity analysis and an LLM review (offline fallback when no LLM is available).
- Design documents (SRS, use cases, components, class and sequence diagrams, testing strategy).
- A 10-minute live demo in class.

**Out of scope** (per the assignment guidelines)
- Integration with Moodle, Zoom APIs or Google Classroom APIs.
- Personal data beyond student ID and name. No passwords for students, no photos, no location.
- Speech-to-text from raw video files. We use the transcript the platform already produces.
- Native iOS / Android apps.
- Multi-lecturer accounts and course management.

## 2.4 Deliverables
| # | Deliverable | Location |
|---|---|---|
| D1 | Repository and README (problem, scope, how to run) | `README.md` |
| D2 | Tools report | `docs/01-tools-report.md` |
| D3 | SoW | this file |
| D4 | SRS | `docs/03-SRS.md` |
| D5 | Use cases / user stories | `docs/04-use-cases.md` |
| D6 | Components | `docs/05-components.md` |
| D7 | Class and sequence diagrams | `docs/06-class-diagrams.md`, `docs/07-sequence-diagrams.md` |
| D8 | Testing strategy and tests | `docs/08-testing-strategy.md`, `tests/` |
| D9 | Demo web app | `run.py`, `classpulse/`, `static/` |
| D10 | Demo script | `docs/09-demo-script.md` |
| D11 | Conclusions | `docs/10-conclusions.md` |

## 2.5 Milestones
| Milestone | Content | Exit criterion |
|---|---|---|
| M1 Define | README, scope, tools report | Stack chosen and smoke-tested |
| M2 Design | SoW, SRS, use cases, components, diagrams | Every SRS requirement maps to a class |
| M3 Build | Attendance first, then polls/comments, then AI | `python3 -m unittest` is green |
| M4 Rehearse | Dry run with 3 phones on a hotspot | Check-in in under 10 s per student |
| M5 Demo and conclude | Live demo, conclusions written | Attendance CSV produced in class |

## 2.6 Assumptions and constraints
- The lecturer's laptop and the students' phones can reach each other (same Wi-Fi, a hotspot or a tunnel).
- An Anthropic API key is optional. Without one, the AI features run in offline mode.
- Python 3.10 or newer is on the lecturer's laptop. No other installs are needed.

## 2.7 Acceptance criteria
- In class, at least 90% of students present check in successfully within 2 minutes.
- The lecturer downloads a CSV that opens in Excel with correct Hebrew names.
- A poll is created and results show live in under 2 seconds.
- A summary is produced from a real .vtt file.
- A homework review shows comparison statistics and flags a copied submission.
