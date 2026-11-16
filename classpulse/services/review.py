"""Feature 5: deep homework review, including comparison with classmates.

Comparison is always computed locally (deterministic, testable). The written
feedback comes from the LLM when available, otherwise from simple heuristics.
Students only ever see classmates as anonymous statistics, never their text.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections import Counter
from dataclasses import dataclass
from statistics import mean
from typing import Callable

from ..events import EventBus, staff_channel
from ..i18n import tr
from ..llm import LLMClient
from ..models import DomainError, Submission
from ..repository import Repository
from ..text_tools import content_words, jaccard, shingles
from .sessions import SessionService

COPY_THRESHOLD = 0.5
MAX_SUBMISSION = 20_000


@dataclass
class Comparison:
    words: int
    class_avg_words: float
    max_similarity: float          # to the most similar classmate
    most_similar_to: str | None    # student id (lecturer view only)
    missing_concepts: list[str]    # terms most classmates used and this one did not
    unique_concepts: list[str]     # terms only this submission used
    class_size: int

    def to_dict(self, include_identities: bool) -> dict:
        d = self.__dict__.copy()
        if not include_identities:
            d.pop("most_similar_to")
        d["max_similarity"] = round(self.max_similarity, 2)
        d["class_avg_words"] = round(self.class_avg_words)
        d["possible_copy"] = self.max_similarity >= COPY_THRESHOLD
        return d


class SimilarityAnalyzer:
    def compare(self, target: Submission, others: list[Submission]) -> Comparison:
        t_sh = shingles(target.text)
        t_terms = set(content_words(target.text))
        best, best_id = 0.0, None
        term_df: Counter = Counter()
        for o in others:
            sim = jaccard(t_sh, shingles(o.text))
            if sim > best:
                best, best_id = sim, o.student_id
            term_df.update(set(content_words(o.text)))
        n = len(others)
        common = [w for w, c in term_df.most_common(40) if n and c / n >= 0.5]
        missing = [w for w in common if w not in t_terms][:8]
        unique = [w for w in t_terms if term_df[w] == 0] if others else []
        unique.sort(key=lambda w: (-target.text.lower().count(w), w))
        lens = [len(o.text.split()) for o in others] or [len(target.text.split())]
        return Comparison(len(target.text.split()), mean(lens), best, best_id,
                          missing, unique[:8], n + 1)

    def matrix(self, subs: list[Submission]) -> list[list[float]]:
        sh = [shingles(s.text) for s in subs]
        return [[round(jaccard(a, b), 2) if i != j else 1.0 for j, b in enumerate(sh)]
                for i, a in enumerate(sh)]


class Reviewer(ABC):
    name: str

    @abstractmethod
    def review(self, sub: Submission, cmp: Comparison, task: str, lang: str = "en") -> str: ...


class HeuristicReviewer(Reviewer):
    """Offline fallback: plain statistics, phrased as feedback."""
    name = "heuristic"

    def review(self, sub: Submission, cmp: Comparison, task: str, lang: str = "en") -> str:
        out = []
        if cmp.class_size == 1:
            out.append(tr(lang, "rev_alone"))
        else:
            ratio = cmp.words / cmp.class_avg_words if cmp.class_avg_words else 1
            key = "rev_short" if ratio < 0.6 else "rev_long" if ratio > 1.6 else "rev_ok"
            out.append(tr(lang, key, words=cmp.words, avg=round(cmp.class_avg_words)))
        if cmp.missing_concepts:
            out.append(tr(lang, "rev_missing", terms=", ".join(cmp.missing_concepts)))
        if cmp.unique_concepts:
            out.append(tr(lang, "rev_unique", terms=", ".join(cmp.unique_concepts[:5])))
        if cmp.max_similarity >= COPY_THRESHOLD:
            out.append(tr(lang, "rev_overlap", pct=round(cmp.max_similarity * 100)))
        return "\n".join(f"- {line}" for line in out) + "\n" + tr(lang, "rev_offline")


class LLMReviewer(Reviewer):
    name = "llm"
    SYSTEM = ("You are a strict but kind teaching assistant in a software-engineering course. "
              "Answer in the language of the submission.")

    def __init__(self, client: LLMClient):
        self._client = client

    def review(self, sub: Submission, cmp: Comparison, task: str, lang: str = "en") -> str:
        prompt = (f"Assignment: {task or '(not given)'}\n\n"
                  f"Student submission:\n<submission>\n{sub.text}\n</submission>\n\n"
                  f"Comparison with {cmp.class_size - 1} classmates (anonymous): "
                  f"length {cmp.words} words vs avg {cmp.class_avg_words:.0f}; "
                  f"concepts most classmates covered but this one did not: {cmp.missing_concepts}; "
                  f"concepts only this student raised: {cmp.unique_concepts}; "
                  f"highest overlap with one classmate: {cmp.max_similarity:.0%}.\n\n"
                  "Give: strengths, weaknesses, how it compares to the class, "
                  "3 concrete improvements, and a suggested grade out of 100 with one line of reasoning.")
        return self._client.complete(self.SYSTEM, prompt)


class ReviewService:
    def __init__(self, repo: Repository, sessions: SessionService, primary: Reviewer | None,
                 fallback: Reviewer | None = None, clock: Callable[[], float] = time.time,
                 bus: EventBus | None = None):
        self._bus = bus
        self._repo = repo
        self._sessions = sessions
        self._primary = primary
        self._fallback = fallback or HeuristicReviewer()
        self._analyzer = SimilarityAnalyzer()
        self._clock = clock

    def submit(self, session_id: str, student_id: str, name: str, text: str,
               device_id: str = "") -> Submission:
        self._sessions.get(session_id)
        text, student_id = text.strip(), student_id.strip()
        if len(text.split()) < 10:
            raise DomainError("SUBMISSION_TOO_SHORT", "Submission needs at least 10 words")
        if not student_id:
            raise DomainError("STUDENT_ID_REQUIRED", "Student ID is required")
        existing = self._repo.get_submission(session_id, student_id)
        if existing and existing.device_id and existing.device_id != device_id:
            raise DomainError("SUBMISSION_LOCKED",
                              "This student ID already submitted from another phone", 409)
        sub = self._repo.upsert_submission(session_id, student_id, name.strip() or "?",
                                           text[:MAX_SUBMISSION], self._clock(), device_id)
        if self._bus:  # the dashboard's list refreshes by itself
            self._bus.publish(staff_channel(session_id), "homework", {"student_id": student_id})
        return sub

    def delete(self, session_id: str, student_id: str) -> None:
        """Lecturer only, e.g. when someone submitted under another student's ID."""
        if not self._repo.delete_submission(session_id, student_id):
            raise DomainError("NO_SUBMISSION", "No such submission", 404)

    def _write(self, sub: Submission, cmp: Comparison, task: str, lang: str) -> tuple[str, str]:
        if self._primary is not None:
            try:
                return self._primary.name, self._primary.review(sub, cmp, task, lang)
            except Exception:
                pass  # network down, quota, etc. -> offline review
        return self._fallback.name, self._fallback.review(sub, cmp, task, lang)

    def review_student(self, session_id: str, student_id: str, task: str = "",
                       lecturer: bool = False, device_id: str = "", lang: str = "en") -> dict:
        session = self._sessions.get(session_id)
        subs = self._repo.list_submissions(session_id)
        mine = next((s for s in subs if s.student_id == student_id), None)
        if mine is None:
            raise DomainError("NO_SUBMISSION", "Submit your homework first", 404)
        if not lecturer and mine.device_id and mine.device_id != device_id:
            raise DomainError("NOT_YOUR_SUBMISSION", "You can only review your own homework", 403)
        others = [s for s in subs if s.student_id != student_id]
        cmp = self._analyzer.compare(mine, others)
        method, text = self._write(mine, cmp, task.strip() or session.homework_task, lang)
        return {"student_id": student_id, "method": method, "review": text,
                "comparison": cmp.to_dict(include_identities=lecturer)}

    def class_overview(self, session_id: str) -> dict:
        """Lecturer view: who submitted, pairwise similarity, suspicious pairs."""
        self._sessions.get(session_id)
        subs = self._repo.list_submissions(session_id)
        m = self._analyzer.matrix(subs)
        flagged = [{"a": subs[i].student_id, "b": subs[j].student_id, "similarity": m[i][j]}
                   for i in range(len(subs)) for j in range(i + 1, len(subs))
                   if m[i][j] >= COPY_THRESHOLD]
        return {"students": [{"student_id": s.student_id, "name": s.name,
                              "words": len(s.text.split())} for s in subs],
                "matrix": m, "flagged_pairs": flagged}
