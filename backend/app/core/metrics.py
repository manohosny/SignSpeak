"""Prometheus counters for ML-pipeline quality events.

HTTP latency/error/throughput histograms come from
prometheus-fastapi-instrumentator (wired in app.main); these counters cover
what the checklist calls "model degradation detection": how often the
pipeline's defensive gates fire. A rising gated/degenerate rate is the
earliest signal of pose-quality or model regression — watch
rate(signspeak_sign_segments_gated_total[5m]) after threshold changes.
"""

from prometheus_client import Counter

SIGN_SEGMENTS_GATED = Counter(
    "signspeak_sign_segments_gated_total",
    "Sign segments rejected before/after inference by quality gates",
    labelnames=("reason",),  # too_short | low_confidence | empty_or_degenerate
)

ML_INFERENCE_TIMEOUTS = Counter(
    "signspeak_ml_inference_timeouts_total",
    "Inference calls killed by the per-engine watchdog timeout",
    labelnames=("engine",),  # stt | translation | sign_to_text | tts
)

CONTENT_REDACTIONS = Counter(
    "signspeak_content_redactions_total",
    "Output texts altered by the content filter before reaching a user",
    labelnames=("kind",),  # pii | profanity
)

MESSAGE_FLAGS = Counter(
    "signspeak_message_flags_total",
    "User-submitted 'wrong translation' flags on persisted messages",
)
