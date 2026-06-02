#!/usr/bin/env bash
# Stage the model weights that are NOT auto-downloaded at runtime into their
# persistent Docker volumes. Run ON the VM from the repo root, AFTER `.env`
# exists and the backend image is built (`docker compose build backend`).
#
# Auto-downloaded at first boot (no action here): mBART-50-LoRA + Parakeet
# (pulled from Hugging Face into the model-cache-hf volume).
#
# Staged here:
#   - Kokoro TTS onnx + voices  -> kokoro-models volume (/app/backend/models)
#   - google/mt5-base snapshot  -> signspeak-models volume (~/.signspeak/models/mt5-base)
#   - Uni-Sign checkpoint        -> signspeak-models volume (~/.signspeak/models/uni-sign)
#
# The Uni-Sign checkpoint is released by the Uni-Sign project (not on a public
# CDN we can hardcode). Set UNISIGN_CKPT_URL to its download URL, OR copy the
# file you already have (see README "Option B: scp local files").
set -euo pipefail

KOKORO_ONNX_URL="${KOKORO_ONNX_URL:-https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx}"
KOKORO_VOICES_URL="${KOKORO_VOICES_URL:-https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin}"
UNISIGN_CKPT_URL="${UNISIGN_CKPT_URL:-}"

# Run inside the backend service so the correct (project-prefixed) volumes are
# mounted and downloads land as the appuser that the runtime uses.
docker compose run --rm --no-deps --entrypoint bash backend -c '
  set -euo pipefail
  mkdir -p /home/appuser/.signspeak/models/uni-sign \
           /home/appuser/.signspeak/models/mt5-base \
           /app/backend/models

  echo ">> Kokoro TTS weights..."
  [ -f /app/backend/models/kokoro-v1.0.onnx ] || curl -fL -o /app/backend/models/kokoro-v1.0.onnx "'"$KOKORO_ONNX_URL"'"
  [ -f /app/backend/models/voices-v1.0.bin ]  || curl -fL -o /app/backend/models/voices-v1.0.bin  "'"$KOKORO_VOICES_URL"'"

  echo ">> google/mt5-base snapshot..."
  python -c "from huggingface_hub import snapshot_download; snapshot_download(\"google/mt5-base\", local_dir=\"/home/appuser/.signspeak/models/mt5-base\")"

  if [ -n "'"$UNISIGN_CKPT_URL"'" ]; then
    echo ">> Uni-Sign checkpoint..."
    [ -f /home/appuser/.signspeak/models/uni-sign/how2sign_pose_only_slt.pth ] || \
      curl -fL -o /home/appuser/.signspeak/models/uni-sign/how2sign_pose_only_slt.pth "'"$UNISIGN_CKPT_URL"'"
  else
    echo "!! UNISIGN_CKPT_URL not set — place how2sign_pose_only_slt.pth in the"
    echo "   signspeak-models volume manually (see README Option B)."
  fi
  echo ">> Staged contents:"; ls -lhR /home/appuser/.signspeak/models /app/backend/models
'
