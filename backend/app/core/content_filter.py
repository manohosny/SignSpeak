"""Output content filter — PII redaction + profanity blocking.

Applied (when CONTENT_FILTER_ENABLED) to every text the pipeline emits to a
user or persists: STT transcripts, recognized sign sentences, and reader text
messages — before broadcast, before the DB write, and before TTS speaks it.

This is a guardrail, not a moderation system: the meeting is a private,
authenticated 1:1 channel, so the goal is to stop the pipeline from
*amplifying* sensitive strings (speaking a misheard credit-card number aloud,
persisting an email address verbatim) rather than to police conversation.
Policy summary lives in SECURITY.md → Content Safety.
"""

import re
from dataclasses import dataclass

from app.core.metrics import CONTENT_REDACTIONS

_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
# 13-19 digits with optional spaces/dashes between groups — card-shaped.
_CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")
# International-ish phone: optional +, 9-15 digits with separators.
_PHONE = re.compile(r"(?<!\w)\+?\d[\d ().-]{7,14}\d(?!\w)")

# Deliberately small and severe — slur-level only. Casual swearing in a
# private 1:1 conversation is the participants' business; these are words the
# product should never voice through TTS regardless of context.
_PROFANITY = frozenset(
    {
        "nigger",
        "nigga",
        "faggot",
        "kike",
        "spic",
        "chink",
        "tranny",
        "retard",
    }
)
_WORD = re.compile(r"[A-Za-z']+")

PII_PLACEHOLDER = "[redacted]"
PROFANITY_PLACEHOLDER = "[censored]"


@dataclass(frozen=True)
class FilterResult:
    text: str
    pii_redactions: int
    profanity_redactions: int

    @property
    def altered(self) -> bool:
        return bool(self.pii_redactions or self.profanity_redactions)


def filter_text(text: str) -> FilterResult:
    """Redact PII patterns and censor blocklisted words.

    Order matters: digits first (card before phone, so a card number is not
    half-eaten by the looser phone pattern), then emails, then words.
    """
    pii = 0

    def _count_sub(pattern: re.Pattern[str], s: str) -> str:
        nonlocal pii
        s, n = pattern.subn(PII_PLACEHOLDER, s)
        pii += n
        return s

    out = _count_sub(_CARD, text)
    out = _count_sub(_PHONE, out)
    out = _count_sub(_EMAIL, out)

    profanity = 0

    def _censor(match: re.Match[str]) -> str:
        nonlocal profanity
        if match.group(0).lower() in _PROFANITY:
            profanity += 1
            return PROFANITY_PLACEHOLDER
        return match.group(0)

    # Whole-word, case-insensitive scan; non-matching words keep their casing.
    out = _WORD.sub(_censor, out)

    if pii:
        CONTENT_REDACTIONS.labels(kind="pii").inc(pii)
    if profanity:
        CONTENT_REDACTIONS.labels(kind="profanity").inc(profanity)
    return FilterResult(text=out, pii_redactions=pii, profanity_redactions=profanity)


def apply_output_filter(text: str) -> str:
    """Settings-aware convenience wrapper used at the pipeline's exit points."""
    from app.core.config import settings

    if not settings.CONTENT_FILTER_ENABLED:
        return text
    return filter_text(text).text
