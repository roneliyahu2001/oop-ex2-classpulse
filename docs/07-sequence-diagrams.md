# 7. Sequence Diagrams

## 7.1 Check-in by QR or typed code (main feature)
```mermaid
sequenceDiagram
  actor St as Student phone
  actor Lc as Lecturer dashboard
  participant H as Handler
  participant RL as RateLimiter
  participant A as AttendanceService
  participant S as SessionService
  participant T as TokenRotator
  participant R as Repository
  participant B as EventBus

  loop every 1 s
    Lc->>H: GET /api/sessions/{sid}/qr
    H->>T: current(sid), current_code(sid), seconds_left()
    H-->>Lc: {url, code, expires_in}
    Note over Lc: redraws the QR and the 6-digit code when they change (every 20 s)
  end
  St->>St: camera scans QR, opens /?s=sid&t=token (or types the address and the code)
  opt the class has a location check
    St->>St: browser asks permission, reads the position
  end
  St->>H: POST /api/checkin {sid, token or code, student_id, name, lat, lon, accuracy}
  H->>RL: allow(device)
  H->>A: check_in(sid, token, id, name, device_id, ip, location)
  A->>S: require_active(sid)
  A->>A: validate ID and name
  A->>T: match(sid, token)
  alt expired or wrong
    A-->>H: DomainError TOKEN_EXPIRED
    H-->>St: 403, scan again or type the code
  end
  A->>R: find_attendance(sid, student_id)
  A->>R: find_attendance(sid, device_id)
  alt duplicate student or device
    A-->>H: DomainError 409
    H-->>St: 409 message
  else new
    A->>A: _locate(session, location) using GeoFence
    alt block mode and far or no location
      A-->>H: DomainError TOO_FAR / LOCATION_REQUIRED
      H-->>St: 403 message
    else allowed
      A->>R: add_attendance(rec with status, method, geo, distance)
      A->>B: publish(staff channel, "attendance", {count})
      B-->>Lc: SSE attendance (no names)
      Lc->>H: GET /api/sessions/{sid}/attendance (lecturer cookie)
      H-->>Lc: rows with badges
      H-->>St: 201 {checked_in_at, status}
    end
  end
```

## 7.2 Turning on the location check
```mermaid
sequenceDiagram
  actor Lc as Lecturer dashboard (localhost)
  participant H as Handler
  participant S as SessionService
  participant R as Repository
  participant B as EventBus
  actor St as Student phones

  Lc->>Lc: choose mode (mark / block) and radius
  Lc->>Lc: navigator.geolocation gives the laptop position
  Lc->>H: POST /api/sessions/{sid}/geofence {mode, lat, lon, radius}
  H->>S: set_geofence(sid, mode, lat, lon, radius)
  S->>S: validate coordinates, clamp radius to 30..5000 m
  S->>R: set_geofence(...)
  S->>B: publish(sid, "session", public dict without coordinates)
  B-->>St: SSE session, geo_mode is now on
  H-->>Lc: session with coordinates (lecturer only)
  Note over Lc: warns if the students' address is not https
```

## 7.3 Live poll
```mermaid
sequenceDiagram
  actor Lc as Lecturer
  actor St as Student phones
  participant H as Handler
  participant P as PollService
  participant R as Repository
  participant B as EventBus

  St->>H: GET /api/sessions/{sid}/events (SSE, kept open)
  Lc->>H: POST /api/sessions/{sid}/polls {question, options}
  H->>P: create(sid, q, options)
  P->>R: close previous open poll
  P->>R: add_poll(...)
  P->>B: publish("poll", poll)
  B-->>St: SSE poll, options shown
  St->>H: POST /api/polls/{pid}/vote {option}
  H->>P: vote(pid, option, device_id)
  P->>R: add_vote() (primary key poll_id + device_id)
  alt already voted
    P-->>H: DomainError ALREADY_VOTED (409)
  else ok
    P->>B: publish("poll", updated counts)
    B-->>Lc: SSE poll, bars update
    B-->>St: SSE poll, bars update
  end
```

## 7.4 Offline comment
```mermaid
sequenceDiagram
  actor St as Student phone
  participant LS as localStorage outbox
  participant H as Handler
  participant C as CommentService
  participant B as EventBus
  actor Lc as Lecturer

  St->>H: POST /comments {text}
  H--xSt: network error (no signal)
  St->>LS: push {sid, body}
  Note over St: "Saved, and it will be sent automatically"
  St->>St: 'online' event or 10-s timer
  St->>LS: read outbox
  St->>H: POST /comments {text}
  H->>C: post(sid, text, author)
  C->>B: publish("comment")
  B-->>Lc: SSE comment
  St->>LS: clear sent items
  Lc->>H: POST /api/comments/{id}/moderate {hidden: true}
  H->>C: moderate(id, hidden=true)
  C->>B: publish("comment", hidden)
  B-->>St: SSE comment, removed from the phones
```

## 7.5 Lesson summary and sharing
```mermaid
sequenceDiagram
  actor Lc as Lecturer
  participant H as Handler
  participant SS as SummaryService
  participant TT as text_tools
  participant LS as LLMSummarizer
  participant LLM as AnthropicClient
  participant ES as ExtractiveSummarizer
  participant S as SessionService
  actor St as Student phones

  Lc->>H: POST /api/summary {transcript (.vtt), session_id}
  H->>SS: summarize(raw, lang)
  SS->>TT: transcript_to_text(raw)
  TT-->>SS: plain text
  alt LLM configured
    SS->>LS: summarize(text)
    loop each part of a long lecture
      LS->>LLM: complete(part i of n)
    end
    LS->>LLM: complete(combine the notes)
    alt success
      LLM-->>SS: summary
    else network / quota error
      SS->>ES: summarize(text)
    end
  else no API key
    SS->>ES: summarize(text)
  end
  SS-->>H: {method, summary, note}
  H->>S: save_summary(sid, summary, published=false)
  H-->>Lc: 200 JSON, shown in an editable box
  Lc->>H: POST /api/sessions/{sid}/summary {summary (edited), published: true}
  H->>S: save_summary(sid, summary, published=true)
  S-->>St: SSE session, the Summary tab appears
```

## 7.6 Homework review
```mermaid
sequenceDiagram
  actor St as Student
  participant H as Handler
  participant RS as ReviewService
  participant R as Repository
  participant SA as SimilarityAnalyzer
  participant RV as Reviewer (LLM / Heuristic)
  actor Lc as Lecturer dashboard

  St->>H: POST /homework {student_id, name, text}
  H->>RS: submit(sid, student_id, name, text, device_id)
  RS->>R: get_submission(sid, student_id)
  alt submitted earlier from another phone
    RS-->>H: DomainError SUBMISSION_LOCKED (409)
  else
    RS->>R: upsert_submission(...)
    RS-->>Lc: SSE homework (staff channel), the list refreshes
  end
  St->>H: POST /homework/{student_id}/review {lang}
  H->>RS: review_student(sid, student_id, task, lecturer=false, device_id, lang)
  RS->>R: list_submissions(sid)
  RS->>RS: check that this phone owns the submission
  RS->>SA: compare(mine, others)
  SA-->>RS: Comparison (length, missing concepts, max overlap)
  RS->>RV: review(sub, comparison, session.homework_task, lang)
  RV-->>RS: feedback text
  RS-->>H: {review, comparison.to_dict(include_identities=false)}
  H-->>St: 200 JSON (no classmate names)
```
