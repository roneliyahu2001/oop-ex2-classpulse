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
    +is_active() bool
    +to_dict() dict
  }
  class AttendanceRecord {
    +str session_id
    +str student_id
    +str name
    +str device_id
    +float checked_in_at
    +to_dict() dict
  }
  class Comment {
    +int id
    +str session_id
    +str text
    +str author
    +float created_at
    +int upvotes
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

## 6.2 Core services (attendance, polls, comments)
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
    +SummaryService summary
    +ReviewService reviews
    +checkin_url(session_id) str
  }
  class Config {
    +str db_path
    +str lecturer_pin
    +str public_url
    +int token_period
    +bytes secret
  }
  class Repository {
    -Connection _db
    -Lock _lock
    +add_session(s)
    +get_session(id) ClassSession
    +end_session(id, t)
    +add_attendance(rec)
    +find_attendance(sid, key) AttendanceRecord
    +list_attendance(sid)
    +add_comment(...) Comment
    +add_upvote(cid, device) bool
    +add_poll(...) Poll
    +add_vote(pid, device, idx) bool
    +close_poll(pid)
    +upsert_submission(...) Submission
    +list_submissions(sid)
  }
  class EventBus {
    +subscribe(channel) Queue
    +unsubscribe(channel, q)
    +publish(channel, event, data)
  }
  class TokenRotator {
    -bytes _secret
    +int period
    -Callable _clock
    +current(session_id) str
    +is_valid(session_id, token) bool
    +seconds_left() int
  }
  class SessionService {
    +start(title) ClassSession
    +get(id) ClassSession
    +require_active(id) ClassSession
    +end(id) ClassSession
    +list() list
  }
  class AttendanceService {
    +check_in(sid, token, student_id, name, device_id) AttendanceRecord
    +list(sid) list
    +export_csv(sid) bytes
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
    +list(sid) list
  }
  ClassPulseApp *-- Config
  ClassPulseApp *-- Repository
  ClassPulseApp *-- EventBus
  ClassPulseApp *-- TokenRotator
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
  PollService --> SessionService
  PollService --> Repository
  PollService --> EventBus
  CommentService --> SessionService
  CommentService --> Repository
  CommentService --> EventBus
```

## 6.3 AI services: Strategy pattern with an offline fallback
```mermaid
classDiagram
  class LLMClient {
    <<abstract>>
    +complete(system, prompt, max_tokens) str
  }
  class AnthropicClient {
    +str model
    +complete(...) str
  }
  class FakeLLMClient {
    +str answer
    +list calls
    +complete(...) str
  }
  LLMClient <|-- AnthropicClient
  LLMClient <|-- FakeLLMClient

  class Summarizer {
    <<abstract>>
    +str name
    +summarize(text) str
  }
  class LLMSummarizer
  class ExtractiveSummarizer {
    +int sentences
  }
  Summarizer <|-- LLMSummarizer
  Summarizer <|-- ExtractiveSummarizer
  LLMSummarizer --> LLMClient

  class SummaryService {
    -Summarizer _primary
    -Summarizer _fallback
    +summarize(raw_transcript) dict
  }
  SummaryService o-- Summarizer : primary 0..1
  SummaryService o-- Summarizer : fallback 1

  class Reviewer {
    <<abstract>>
    +str name
    +review(sub, cmp, task) str
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
    +submit(sid, student_id, name, text) Submission
    +review_student(sid, student_id, task, lecturer) dict
    +class_overview(sid) dict
  }
  ReviewService o-- Reviewer : primary / fallback
  ReviewService *-- SimilarityAnalyzer
  ReviewService --> Repository
  SimilarityAnalyzer ..> Comparison : creates
```

## 6.4 Web layer
```mermaid
classDiagram
  class BaseHTTPRequestHandler
  class Handler {
    +ClassPulseApp app
    +is_lecturer() bool
    +device_id() str
    +body() dict
    +dispatch(method)
    +static(path)
    +events(sid)
    +checkin()
    +create_poll()
    +vote()
  }
  class ThreadingHTTPServer
  BaseHTTPRequestHandler <|-- Handler
  ThreadingHTTPServer o-- Handler : one per request thread
  Handler --> ClassPulseApp
```

## 6.5 Design decisions (OOD principles)
| Principle / pattern | Where | Why |
|---|---|---|
| **Single Responsibility** | Each service owns one feature. `Repository` owns SQL. `Handler` owns HTTP. | Each class has one reason to change |
| **Dependency Inversion** | Services depend on `LLMClient`, `Summarizer` and `Reviewer` abstractions | We can swap Claude for another LLM, or a fake |
| **Strategy** | Summarizer and Reviewer implementations | Lets the AI path and the offline path be swapped |
| **Observer (pub/sub)** | `EventBus` with SSE subscribers | Live updates without polling |
| **Repository** | `Repository` | Persistence is isolated from the domain |
| **Composition root / DI** | `ClassPulseApp` | One place builds the graph. Tests inject `FakeClock` |
| **Value objects** | dataclasses in `models.py` | Simple, comparable, serialisable |
| **Information hiding** | `AttendanceRecord.to_dict()` drops `device_id`. `Comparison.to_dict(False)` drops identities | Privacy (NFR-5) |
