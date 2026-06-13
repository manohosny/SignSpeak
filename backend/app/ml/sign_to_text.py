"""Gloss-free Sign-to-Text engine wrapping the Uni-Sign (pose-only) checkpoint.

Direction B (signs -> English): a stream of RTMW COCO-WholeBody-133 keypoints
(2D + per-keypoint score, already normalized by frame [W,H] on the client) is
mapped directly to an English sentence by Uni-Sign's ST-GCN pose encoder +
mt5-base decoder. No glosses, no CTC -- this REPLACES the gloss->English mBART
step for the signing path (mBART stays loaded for Direction A text->gloss).

Key implementation details (mirrors translation.py conventions):
1. Inference only, Apple M1 / MPS, fp32 (the released checkpoint runs bfloat16
   on CUDA; bf16 op support on MPS is uneven, so we force fp32 for correctness).
2. The integrated Uni-Sign repo (sign_to_gloss/Uni-Sign) is imported at load time.
   We import ONLY models.Uni_Sign -- NOT datasets.py, which pulls in decord/cv2
   (video deps we don't need; extraction is browser-side). The model's pose
   preprocessing (load_part_kp / crop_scale) is reimplemented below, copied
   verbatim from datasets.py so the server matches the checkpoint's training
   distribution exactly. See sign_to_gloss/UNI_SIGN_MPS_NOTES.md.
3. The shared model is not thread-safe; model.generate() is guarded by a
   threading.Lock and runs in the asyncio.to_thread pool.
4. Greedy decoding (num_beams=1) on CPU/MPS for acceptable latency.
"""

import asyncio
import contextlib
import copy
import logging
import os
import sys
import threading
import time
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import numpy as np
import numpy.typing as npt

logger = logging.getLogger(__name__)

MOCK_MODE = os.getenv("SIGN_TO_TEXT_MOCK_MODE", "false").lower() == "true"

# COCO-WholeBody-133 is the fixed input topology the checkpoint is bound to.
NUM_KEYPOINTS = 133


def _detect_device(preferred: str = "auto") -> str:
    import torch

    if preferred not in ("auto", "best"):
        if preferred == "cuda" and torch.cuda.is_available():
            return "cuda"
        if preferred == "mps" and torch.backends.mps.is_available():
            return "mps"
        logger.warning(
            "Requested device '%s' not available, falling back to auto", preferred
        )
    if torch.cuda.is_available():
        return "cuda"
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


# -- Pose preprocessing -------------------------------------------------------
# Copied verbatim from sign_to_gloss/Uni-Sign/datasets.py (the model's training
# contract). The browser sends raw RTMW-133 keypoints divided by [W,H]; ALL of
# the part-grouping + body-scale normalization below happens server-side,
# identically to training. See UNI_SIGN_MPS_NOTES.md sections (a)/(b).


def _crop_scale(
    motion: npt.NDArray[Any], thr: float
) -> tuple[npt.NDArray[Any], float, list[float] | None]:
    """Body-bbox normalize to [-1, 1]; returns (result, scale, offset)."""
    result = copy.deepcopy(motion)
    valid_coords = motion[motion[..., 2] > thr][:, :2]
    if len(valid_coords) < 4:
        return np.zeros(motion.shape), 0, None
    xmin, xmax = min(valid_coords[:, 0]), max(valid_coords[:, 0])
    ymin, ymax = min(valid_coords[:, 1]), max(valid_coords[:, 1])
    scale = max(xmax - xmin, ymax - ymin)  # ratio = 1
    if scale == 0:
        return np.zeros(motion.shape), 0, None
    xs = (xmin + xmax - scale) / 2
    ys = (ymin + ymax - scale) / 2
    result[..., :2] = (motion[..., :2] - [xs, ys]) / scale
    result[..., :2] = (result[..., :2] - 0.5) * 2
    result = np.clip(result, -1, 1)
    result[result[..., 2] <= thr] = 0
    return result, scale, [xs, ys]


def _load_part_kp(
    skeletons: npt.NDArray[Any], confs: npt.NDArray[Any]
) -> dict[str, Any]:
    """Split 133 keypoints into the 4 ST-GCN streams (body/left/right/face_all).

    skeletons: (T, 1, 133, 2)   confs: (T, 1, 133)   (person axis = 1)
    Returns {part: torch.FloatTensor (T, n_part, 3)}.
    """
    import torch

    thr = 0.3
    kps_with_scores: dict[str, Any] = {}
    scale = None
    for part in ["body", "left", "right", "face_all"]:
        kps, confidences = [], []
        for skeleton, conf in zip(skeletons, confs, strict=False):
            skeleton = skeleton[0]
            conf = conf[0]
            if part == "body":
                hand_kp2d = skeleton[[0] + list(range(3, 11)), :]
                confidence = conf[[0] + list(range(3, 11))]
            elif part == "left":
                hand_kp2d = skeleton[91:112, :]
                hand_kp2d = hand_kp2d - hand_kp2d[0, :]
                confidence = conf[91:112]
            elif part == "right":
                hand_kp2d = skeleton[112:133, :]
                hand_kp2d = hand_kp2d - hand_kp2d[0, :]
                confidence = conf[112:133]
            else:  # face_all
                idx = list(range(23, 23 + 17))[::2] + list(range(83, 83 + 8)) + [53]
                hand_kp2d = skeleton[idx, :]
                hand_kp2d = hand_kp2d - hand_kp2d[-1, :]
                confidence = conf[idx]
            kps.append(hand_kp2d)
            confidences.append(confidence)
        kps_arr = np.stack(kps, axis=0)
        conf_arr = np.stack(confidences, axis=0)
        if part == "body":
            result, scale, _ = _crop_scale(
                np.concatenate([kps_arr, conf_arr[..., None]], axis=-1), thr
            )
        else:
            assert scale is not None
            result = np.concatenate([kps_arr, conf_arr[..., None]], axis=-1)
            if scale == 0:
                result = np.zeros(result.shape)
            else:
                result[..., :2] = result[..., :2] / scale
                result = np.clip(result, -1, 1)
                result[result[..., 2] <= thr] = 0
        kps_with_scores[part] = torch.tensor(result)
    return kps_with_scores


def _collate_single(kps_with_scores: dict[str, Any]) -> dict[str, Any]:
    """B=1 collate (no padding); builds the per-stream batch + attention_mask."""
    import torch

    src_input: dict[str, Any] = {}
    seq_len = 0
    for key, val in kps_with_scores.items():
        src_input[key] = val[None].float()  # (1, T, V, 3)
        seq_len = val.shape[0]
    mask = (torch.ones(seq_len) + 7)[None]
    src_input["attention_mask"] = (mask != 0).long()
    return src_input


def _resolve_repo_dir(repo_dir: str) -> str:
    """Resolve the vendored Uni-Sign path independent of the process cwd.

    A relative path (the config default "sign_to_gloss/Uni-Sign") is anchored at
    the SignSpeak project root — parents[3] of this file
    (backend/app/ml/sign_to_text.py -> project root) — so it works whether the
    server is launched from backend/ or the repo root.
    """
    expanded = os.path.expanduser(repo_dir)
    if os.path.isabs(expanded):
        return expanded
    project_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..")
    )
    return os.path.join(project_root, expanded)


@contextlib.contextmanager
def _uni_sign_path(repo_dir: str) -> Iterator[None]:
    """Make the vendored Uni-Sign repo importable without polluting sys.path.

    The repo root holds generically-named modules (datasets.py / utils.py /
    config.py / models.py). Inserting it at sys.path[0] shadowed real installed
    libraries process-wide and permanently -- e.g. NeMo's `import datasets`
    (HuggingFace) resolved to Uni-Sign's datasets.py, which chained to
    `import deepspeed` and broke STT loading (a hard-to-trace, concurrency-timed
    failure during the startup model-load gather).

    Fix on two axes:
      * APPEND (not insert) so installed packages always win -- a concurrent
        `import datasets` keeps resolving to the real package regardless of
        timing. Uni-Sign's uniquely-named modules (models, stgcn_layers, ...)
        still resolve because nothing else provides them.
      * REMOVE on exit so the repo's generic names never linger on the path.
        The modules needed for inference are cached in sys.modules by then, and
        inference performs no further Uni-Sign imports.
    """
    added = repo_dir not in sys.path
    if added:
        sys.path.append(repo_dir)
    try:
        yield
    finally:
        if added and repo_dir in sys.path:
            sys.path.remove(repo_dir)


def _subsample_indices(duration: int, max_frames: int) -> npt.NDArray[Any]:
    """Deterministic uniform subsample when over the model's T cap."""
    if duration > max_frames:
        return np.linspace(0, duration - 1, max_frames).round().astype(int)
    return np.arange(duration)


# -- Engine -------------------------------------------------------------------


class SignToTextEngine:
    """Wraps Uni-Sign (pose-only) for keypoints -> English translation.

    Lifecycle:
        engine = SignToTextEngine()
        engine.load_model(repo_dir, checkpoint, mt5_dir)
        text = await engine.translate_keypoints(keypoints, scores)
    """

    def __init__(self) -> None:
        self._model: Any = None  # Uni_Sign model (untyped vendored lib)
        self._device: str = "cpu"
        self._num_beams: int = 1
        self._max_new_tokens: int = 100
        self._max_frames: int = 256
        self._loaded = False
        # Serializes generate() across asyncio.to_thread workers (model is shared).
        self._inference_lock = threading.Lock()

    def load_model(
        self,
        repo_dir: str,
        checkpoint: str,
        mt5_dir: str,
        device: str = "auto",
        num_beams: int = 1,
        max_new_tokens: int = 100,
        max_frames: int = 256,
        dtype: str = "fp32",
    ) -> None:
        """Load the Uni-Sign pose-only checkpoint. Call once at app startup."""
        self._max_frames = max_frames
        self._max_new_tokens = max_new_tokens

        if MOCK_MODE:
            logger.info("Sign-to-text running in MOCK MODE -- no model loaded")
            self._loaded = True
            return


        import torch

        self._device = _detect_device(device)
        # CPU/MPS: greedy for latency (beam search too slow / uneven op support).
        self._num_beams = num_beams
        if self._device in ("cpu", "mps") and num_beams > 1:
            logger.warning(
                "%s device with num_beams=%d; downgrading to greedy (1)",
                self._device,
                num_beams,
            )
            self._num_beams = 1

        repo_dir = _resolve_repo_dir(repo_dir)
        # Import under a scoped, append-only path so the repo's generically-named
        # modules can't shadow installed libraries (see _uni_sign_path).
        with _uni_sign_path(repo_dir):
            # Point the vendored repo's config.mt5_path at our mt5-base snapshot
            # BEFORE importing models (models.py does `from config import mt5_path`).
            import config as unisign_config  # type: ignore

            unisign_config.mt5_path = os.path.expanduser(mt5_dir)
            from models import Uni_Sign  # type: ignore

        logger.info("Loading Uni-Sign on %s...", self._device)
        start = time.time()

        model_args = SimpleNamespace(
            dataset="How2Sign",
            rgb_support=False,
            hidden_dim=256,
            max_length=max_frames,
            label_smoothing=0.2,
            task="SLT",
        )
        model = Uni_Sign(args=model_args)
        # State dict is plain tensors -> weights_only=True is safe and avoids the
        # arbitrary-unpickle code path.
        state = torch.load(checkpoint, map_location="cpu", weights_only=True)["model"]
        # assign=True replaces module params with the checkpoint tensors directly.
        # This MATERIALIZES any `meta`-device params that transformers' lazy
        # (low_cpu_mem_usage / accelerate) init may leave behind -- which happens
        # when mt5 and the mBART translation model run from_pretrained concurrently
        # during the startup lifespan. Without it, a later .to(device) raises
        # "Cannot copy out of meta tensor". strict=True guarantees every param is
        # present in the checkpoint, so the assignment is total.
        ret = model.load_state_dict(state, strict=True, assign=True)
        if ret.missing_keys or ret.unexpected_keys:
            logger.warning(
                "Uni-Sign load: %d missing, %d unexpected keys",
                len(ret.missing_keys),
                len(ret.unexpected_keys),
            )
        model.eval()
        model.float()  # fp32 on MPS (NOT bfloat16)
        if self._device != "cpu":
            model.to(torch.device(self._device))
        self._model = model

        logger.info(
            "Sign-to-text model loaded in %.1fs (%s)", time.time() - start, self._device
        )
        self._loaded = True

    async def translate_keypoints(
        self,
        keypoints: npt.NDArray[Any],
        scores: npt.NDArray[Any],
    ) -> str | None:
        """Translate a keypoint clip to English (async).

        keypoints: (T, 133, 2) float, normalized [0,1] by frame [W,H].
        scores:    (T, 133)    float confidence in [0,1].
        Returns None on empty/failed output.
        """
        if not self._loaded:
            raise RuntimeError("Sign-to-text model not loaded. Call load_model() first.")
        if MOCK_MODE:
            return "Mock: hello how are you"
        from app.core.config import settings

        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._translate_sync, keypoints, scores),
                timeout=settings.SIGN_TO_TEXT_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            from app.core.metrics import ML_INFERENCE_TIMEOUTS

            ML_INFERENCE_TIMEOUTS.labels(engine="sign_to_text").inc()
            logger.error(
                "Sign-to-text inference timed out after %.1fs — dropping segment",
                settings.SIGN_TO_TEXT_TIMEOUT_SECONDS,
            )
            return None

    def _translate_sync(self, keypoints: npt.NDArray[Any], scores: npt.NDArray[Any]) -> str | None:
        import torch

        try:
            keypoints = np.asarray(keypoints, dtype=np.float32)
            scores = np.asarray(scores, dtype=np.float32)
            if keypoints.ndim != 3 or keypoints.shape[1:] != (NUM_KEYPOINTS, 2):
                logger.error("Bad keypoints shape %s, expected (T,133,2)", keypoints.shape)
                return None

            duration = keypoints.shape[0]
            if duration == 0:
                return None
            idx = _subsample_indices(duration, self._max_frames)
            # Add the person axis (T, 1, 133, *) that _load_part_kp expects.
            skeletons = keypoints[idx][:, None, :, :]
            confs = scores[idx][:, None, :]

            kps_with_scores = _load_part_kp(skeletons, confs)
            src_input = _collate_single(kps_with_scores)
            src_input = {
                k: (v.to(self._device) if isinstance(v, torch.Tensor) else v)
                for k, v in src_input.items()
            }
            tgt_input = {"gt_sentence": [""], "gt_gloss": [""]}

            with self._inference_lock, torch.no_grad():
                stack_out = self._model(src_input, tgt_input)
                output = self._model.generate(
                    stack_out,
                    max_new_tokens=self._max_new_tokens,
                    num_beams=self._num_beams,
                )
            text = self._model.mt5_tokenizer.batch_decode(
                output, skip_special_tokens=True
            )[0].strip()
            return text if text else None
        except Exception as e:
            logger.error("Sign-to-text inference error: %s", e, exc_info=True)
            return None

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    @property
    def device(self) -> str:
        return self._device

    def unload(self) -> None:
        if self._model is not None:
            del self._model
            self._model = None
        self._loaded = False
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        logger.info("Sign-to-text model unloaded")


# -- Singleton ----------------------------------------------------------------
sign_to_text_engine = SignToTextEngine()
