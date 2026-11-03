"""Feature 4: summary of a recorded lesson.

Input is the transcript file Zoom / Google Meet already produce (.vtt / .srt / .txt).
Speech-to-text of raw video is out of scope (see SRS, section 2.4).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections import Counter

from ..llm import LLMClient
from ..models import DomainError
from ..text_tools import content_words, split_sentences, top_keywords, transcript_to_text

MAX_CHARS = 120_000  # roughly a 90-minute lecture


class Summarizer(ABC):
    name: str

    @abstractmethod
    def summarize(self, text: str) -> str: ...


class ExtractiveSummarizer(Summarizer):
    """Offline fallback: picks the sentences with the most frequent content words."""
    name = "extractive"

    def __init__(self, sentences: int = 7):
        self.sentences = sentences

    def summarize(self, text: str) -> str:
        freq = Counter(content_words(text))
        sents = split_sentences(text)
        if not sents:
            return text[:500]

        def score(s: str) -> float:
            ws = content_words(s)
            return sum(freq[w] for w in ws) / (len(ws) + 1)

        best = sorted(range(len(sents)), key=lambda i: score(sents[i]), reverse=True)[: self.sentences]
        lines = ["Key topics: " + ", ".join(top_keywords(text)), "", "Main points:"]
        lines += [f"- {sents[i]}" for i in sorted(best)]
        return "\n".join(lines)


class LLMSummarizer(Summarizer):
    name = "llm"
    SYSTEM = ("You summarise university lectures for students who missed class. "
              "Answer in the language of the transcript. Be concrete and short.")

    def __init__(self, client: LLMClient):
        self._client = client

    def summarize(self, text: str) -> str:
        prompt = ("Lecture transcript:\n<transcript>\n" + text + "\n</transcript>\n\n"
                  "Write: 1) a 3-sentence overview, 2) the main topics as bullets, "
                  "3) definitions/formulas mentioned, 4) 3 review questions for students.")
        return self._client.complete(self.SYSTEM, prompt)


class SummaryService:
    def __init__(self, primary: Summarizer | None, fallback: Summarizer | None = None):
        self._primary = primary
        self._fallback = fallback or ExtractiveSummarizer()

    def summarize(self, raw_transcript: str) -> dict:
        text = transcript_to_text(raw_transcript)
        if len(text.split()) < 30:
            raise DomainError("TRANSCRIPT_TOO_SHORT", "Transcript is too short to summarise")
        text = text[:MAX_CHARS]
        note = None
        if self._primary is not None:
            try:
                return {"method": self._primary.name, "summary": self._primary.summarize(text),
                        "words": len(text.split()), "note": None}
            except Exception as e:  # network down, quota, etc. -> degrade gracefully
                note = f"LLM unavailable ({type(e).__name__}); used offline summary"
        return {"method": self._fallback.name, "summary": self._fallback.summarize(text),
                "words": len(text.split()), "note": note}
