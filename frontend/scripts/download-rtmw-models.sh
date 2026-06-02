#!/usr/bin/env bash
# Download the RTMW (lightweight-mode) ONNX models for browser-side pose
# extraction (Direction B). These match the Phase-0 server extractor exactly, so
# the keypoints the browser produces are in the distribution Uni-Sign expects.
#
# ~143MB total; gitignored. Run once after checkout:
#   bash frontend/scripts/download-rtmw-models.sh
set -euo pipefail

DEST="$(cd "$(dirname "$0")/.." && pwd)/public/models/rtmw"
mkdir -p "$DEST"
cd "$DEST"

DET="https://download.openmmlab.com/mmpose/v1/projects/rtmposev1/onnx_sdk/yolox_tiny_8xb8-300e_humanart-6f3252f9.zip"
POSE="https://download.openmmlab.com/mmpose/v1/projects/rtmw/onnx_sdk/rtmw-dw-l-m_simcc-cocktail14_270e-256x192_20231122.zip"

echo "Downloading YOLOX-tiny detector..."
curl -sSL "$DET" -o det.zip && unzip -oq det.zip -d det
find det -name "*.onnx" -exec cp {} yolox_tiny.onnx \;

echo "Downloading RTMW-DW-L-M pose..."
curl -sSL "$POSE" -o pose.zip && unzip -oq pose.zip -d pose
find pose -name "*.onnx" -exec cp {} rtmw_dw_l_m.onnx \;

rm -rf det pose det.zip pose.zip
echo "Done:"
ls -lh "$DEST"/*.onnx
