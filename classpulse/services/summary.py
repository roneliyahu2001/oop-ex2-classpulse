"""Feature 4: summary of a recorded lesson.

Input is the transcript file Zoom / Google Meet already produce (.vtt / .srt / .txt).
Speech-to-text of raw video is out of scope (see SRS, section 2.4).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections import Counter

from ..i18n import tr
from ..llm import LLMClient
from ..models import DomainError
from ..text_tools import content_words, split_chunks, split_sentences, top_keywords, transcript_to_text

MAX_CHARS = 400_000  # about five hours of speech; longer input is cut


class Summarizer(ABC):
    name: str

    @abstractmethod
    def summarize(self, text: str, lang: str = "en") -> str: ...


class ExtractiveSummarizer(Summarizer):
    """Offline fallback: picks the sentences with the most frequent content words."""
    name = "extractive"

    def __init__(self, sentences: int = 7):
        self.sentences = sentences

    def summarize(self, text: str, lang: str = "en") -> str:
        freq = Counter(content_words(text))
        sents = split_sentences(text)
        if not sents:
            return text[:500]

        def score(s: str) -> float:
            ws = content_words(s)
            return sum(freq[w] for w in ws) / (len(ws) + 1)

        best = sorted(range(len(sents)), key=lambda i: score(sents[i]), reverse=True)[: self.sentences]
        lines = [f"{tr(lang, 'sum_topics')}: " + ", ".join(top_keywords(text)), "",
                 f"{tr(lang, 'sum_points')}:"]
        lines += [f"- {sents[i]}" for i in sorted(best)]
        return "\n".join(lines)


class LLMSummarizer(Summarizer):
    """Summarises with the LLM. A long lecture is summarised part by part, then combined."""
    name = "llm"
    CHUNK_CHARS = 30_000
    SYSTEM = ("You summarise university lectures for students who missed class. "
              "Answer in the language of the transcript. Be concrete and short.")
    FINAL = ("Write: 1) a 3-sentence overview, 2) the main topics as bullets, "
             "3) definitions/formulas mentioned, 4) 3 review questions for students.")

    def __init__(self, client: LLMClient):
        self._client = client

    def summarize(self, text: str, lang: str = "en") -> str:
        chunks = split_chunks(text, self.CHUNK_CHARS)
        if len(chunks) <= 1:
            prompt = f"Lecture transcript:\n<transcript>\n{text}\n</transcript>\n\n{self.FINAL}"
            return self._client.complete(self.SYSTEM, prompt)
        notes = []
        for i, chunk in enumerate(chunks, 1):
            prompt = (f"Part {i} of {len(chunks)} of one lecture transcript:\n<transcript>\n{chunk}\n"
                      "</transcript>\n\nList the key points, definitions and examples of this part "
                      "as short bullets.")
            notes.append(f"Part {i}:\n" + self._client.complete(self.SYSTEM, prompt, max_tokens=700))
        prompt = ("Notes taken from the consecutive parts of one lecture:\n<notes>\n"
                  + "\n\n".join(notes) + f"\n</notes>\n\n{self.FINAL}")
        return self._client.complete(self.SYSTEM, prompt)


class SummaryService:
    def __init__(self, primary: Summarizer | None, fallback: Summarizer | None = None):
        self._primary = primary
        self._fallback = fallback or ExtractiveSummarizer()

    def summarize(self, raw_transcript: str, lang: str = "en") -> dict:
        text = transcript_to_text(raw_transcript)
        if len(text.split()) < 30:
            raise DomainError("TRANSCRIPT_TOO_SHORT", "Transcript is too short to summarise")
        text = text[:MAX_CHARS]
        note = None
        if self._primary is not None:
            try:
                return {"method": self._primary.name, "summary": self._primary.summarize(text, lang),
                        "words": len(text.split()), "note": None}
            except Exception as e:  # network down, quota, etc. -> degrade gracefully
                note = f"LLM unavailable ({type(e).__name__}); used offline summary"
        return {"method": self._fallback.name, "summary": self._fallback.summarize(text, lang),
                "words": len(text.split()), "note": note}
