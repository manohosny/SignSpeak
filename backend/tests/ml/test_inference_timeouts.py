"""Per-inference watchdog timeouts for every ML engine.

Inference runs via asyncio.to_thread with the GIL-releasing model call inside;
before these timeouts a hung model call would stall that meeting's WS pipeline
indefinitely. Each engine's async wrapper must give up after the config-driven
budget: the str-returning engines resolve to None (the existing failure
contract callers already handle); TTS raises TimeoutError, which the handler's
existing except path converts into the "Audio synthesis failed" WS error.

These tests force MOCK_MODE off per-instance and replace the sync inference
with a slow stub, so no model is loaded or downloaded.
"""

import asyncio
import time
from typing import Any

import numpy as np
import pytest

import app.ml.sign_to_text as s2t_mod
import app.ml.stt as stt_mod
import app.ml.translation as tr_mod
import app.ml.tts as tts_mod
from app.core.config import settings

# Generous wall-clock ceiling: the awaits below must return at the ~0.05s
# budget, not after the 5s stub sleep. CI boxes are slow, hence 2s.
WALL_CLOCK_CEILING = 2.0


def _slow_sync(*_args: Any, **_kwargs: Any) -> str:
    time.sleep(5)
    return "should never be returned"


@pytest.fixture(autouse=True)
def _tiny_budgets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "STT_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(settings, "TRANSLATION_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(settings, "SIGN_TO_TEXT_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(settings, "TTS_TIMEOUT_SECONDS", 0.05)


async def test_stt_transcribe_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = stt_mod.STTEngine()
    engine._loaded = True
    monkeypatch.setattr(stt_mod, "MOCK_MODE", False)
    monkeypatch.setattr(engine, "_transcribe_sync", _slow_sync)

    audio = np.zeros(stt_mod.DEFAULT_SAMPLE_RATE, dtype=np.float32)  # 1s
    start = time.monotonic()
    result = await engine.transcribe(audio)
    assert result is None
    assert time.monotonic() - start < WALL_CLOCK_CEILING


async def test_sign_to_text_translate_keypoints_times_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = s2t_mod.SignToTextEngine()
    engine._loaded = True
    monkeypatch.setattr(s2t_mod, "MOCK_MODE", False)
    monkeypatch.setattr(engine, "_translate_sync", _slow_sync)

    keypoints = np.zeros((20, 133, 2), dtype=np.float32)
    scores = np.ones((20, 133), dtype=np.float32)
    start = time.monotonic()
    result = await engine.translate_keypoints(keypoints, scores)
    assert result is None
    assert time.monotonic() - start < WALL_CLOCK_CEILING


async def test_translation_both_directions_time_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = tr_mod.TranslationEngine()
    engine._loaded = True
    monkeypatch.setattr(tr_mod, "MOCK_MODE", False)
    monkeypatch.setattr(tr_mod, "_cached_translate", _slow_sync)

    start = time.monotonic()
    assert await engine.english_to_gloss("hello there friend") is None
    assert await engine.gloss_to_english("IX HELLO") is None
    assert time.monotonic() - start < 2 * WALL_CLOCK_CEILING


async def test_tts_synthesize_times_out_with_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = tts_mod.TTSEngine()
    engine._loaded = True
    monkeypatch.setattr(tts_mod, "MOCK_MODE", False)
    monkeypatch.setattr(engine, "_synthesize_sync", _slow_sync)

    start = time.monotonic()
    with pytest.raises(asyncio.TimeoutError):
        await engine.synthesize("hello world")
    assert time.monotonic() - start < WALL_CLOCK_CEILING
