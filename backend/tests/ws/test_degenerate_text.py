"""Direct unit tests for the degenerate-output detector.

_is_degenerate_text is the post-inference hallucination gate — it suppresses
the single-token repetition Uni-Sign emits on weak/short input ("Oh, yeah,
yeah, yeah, ...") before it is spoken to the speaker. It previously had only
indirect coverage through the keypoint-handler tests.
"""

import pytest

from app.ws.handlers import _is_degenerate_text


@pytest.mark.parametrize(
    "text",
    [
        # The motivating real-world failure: one token dominating the output.
        "Oh, yeah, yeah, yeah, yeah, yeah, yeah",
        "yeah yeah yeah yeah yeah yeah",
        # Case-insensitive: same token in mixed case still counts together.
        "Yeah YEAH yeah YEAH yeah yeah",
        # Dominant token among minor variation (6 of 8 > 50%).
        "no no no no no no way sir",
    ],
)
def test_degenerate_repetition_is_flagged(text: str) -> None:
    assert _is_degenerate_text(text) is True


@pytest.mark.parametrize(
    "text",
    [
        # Normal sentences must pass through untouched.
        "I want to bake a cake today",
        "hello how are you doing this morning",
        # Short outputs (< 6 words) are never flagged — a legitimate short
        # answer like "yes yes" must not be suppressed.
        "yes yes",
        "no no no no no",
        "",
        # Exactly at the 50% boundary is NOT degenerate (strict >).
        "yeah yeah yeah stop it now",
        # Repetition spread across two tokens, neither dominant.
        "yes no yes no yes no yes no",
    ],
)
def test_normal_or_short_text_is_not_flagged(text: str) -> None:
    assert _is_degenerate_text(text) is False
