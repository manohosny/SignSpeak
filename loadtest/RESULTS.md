# Load Test Results

Baseline evidence for the questions "how many users can the system handle"
and "what are your average and p95 latency". Reproduce with
[k6-baseline.js](./k6-baseline.js).

## Local baseline — 2026-06-11

Configuration: backend at commit `54a576c`, single uvicorn worker (same as the
production [Dockerfile](../backend/Dockerfile) CMD), ML engines in mock mode
(`*_MOCK_MODE=true`), Apple-silicon Mac, k6 ramping 1 → 50 VUs over 90s.

Command:

```bash
cd backend && STT_MOCK_MODE=true TTS_MOCK_MODE=true \
  uv run uvicorn app.main:app --host 127.0.0.1 --port 8001 --workers 1 &
k6 run -e API_BASE=http://127.0.0.1:8001 -e SKIP_WEB=1 loadtest/k6-baseline.js
```

Result (k6 summary, verbatim):

```
http_reqs......................: 149355 1659.5/s
http_req_failed................: 0.00%  0 out of 149355
http_req_duration..............: avg=19.44ms med=13.36ms p(90)=27.59ms p(95)=98.71ms max=466.58ms
  { endpoint:livez }...........: avg=19.13ms med=13.27ms p(95)=97.97ms
  { endpoint:openapi }.........: avg=19.98ms med=13.79ms p(95)=100.03ms
vus_max........................: 50
checks_succeeded...............: 100.00% (149355/149355)
```

Interpretation:

- **50 concurrent users, 1,659 req/s sustained for 90s, zero failures** on a
  single worker. The HTTP tier is nowhere near the bottleneck.
- avg 19ms / p95 99ms under full load; median 13ms.
- This measures the web/transport tier only. ML inference capacity is bounded
  separately: engines process one inference at a time and WS sessions buffer
  per-connection, so ML load degrades latency per session rather than
  crashing the server (see `backend/app/ws/`).

## Production probe — 2026-06-11

Gentle sequential probes (not a load test) against the live GCP deployment
(`e2-standard-16`, CPU-only, Caddy TLS, https://api.34.10.142.210.sslip.io):

- `GET /api/v1/utils/healthz/live`: 10/10 → HTTP 200.
- Fresh connection: 0.49–0.81s typical (dominated by DNS + TLS handshake +
  RTT to us-central1); outliers 1.9s / 6.6s observed once each (network).
- Reused connection: **165–205ms** per request — i.e. effectively pure
  network RTT; server processing is single-digit ms.
- `GET /api/v1/utils/healthz/ready` → 200 (all ML models warm).

## Multi-replica validation — 2026-06-12

Two backend replicas (:8021/:8022) against one Redis (`redis-server` 8.x) and
one Postgres, mock-ML config:

- Boot surfaced a real gap: the `redis` Python package was **not a backend
  dependency** — both replicas silently fell back to the memory backend.
  Fixed (`uv add redis`); both replicas then logged
  `Redis session backend connected` / `Session backend switched to
  RedisSessionBackend`.
- **Cross-replica presence verified:** a reader joining on :8022 produced
  `user_joined` on the speaker's socket held by :8021 (Redis pub/sub).
- **Per-meeting affinity verified (the documented deployment shape,
  deployment.md):** REST calls on :8021 (login, create, join — replica-
  agnostic), both meeting sockets on :8022 → full flow PASSED
  (`text_message` → speaker + `tts_start`).
- Confirmed limitation, by design: in-meeting counterpart routing resolves
  from the replica-local session, so meetings require proxy affinity;
  without it the speaker lookup misses ("TTS skipped — no speaker
  connected" logged on the other replica). Matches deployment.md's
  affinity requirement.

## Real-model Direction B benchmark (local) — 2026-06-12

Backend with **real Uni-Sign + mBART on Apple-silicon MPS** (STT/TTS mocked;
local checkpoint is the heavier `how2sign_pose_only_slt` — production runs
the lighter WLASL ISLR), driven by `backend/scripts/e2e_sign_to_speech.py`
through the real WS route. Both runs **PASSED** end-to-end (recognized text
delivered, TTS stream start→end).

| Stage | Cold (first inference) | Warm (second run) |
|---|---|---|
| Model load: mBART | 9.4 s | — |
| Model load: Uni-Sign (+mT5) | 107.8 s | — |
| sign_to_text (24-frame segment) | 25.06 s | **11.84 s** |
| gloss_to_english | 19.58 s | **0.46 ms** (LRU cache hit) |
| tts (mock) | 216 ms | 3 ms |

Cold numbers include one-time MPS kernel compilation. The production CPU
deployment with the ISLR checkpoint emits one word per sign with a measured
floor of ~0.4–0.7 s/sign (design spec) — the sentence-SLT decode benchmarked
here generates a full sentence (up to 100 tokens) per segment, hence the
larger figure. Hard ceilings: the per-engine `*_TIMEOUT_SECONDS` watchdogs.

## Running the full test against production

The same script targets production — run it only when you accept putting
50 VUs of synthetic load on the live VM:

```bash
k6 run -e API_BASE=https://api.34.10.142.210.sslip.io \
       -e WEB_BASE=https://dashboard.34.10.142.210.sslip.io \
       -e SKIP_OPENAPI=1 loadtest/k6-baseline.js
```

(`SKIP_OPENAPI=1` because `/api/v1/openapi.json` is intentionally disabled
outside `ENVIRONMENT=local` — see `backend/app/main.py`.)
