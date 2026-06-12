"""Unit tests for the output content filter (PII redaction + profanity).

Policy: SECURITY.md -> Content Safety. Applied at the pipeline's exit points
(transcripts, sign sentences, text messages) before broadcast/persist/TTS.
"""

import pytest

from app.core.config import settings
from app.core.content_filter import (
    PII_PLACEHOLDER,
    PROFANITY_PLACEHOLDER,
    apply_output_filter,
    filter_text,
)


class TestPiiRedaction:
    def test_email_redacted(self) -> None:
        out = filter_text("contact me at john.doe+spam@example.co.uk please")
        assert out.text == f"contact me at {PII_PLACEHOLDER} please"
        assert out.pii_redactions == 1

    def test_phone_redacted(self) -> None:
        out = filter_text("call +1 (415) 555-0199 tomorrow")
        assert PII_PLACEHOLDER in out.text
        assert "555" not in out.text
        assert out.pii_redactions == 1

    def test_card_number_redacted(self) -> None:
        out = filter_text("my card is 4111 1111 1111 1111 thanks")
        assert PII_PLACEHOLDER in out.text
        assert "4111" not in out.text

    def test_multiple_pii_counted(self) -> None:
        out = filter_text("a@b.com and c@d.org")
        assert out.pii_redactions == 2


class TestProfanity:
    def test_slur_censored_case_insensitive(self) -> None:
        out = filter_text("you Retard stop")
        assert out.text == f"you {PROFANITY_PLACEHOLDER} stop"
        assert out.profanity_redactions == 1

    def test_substring_of_clean_word_not_censored(self) -> None:
        # "retardant" contains a blocklisted word as a substring — whole-word
        # matching must leave it alone.
        out = filter_text("fire retardant material")
        assert out.text == "fire retardant material"
        assert out.profanity_redactions == 0


class TestPassthrough:
    @pytest.mark.parametrize(
        "text",
        [
            "I want to bake a cake today",
            "meet me at 5 pm",  # short digits — not phone-shaped
            "",
        ],
    )
    def test_clean_text_unaltered(self, text: str) -> None:
        out = filter_text(text)
        assert out.text == text
        assert not out.altered


class TestSettingsGate:
    def test_disabled_flag_bypasses_filter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "CONTENT_FILTER_ENABLED", False)
        assert apply_output_filter("a@b.com") == "a@b.com"

    def test_enabled_flag_applies_filter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "CONTENT_FILTER_ENABLED", True)
        assert apply_output_filter("a@b.com") == PII_PLACEHOLDER
