"""Tests for app.ml.sign_to_text — runs entirely in MOCK_MODE (no model download).

SIGN_TO_TEXT_MOCK_MODE must be set before the module is imported so the
module-level MOCK_MODE constant is True.
"""

import asyncio
import os

# Set env var first (works when module hasn't been imported yet).
os.environ["SIGN_TO_TEXT_MOCK_MODE"] = "true"

import numpy as np  # noqa: E402
import pytest  # noqa: E402

import app.ml.sign_to_text as _s2t_mod  # noqa: E402

# Patch module-level MOCK_MODE in case the module was already imported elsewhere.
_s2t_mod.MOCK_MODE = True

from app.ml.sign_to_text import (  # noqa: E402
    NUM_KEYPOINTS,
    SignToTextEngine,
    _crop_scale,
    _load_part_kp,
    _subsample_indices,
    _uni_sign_path,
    sign_to_text_engine,
)


def _kps(t: int = 30):
    """Synthetic (keypoints, scores) clip of T frames."""
    rng = np.random.default_rng(0)
    keypoints = rng.uniform(0.2, 0.8, size=(t, NUM_KEYPOINTS, 2)).astype(np.float32)
    scores = rng.uniform(0.5, 0.99, size=(t, NUM_KEYPOINTS)).astype(np.float32)
    return keypoints, scores


def _ensure_loaded() -> None:
    if not sign_to_text_engine.is_loaded:
        sign_to_text_engine.load_model(repo_dir="", checkpoint="", mt5_dir="")


class TestMockMode:
    def setup_method(self) -> None:
        _ensure_loaded()

    def test_mock_translate_keypoints(self) -> None:
        kp, sc = _kps()
        result = asyncio.run(sign_to_text_engine.translate_keypoints(kp, sc))
        assert result == "Mock: hello how are you"

    def test_mock_translate_is_string(self) -> None:
        kp, sc = _kps(10)
        result = asyncio.run(sign_to_text_engine.translate_keypoints(kp, sc))
        assert isinstance(result, str) and len(result) > 0


class TestLoadAndUnload:
    def test_load_sets_is_loaded(self) -> None:
        engine = SignToTextEngine()
        assert not engine.is_loaded
        engine.load_model(repo_dir="", checkpoint="", mt5_dir="")
        assert engine.is_loaded

    def test_unload_clears_state(self) -> None:
        engine = SignToTextEngine()
        engine.load_model(repo_dir="", checkpoint="", mt5_dir="")
        engine.unload()
        assert not engine.is_loaded

    def test_load_model_is_idempotent_in_mock(self) -> None:
        engine = SignToTextEngine()
        engine.load_model(repo_dir="", checkpoint="", mt5_dir="")
        engine.load_model(repo_dir="", checkpoint="", mt5_dir="")
        assert engine.is_loaded

    def test_load_records_caps(self) -> None:
        engine = SignToTextEngine()
        engine.load_model(
            repo_dir="", checkpoint="", mt5_dir="", max_frames=128, max_new_tokens=50
        )
        assert engine._max_frames == 128
        assert engine._max_new_tokens == 50


class TestNotLoadedGuard:
    def test_translate_raises_when_not_loaded(self) -> None:
        engine = SignToTextEngine()
        kp, sc = _kps(5)
        with pytest.raises(RuntimeError, match="not loaded"):
            asyncio.run(engine.translate_keypoints(kp, sc))


class TestConstantsAndDevice:
    def test_num_keypoints(self) -> None:
        assert NUM_KEYPOINTS == 133

    def test_device_default_cpu(self) -> None:
        engine = SignToTextEngine()
        assert engine.device == "cpu"


class TestPreprocessing:
    """The pose preprocessing is pure NumPy/torch — exercise it without a model."""

    def test_subsample_caps_at_max_frames(self) -> None:
        idx = _subsample_indices(1000, 256)
        assert len(idx) == 256
        assert idx[0] == 0 and idx[-1] == 999
        # deterministic + monotonic
        assert list(idx) == sorted(idx)

    def test_subsample_passthrough_when_short(self) -> None:
        idx = _subsample_indices(40, 256)
        assert list(idx) == list(range(40))

    def test_crop_scale_returns_scale(self) -> None:
        rng = np.random.default_rng(1)
        motion = np.concatenate(
            [rng.uniform(0, 1, (8, 9, 2)), np.ones((8, 9, 1))], axis=-1
        )
        result, scale, _ = _crop_scale(motion, thr=0.3)
        assert result.shape == motion.shape
        assert scale > 0
        assert result.min() >= -1 and result.max() <= 1

    def test_load_part_kp_stream_shapes(self) -> None:
        kp, sc = _kps(12)
        skeletons = kp[:, None, :, :]   # (T, 1, 133, 2)
        confs = sc[:, None, :]          # (T, 1, 133)
        parts = _load_part_kp(skeletons, confs)
        assert set(parts.keys()) == {"body", "left", "right", "face_all"}
        # Verified joint counts (UNI_SIGN_MPS_NOTES item b).
        assert parts["body"].shape == (12, 9, 3)
        assert parts["left"].shape == (12, 21, 3)
        assert parts["right"].shape == (12, 21, 3)
        assert parts["face_all"].shape == (12, 18, 3)


class TestUniSignPathIsolation:
    """The vendored Uni-Sign repo root has generically-named modules
    (datasets.py / utils.py / config.py). Putting it on sys.path at position 0
    shadowed real installed libraries process-wide -- e.g. NeMo's
    `import datasets` (HuggingFace) resolved to Uni-Sign's datasets.py, which
    chained to `import deepspeed` and broke STT loading. The path helper must
    NOT shadow installed packages and must clean up after itself.
    """

    import importlib.util
    import sys as _sys

    def test_does_not_shadow_installed_datasets(self, tmp_path):
        import importlib.util

        # A fake repo whose datasets.py would explode if it were ever imported.
        (tmp_path / "datasets.py").write_text("raise RuntimeError('shadowed!')")
        (tmp_path / "myuniqmod.py").write_text("VALUE = 42")
        with _uni_sign_path(str(tmp_path)):
            # Installed `datasets` (HF) must still win over the repo's datasets.py.
            spec = importlib.util.find_spec("datasets")
            assert spec is not None and "site-packages" in (spec.origin or ""), (
                "Uni-Sign repo must not shadow the installed datasets package"
            )
            # ...but a uniquely-named repo module IS importable inside the context.
            assert importlib.util.find_spec("myuniqmod") is not None

    def test_cleans_up_sys_path(self, tmp_path):
        import sys

        before = list(sys.path)
        with _uni_sign_path(str(tmp_path)):
            assert str(tmp_path) in sys.path
        assert str(tmp_path) not in sys.path
        assert sys.path == before

    def test_nested_or_preexisting_entry_not_double_removed(self, tmp_path):
        import sys

        sys.path.append(str(tmp_path))  # pre-existing entry we must NOT remove
        try:
            with _uni_sign_path(str(tmp_path)):
                assert str(tmp_path) in sys.path
            assert str(tmp_path) in sys.path, "must not remove a pre-existing entry"
        finally:
            sys.path.remove(str(tmp_path))


@pytest.mark.skipif(
    os.getenv("RUN_ML_INTEGRATION", "false").lower() != "true",
    reason="Set RUN_ML_INTEGRATION=true to exercise the real Uni-Sign checkpoint on MPS",
)
class TestRealModelIntegration:
    """Loads the real checkpoint and runs one synthetic clip end-to-end on MPS."""

    def test_real_translate_runs(self) -> None:
        os.environ["SIGN_TO_TEXT_MOCK_MODE"] = "false"
        _s2t_mod.MOCK_MODE = False
        from app.core.config import settings

        engine = SignToTextEngine()
        engine.load_model(
            repo_dir=settings.SIGN_TO_TEXT_REPO_DIR,
            checkpoint=os.path.expanduser(settings.SIGN_TO_TEXT_CHECKPOINT),
            mt5_dir=os.path.expanduser(settings.SIGN_TO_TEXT_MT5_DIR),
            device=settings.SIGN_TO_TEXT_DEVICE,
        )
        kp, sc = _kps(48)
        result = asyncio.run(engine.translate_keypoints(kp, sc))
        # Synthetic input -> output not meaningful, but the path must run + decode.
        assert result is None or isinstance(result, str)
        engine.unload()
