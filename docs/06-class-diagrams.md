# 6. Low-level Class Diagrams

The diagrams match the code in `classpulse/`. They render on GitHub (Mermaid).

## 6.1 Domain model (`models.py`)
```mermaid
classDiagram
  class ClassSession {
    +str id
    +str title
    +float started_at
    +float ended_at
    +str homework_task
    +str summary
    +bool summary_published
    +str geo_mode
    +float geo_lat
    +float geo_lon
    +int geo_radius
    +is_active() bool
    +to_dict(lecturer) dict
  }
  class AttendanceRecord {
    +str session_id
    +str student_id
    +str name
    +str device_id
    +float checked_in_at
    +str status
    +str method
    +str ip
    +str geo
    +int distance_m
    +to_dict() dict
  }
  class Comment {
    +int id
    +str session_id
    +str text
    +str author
    +float created_at
    +int upvotes
    +bool answered
    +bool hidden
  }
  class Poll {
    +int id
    +str session_id
    +str question
    +list~str~ options
    +bool is_open
    +list~int~ votes
    +total_votes() int
  }
  class Submission {
    +int id
    +str session_id
    +str student_id
    +str name
    +str text
    +float submitted_at
    +str device_id
  }
  class DomainError {
    +str code
    +str message
    +int status
  }
  Exception <|-- DomainError
  ClassSession "1" o-- "*" AttendanceRecord
  ClassSession "1" o-- "*" Comment
  ClassSession "1" o-- "*" Poll
  ClassSession "1" o-- "*" Submission
```
Notes: `status` is `on_time` or `late`. `method` is `qr`, `code` or `manual`. `geo` is empty, `ok`, `far` or `none`.
`ClassSession.to_dict(lecturer=False)` drops the classroom coordinates and an unpublished summary.
`AttendanceRecord.to_dict()` drops `device_id` and `ip`.

## 6.2 Core services (sessions, attendance, polls, comments)
```mermaid
classDiagram
  class ClassPulseApp {
    +Config config
    +bytes secret
    +EventBus bus
    +Repository repo
    +TokenRotator rotator
    +SessionService sessions
    +AttendanceService attendance
    +CommentService comments
    +PollService polls
    +ReportService reports
    +SummaryService summary
    +ReviewService reviews
    +RateLimiter login_limiter
    +RateLimiter checkin_limiter
    +RateLimiter comment_limiter
    +checkin_url(session_id) str
  }
  class Config {
    +str db_path
    +str lecturer_pin
    +str public_url
    +int token_period
    +int late_after_minutes
    +bytes secret
  }
  class Repository {
    -Connection _db
    -Lock _lock
    -_migrate()
    +add_session(s)
    +get_session(id) ClassSession
    +end_session(id, t)
    +set_homework_task(id, task)
    +set_summary(id, summary, published)
    +set_geofence(id, mode, lat, lon, radius)
    +add_attendance(rec) bool
    +find_attendance(sid, key) AttendanceRecord
    +list_attendance(sid) list
    +delete_attendance(sid, student_id) bool
    +add_comment(sid, text, author, t) Comment
    +add_upvote(cid, device) bool
    +set_comment_flags(cid, answered, hidden)
    +add_poll(sid, question, options, t) Poll
    +add_vote(pid, device, idx) bool
    +close_poll(pid)
    +upsert_submission(sid, student_id, name, text, t, device) Submission
    +list_submissions(sid) list
    +delete_submission(sid, student_id) bool
  }
  class EventBus {
    +subscribe(channels) Queue
    +unsubscribe(q)
    +publish(channel, event, data)
  }
  class TokenRotator {
    -bytes _secret
    +int period
    -Callable _clock
    +current(session_id) str
    +current_code(session_id) str
    +match(session_id, given) str
    +is_valid(session_id, given) bool
    +seconds_left() int
  }
  class GeoFence {
    +float lat
    +float lon
    +int radius_m
    +distance_to(lat, lon) float
    +contains(lat, lon, accuracy_m) bool
  }
  class RateLimiter {
    +int limit
    +float per_seconds
    -Callable _clock
    +allow(key) bool
    +reset(key)
  }
  class SessionService {
    +start(title) ClassSession
    +get(id) ClassSession
    +require_active(id) ClassSession
    +active() ClassSession
    +end(id) ClassSession
    +list() list
    +set_homework_task(id, task) ClassSession
    +save_summary(id, summary, published) ClassSession
    +set_geofence(id, mode, lat, lon, radius) ClassSession
  }
  class AttendanceService {
    -int _late_after
    +check_in(sid, token, student_id, name, device_id, ip, location) AttendanceRecord
    +add_manual(sid, student_id, name) AttendanceRecord
    +remove(sid, student_id)
    +list(sid) list
    +list_for_lecturer(sid) list
    +export_csv(sid, lang) bytes
    -_locate(session, location) tuple
  }
  class PollService {
    +create(sid, question, options) Poll
    +vote(pid, option, device_id) Poll
    +close(pid) Poll
    +open_poll(sid) Poll
  }
  class CommentService {
    +post(sid, text, author) Comment
    +upvote(cid, device_id) Comment
    +moderate(cid, answered, hidden) Comment
    +list(sid, include_hidden) list
  }
  ClassPulseApp *-- Config
  ClassPulseApp *-- Repository
  ClassPulseApp *-- EventBus
  ClassPulseApp *-- TokenRotator
  ClassPulseApp *-- RateLimiter
  ClassPulseApp *-- SessionService
  ClassPulseApp *-- AttendanceService
  ClassPulseApp *-- PollService
  ClassPulseApp *-- CommentService
  SessionService --> Repository
  SessionService --> EventBus
  AttendanceService --> SessionService
  AttendanceService --> TokenRotator
  AttendanceService --> Repository
  AttendanceService --> EventBus
  AttendanceService ..> GeoFence : creates
  PollService --> SessionService
  PollService --> Repository
  PollService --> EventBus
  CommentService --> SessionService
  CommentService --> Repository
  CommentService --> EventBus
```

## 6.3 Reports
```mermaid
classDiagram
  class ReportService {
    +session_workbook(sid, lang) bytes
    +course_matrix() dict
    +course_workbook(lang) bytes
  }
  class Workbook {
    -bool _rtl
    -list _sheets
    +add_sheet(name, rows, widths)
    +to_bytes() bytes
  }
  class Repository
  class SessionService
  ReportService --> Repository
  ReportService --> SessionService
  ReportService ..> Workbook : creates
```

## 6.4 AI services: Strategy pattern with an offline fallback
```mermaid
classDiagram
  class LLMClient {
    <<abstract>>
    +complete(system, prompt, max_tokens) str
  }
  class AnthropicClient {
    +str model
    +complete(system, prompt, max_tokens) str
  }
  class FakeLLMClient {
    +str answer
    +list calls
    +complete(system, prompt, max_tokens) str
  }
  LLMClient <|-- AnthropicClient
  LLMClient <|-- FakeLLMClient

  class Summarizer {
    <<abstract>>
    +str name
    +summarize(text, lang) str
  }
  class LLMSummarizer {
    +int CHUNK_CHARS
  }
  class ExtractiveSummarizer {
    +int sentences
  }
  Summarizer <|-- LLMSummarizer
  Summarizer <|-- ExtractiveSummarizer
  LLMSummarizer --> LLMClient

  class SummaryService {
    -Summarizer _primary
    -Summarizer _fallback
    +summarize(raw_transcript, lang) dict
  }
  SummaryService o-- Summarizer : primary 0..1
  SummaryService o-- Summarizer : fallback 1

  class Reviewer {
    <<abstract>>
    +str name
    +review(sub, cmp, task, lang) str
  }
  class LLMReviewer
  class HeuristicReviewer
  Reviewer <|-- LLMReviewer
  Reviewer <|-- HeuristicReviewer
  LLMReviewer --> LLMClient

  class SimilarityAnalyzer {
    +compare(target, others) Comparison
    +matrix(subs) list
  }
  class Comparison {
    +int words
    +float class_avg_words
    +float max_similarity
    +str most_similar_to
    +list missing_concepts
    +list unique_concepts
    +int class_size
    +to_dict(include_identities) dict
  }
  class ReviewService {
    +submit(sid, student_id, name, text, device_id) Submission
    +delete(sid, student_id)
    +review_student(sid, student_id, task, lecturer, device_id, lang) dict
    +class_overview(sid) dict
  }
  class Repository
  ReviewService o-- Reviewer : primary / fallback
  ReviewService *-- SimilarityAnalyzer
  ReviewService --> Repository
  SimilarityAnalyzer ..> Comparison : creates
```

## 6.5 Web layer
```mermaid
classDiagram
  class BaseHTTPRequestHandler
  class ThreadingHTTPServer
  class ClassPulseApp
  class Handler {
    +ClassPulseApp app
    +is_lecturer() bool
    +device_id() str
    +peer_ip() str
    +limit(limiter, key)
    +lang(body) str
    +body() dict
    +dispatch(method)
    +static(path)
    +events(sid)
    +checkin()
    +create_poll()
    +vote()
  }
  class Server {
    +bool daemon_threads
    +int request_queue_size
  }
  BaseHTTPRequestHandler <|-- Handler
  ThreadingHTTPServer <|-- Server
  Server o-- Handler : one per request thread
  Handler --> ClassPulseApp
```

## 6.6 Design decisions (OOD principles)
| Principle / pattern | Where | Why |
|---|---|---|
| **Single Responsibility** | Each service owns one feature. `Repository` owns SQL. `Handler` owns HTTP. `Workbook` owns the file format. | Each class has one reason to change |
| **Dependency Inversion** | Services depend on `LLMClient`, `Summarizer` and `Reviewer` abstractions | We can swap Claude for another LLM, or a fake |
| **Strategy** | Summarizer and Reviewer implementations | Lets the AI path and the offline path be swapped |
| **Observer (pub/sub)** | `EventBus` with SSE subscribers, public and staff channels | Live updates without polling, and names reach only the lecturer |
| **Repository** | `Repository` | Persistence is isolated from the domain, including schema upgrades |
| **Composition root / DI** | `ClassPulseApp` | One place builds the graph. Tests inject `FakeClock` |
| **Value objects** | dataclasses in `models.py`, the frozen `GeoFence` | Simple, comparable, serialisable |
| **Information hiding** | `to_dict()` methods drop `device_id`, `ip`, coordinates, draft summaries and classmates' identities | Privacy (NFR-5) is enforced in one place per entity |
| **Open/closed** | A new check-in rule (late marking, location) was added inside `AttendanceService` without touching the web layer or other services | Features grow without rewrites |
| **Fail safe** | `SummaryService` and `ReviewService` catch any LLM failure and fall back | The demo never depends on the network |
