# SignSpeak

A real-time accessibility platform for communication between a hearing **speaker** and a Deaf/HoH **reader**, in both directions:

- **Direction A (speech → sign):** the speaker talks; their speech is transcribed live, translated to sign gloss, and rendered by a 3D signing avatar (plus live captions). Reader replies are spoken aloud via TTS.
- **Direction B (sign → speech):** the reader signs at their camera; pose keypoints are extracted **in the browser** (video never leaves the device), streamed over WebSocket, recognized sign-by-sign on the server, and spoken to the speaker via TTS.

## Team Members

| Name | ID | Program |
|------|----|---------|
| Abdulrahman Mohamed Hosny | 202200066 | DSAI |
| Mariam Hani | 202200903 | DSAI |
| Youssef El Dawayaty | 202201209 | DSAI |

**Supervisor:** Dr. Mohamed Sami Rakha

## Problem Statement

Communication between Deaf/Hard-of-Hearing (Deaf/HoH) signers and hearing
non-signers is routinely blocked by the absence of a shared language. Human
interpreters are scarce, expensive, and not available on demand, while generic
captioning only solves one direction (speech → text) and ignores the signer
entirely. SignSpeak addresses this by providing **real-time, two-way**
translation in a single browser-based meeting: a hearing speaker's speech is
transcribed and rendered as sign by a 3D avatar, and a signer's signs are
recognized from their webcam and spoken aloud — with the signer's video never
leaving their device.

## Features

- **Speech-to-Text (STT)** — Live transcription using NVIDIA Parakeet TDT 0.6B via NeMo
- **Gloss translation** — English ↔ ASL pseudo-gloss via a custom mBART-50 LoRA fine-tune (`manohonsy/asl-mbart-50-lora`)
- **3D signing avatar** — CWASA/SiGML avatar with a ~1,168-sign lexicon and fingerspelling fallback
- **Sign recognition (Direction B)** — Browser-side YOLOX + RTMW pose extraction (ONNX web worker) → WebSocket keypoint streaming → Uni-Sign (WLASL ISLR checkpoint) recognition with rest-pose/motion-pause segmentation
- **Text-to-Speech (TTS)** — Message vocalization using Kokoro 82M ONNX
- **Real-time meetings** — WebSocket-based communication with shareable meeting codes
- **Role-based participation** — Speaker and reader roles with tailored UIs
- **Meeting lifecycle** — Create, join, and manage meetings (waiting → active → ended)
- **User authentication** — JWT-based auth with email password recovery
- **Dark mode** — Full theme support across the app

## System Architecture

SignSpeak is a FastAPI backend + React frontend joined by a single WebSocket per
meeting that multiplexes JSON control frames and binary audio/keypoint frames.
ML runs on our own server; the **only** data that leaves the reader's browser is
133 pose keypoints (never video).

```mermaid
flowchart LR
    subgraph Client["Browser (client)"]
        Mic["Speaker mic"]
        Cam["Reader webcam"]
        Worker["ONNX web worker<br/>YOLOX + RTMW pose"]
        Cap["Live captions"]
        Avatar["3D signing avatar"]
        Spk["Speaker audio out"]
    end

    subgraph Server["FastAPI server"]
        WS["WebSocket hub"]
        STT["STT · Parakeet"]
        TR["Gloss translate<br/>mBART-50 LoRA"]
        SEG["Segmentation<br/>rest-pose / motion-pause"]
        UNI["Sign recognition · Uni-Sign"]
        TTS["TTS · Kokoro"]
        DB[("PostgreSQL")]
    end

    Mic -->|"audio frames"| WS
    WS --> STT --> TR
    TR -->|"gloss"| Avatar
    TR -->|"captions"| Cap

    Cam --> Worker
    Worker -->|"133 keypoints only"| WS
    WS --> SEG --> UNI
    UNI -->|"gloss"| WS
    UNI -->|"English text"| TTS
    TTS -->|"audio"| Spk

    WS --- DB
```

**Direction A (speech → sign):** mic audio → STT → gloss translation → 3D avatar
+ live captions.
**Direction B (sign → speech):** webcam → in-browser pose extraction → keypoints
over WebSocket → segmentation → sign recognition → English → TTS.

## Technologies Used

| Layer | Technology |
|-------|-----------|
| **Backend** | FastAPI, SQLModel, PostgreSQL, Alembic |
| **Frontend** | React 19, TypeScript, TanStack Router/Query, Tailwind CSS, shadcn/ui |
| **ML/AI** | NVIDIA Parakeet TDT 0.6B (STT), mBART-50 LoRA (gloss translation), Uni-Sign + RTMW/YOLOX ONNX (sign recognition), Kokoro 82M ONNX (TTS), PyTorch |
| **Real-time** | WebSockets (FastAPI native) — JSON control + binary keypoint/audio frames |
| **Infrastructure** | Docker Compose, Traefik (local) / Caddy (production), Nginx |
| **Testing** | Pytest (backend), Playwright (E2E), Vitest (unit), k6 (load) |

## Prerequisites

- **Docker & Docker Compose** (recommended for full-stack)
- **Python 3.10+** with [uv](https://docs.astral.sh/uv/) package manager
- **Bun** (or Node.js) for the frontend
- **PostgreSQL 12+** (or a cloud provider like Supabase)

> **macOS (Apple Silicon) Note:** When running `uv sync --extra ml`, uv will automatically resolve a compatible version of `kaldialign` (≥0.9.2) for ARM64. If you hit a platform error, ensure the root `pyproject.toml` includes the `kaldialign>=0.9.2` override (already included in this repo).

## Quick Start (Docker)

```bash
# 1. Clone the repository
git clone git@github.com:manohosny/SignSpeak.git
cd SignSpeak

# 2. Configure environment (the repo ships .env.example, not .env)
cp .env.example .env   # Edit: database URL, SECRET_KEY, superuser credentials

# Optional: run without downloading any ML models (fastest first boot —
# this is exactly what CI does in .github/workflows/test-docker-compose.yml)
cat >> .env <<'EOF'
STT_MOCK_MODE=true
TRANSLATION_MOCK_MODE=true
TTS_MOCK_MODE=true
SIGN_TO_TEXT_MOCK_MODE=true
EOF

# 3. Start all services
docker compose watch
```

This starts:

| Service | URL |
|---------|-----|
| Backend API | http://localhost:8000 |
| API Docs (Swagger) | http://localhost:8000/docs |
| Frontend | http://localhost:5173 |
| Mailcatcher (email testing) | http://localhost:1080 |
| Traefik Dashboard | http://localhost:8090 |

## Local Development (without Docker)

### Backend

```bash
cd backend

# Option A — without ML models (faster, mock mode)
uv sync

# Option B — with ML models (STT + TTS, ~2GB download)
uv sync --extra ml
```

> **Important:** `uv sync` and `uv sync --extra ml` are mutually exclusive syncs — running plain `uv sync` after `uv sync --extra ml` will **remove** the ML packages (`torch`, `kokoro-onnx`, etc.). Pick one and stick with it. Use `STT_MOCK_MODE=true` / `TTS_MOCK_MODE=true` in `.env` if running without ML.

```bash
# Run database migrations
uv run alembic upgrade head

# Seed initial superuser
uv run python app/initial_data.py

# Start dev server with hot reload
uv run fastapi dev app/main.py
```

The backend runs at http://localhost:8000.

### Frontend

```bash
cd frontend

# Install dependencies
bun install

# Start dev server
bun run dev
```

The frontend runs at http://localhost:5173.

### Regenerate API Client

When backend API endpoints change, regenerate the typed frontend client:

```bash
cd frontend
bun run generate-client
```

## Environment Variables

Key variables in `.env` (see the file for the full list):

| Variable | Description | Default |
|----------|-------------|---------|
| `SECRET_KEY` | JWT signing key — **change in production** | `changethis` |
| `DATABASE_URL` | PostgreSQL connection string | *(required)* |
| `FIRST_SUPERUSER` | Admin email created on first run | `admin@example.com` |
| `FIRST_SUPERUSER_PASSWORD` | Admin password — **change in production** | `changethis` |
| `FRONTEND_HOST` | Frontend URL (for CORS and email links) | `http://localhost:5173` |
| `ENVIRONMENT` | `local`, `staging`, or `production` | `local` |
| `SMTP_HOST` | SMTP server for emails | *(empty = disabled)* |
| `SENTRY_DSN` | Sentry error tracking | *(empty = disabled)* |

Generate a secure secret key:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

## Deployment Instructions

The production deployment is a **CPU-only GCP VM** behind Caddy (automatic
HTTPS), not the generic Traefik guide in `deployment.md`. The authoritative
runbook is [`deploy/gcp/README.md`](./deploy/gcp/README.md).

**Live demo (on-demand):** https://dashboard.34.10.142.210.sslip.io
> The demo runs on an on-demand CPU-only VM that is stopped to save cost, so the
> URL may be unreachable until the VM is started (see the runbook below). The
> backend health check is `https://api.34.10.142.210.sslip.io/api/v1/utils/healthz/ready`.

Bring-up summary (full detail in the runbook):

```bash
# 1. Create the VM + static IP (prints DOMAIN=<ip>.sslip.io)
bash deploy/gcp/01-create-vm.sh

# 2. Install Docker + clone repo on the VM
bash deploy/gcp/02-setup-vm.sh

# 3. Stage ML model weights (Uni-Sign, mT5, Kokoro)
bash deploy/gcp/03-stage-models.sh

# 4. Start app + Caddy reverse proxy (TLS via Let's Encrypt)
docker compose -f compose.yml -f deploy/gcp/compose.cpu.yml up -d
docker compose -f deploy/gcp/docker-compose.caddy.yml -p caddy up -d
```

`sslip.io` provides free wildcard DNS (`<ip>.sslip.io` → that IP), so no domain
purchase is required. Caddy serves `dashboard.<ip>.sslip.io` (frontend) and
`api.<ip>.sslip.io` (backend) per [`deploy/gcp/Caddyfile`](./deploy/gcp/Caddyfile).

## Usage Guide

Once the app is running (locally or via the live demo), a meeting works like this:

1. A **speaker** creates a meeting and gets a shareable code (e.g., `XKF-8291`)
2. A **reader** joins using the code
3. **Direction A:** the speaker's audio is streamed via WebSocket → the backend runs **STT** → the transcript is translated to **sign gloss** (mBART LoRA) → the reader sees live captions and the **3D avatar** signing the gloss
4. **Direction B:** the reader signs at their camera → a web worker extracts 133 RTMW pose keypoints per frame (**only keypoints, never video, leave the browser**) → keypoints stream over the same WebSocket → the backend segments signs (rest-pose / motion-pause detection) and recognizes each with **Uni-Sign** → the sentence is finalized, smoothed to English, and spoken to the speaker via **TTS**

## Project Structure

```
SignSpeak/
├── backend/
│   ├── app/
│   │   ├── main.py                 # FastAPI entry point & ML model lifecycle
│   │   ├── models.py               # SQLModel database models
│   │   ├── api/
│   │   │   ├── deps.py             # Dependency injection (auth, DB sessions)
│   │   │   └── routes/             # REST endpoints (login, users, meetings)
│   │   ├── core/
│   │   │   ├── config.py           # Pydantic settings from .env
│   │   │   ├── db.py               # Async database engine
│   │   │   └── security.py         # Password hashing & JWT
│   │   ├── ml/
│   │   │   ├── stt.py              # Speech-to-Text engine
│   │   │   ├── tts.py              # Text-to-Speech engine
│   │   │   └── audio_utils.py      # Audio format conversion
│   │   ├── ws/
│   │   │   ├── router.py           # WebSocket endpoint
│   │   │   ├── connection_manager.py
│   │   │   └── handlers.py         # STT/TTS message routing
│   │   └── services/               # Business logic layer
│   ├── scripts/                    # Prestart, test, lint scripts
│   ├── tests/
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── routes/                 # TanStack Router pages
│   │   ├── components/
│   │   │   ├── Meeting/            # SpeakerView, ReaderView, WaitingRoom
│   │   │   └── ui/                 # shadcn/ui components
│   │   ├── hooks/                  # useAuth, useMeeting (WebSocket)
│   │   └── client/                 # Auto-generated OpenAPI client
│   ├── tests/                      # Playwright E2E tests
│   └── package.json
├── compose.yml                     # Production Docker Compose
├── compose.override.yml            # Dev overrides (hot reload, mailcatcher)
├── .env                            # Environment configuration
├── development.md                  # Detailed development guide
└── deployment.md                   # Production deployment guide
```

## Common Commands

### Backend (Docker)

```bash
# Run tests
docker compose exec backend bash scripts/tests-start.sh

# Create a new migration
docker compose exec backend alembic revision --autogenerate -m "description"

# Apply migrations
docker compose exec backend alembic upgrade head

# Open a shell
docker compose exec backend bash
```

### Backend (local)

```bash
cd backend

# Run tests — ALWAYS against a local database, with an explicit DSN.
# (`DATABASE_URL=''` does NOT work: env_ignore_empty=True means empty env
# vars are ignored and the .env value wins. The suite's teardown deletes all
# users; tests/conftest.py refuses non-local DB hosts as a safety net.)
# One-time local DB:  initdb -D /tmp/sstest -U postgres --auth=trust &&
#   pg_ctl -D /tmp/sstest -o "-p 55432 -c fsync=off" start &&
#   psql -h localhost -p 55432 -U postgres -c "CREATE DATABASE app;"
export TEST_DB='postgresql+psycopg://postgres:postgres@localhost:55432/app'
DATABASE_URL=$TEST_DB uv run bash scripts/prestart.sh   # migrate + seed once
DATABASE_URL=$TEST_DB uv run pytest                     # Run tests

uv run ruff check .                 # Lint
uv run ruff format .                # Format
uv run mypy app                     # Type check
```

### Frontend

```bash
cd frontend
bun run dev                         # Dev server
bun run build                       # Production build
bun run test                        # E2E tests (Playwright)
bun run test:unit                   # Unit tests (Vitest)
bun run lint                        # Lint & format (Biome)
bun run generate-client             # Regenerate API client
```

## ML Models

The STT and TTS models are loaded at backend startup. To run without them (for frontend-focused work or CI):

```bash
# In .env
STT_MOCK_MODE=true
TTS_MOCK_MODE=true
```

When ML is enabled, the backend requires:
- **STT**: Downloads automatically via NeMo toolkit (~600MB)
- **TTS**: Requires `kokoro-v1.0.onnx` (~325MB) and `voices-v1.0.bin` (~28MB) — place in the backend working directory
- **Gloss translation**: `manohonsy/asl-mbart-50-lora` downloads automatically from Hugging Face

### Running Direction B (sign recognition) locally

Direction B needs the Uni-Sign checkpoint and an mT5 snapshot, which are **not** auto-downloaded:

1. Place the WLASL ISLR checkpoint at `~/.signspeak/models/uni-sign/wlasl_pose_only_islr.pth` and the mT5 base snapshot at `~/.signspeak/models/mt5-base` (see `deploy/gcp/03-stage-models.sh` for download/staging commands), or point `SIGN_TO_TEXT_CHECKPOINT` / `SIGN_TO_TEXT_MT5_DIR` wherever you keep them.
2. The sign-recognition model code lives in `sign_to_gloss/Uni-Sign/` and is driven by `backend/app/ml/sign_to_text.py`. It is built on the **Uni-Sign** model (Li et al., ICLR 2025 — see [Models & Credits](#team--provenance)).
3. No setup is needed for the browser side — YOLOX + RTMW ONNX models are bundled with the frontend (or served from `VITE_MODEL_BASE`).
4. Without the checkpoint, the backend starts fine and logs a warning; set `SIGN_TO_TEXT_MOCK_MODE=true` to exercise the pipeline with canned output.

Segmentation/recognition knobs (`SIGN_TO_TEXT_*` in `backend/app/core/config.py`) are all env-tunable — thresholds were calibrated against real keypoint traces (motion threshold 0.012, min 18 frames, min hand confidence 0.3).

## Privacy & Known Model Limitations

**Privacy by design (Direction B):** the reader's camera video is processed entirely in a browser web worker — only 133 pose keypoints (x, y, confidence) are ever transmitted. Raw pixels never leave the device. All ML models run locally on our own server; no user content is sent to third-party AI APIs. Sentry error tracking runs with `send_default_pii=False` and scrubs audio buffers from events.

**Known limitations (documented honestly):**
- The translation model emits **pseudo-gloss** (IX / #WORD / cl: conventions), not authentic ASL grammar.
- The avatar lexicon is ~1,168 **Indian Sign Language** signs rendered for ASL gloss — a different language, not just an imperfect rendering; fingerspelling falls back to ISL handshapes.
- Direction B vocabulary is limited to **WLASL isolated signs**; classifier-predicate motion (core ASL grammar) is not rendered.
- No fairness evaluation across signer demographics (skin tone, hand size, signing speed) has been run yet — see the maturity report roadmap.

## Team & Provenance

This repository was forked from the [FastAPI full-stack template](https://github.com/fastapi/full-stack-fastapi-template) via copier (template authors appear in the inherited git history). All SignSpeak features — meetings, STT/TTS pipelines, gloss translation, the signing avatar, and the Direction B sign-recognition pipeline — were built by **@manohosny**. To see project work excluding template history: `git log --since=2025-03-01 --oneline --no-merges`.

**Models & credits.** SignSpeak's ML stages are built on pretrained models we integrate (not author); our work is the segmentation, real-time pipeline, and serving around them:

- **Sign recognition (Direction B):** [Uni-Sign](https://github.com/ZechengLi19/Uni-Sign) — Li, Zhou, Zhao, Wu, Hu, Li, *Uni-Sign: Toward Unified Sign Language Understanding at Scale*, ICLR 2025 ([arXiv:2501.15187](https://arxiv.org/abs/2501.15187)).
- **STT:** NVIDIA Parakeet TDT 0.6B · **TTS:** Kokoro 82M · **Browser pose:** YOLOX-tiny + RTMW (MMPose) · **Gloss translation:** mBART-50, LoRA-fine-tuned in-house as `manohonsy/asl-mbart-50-lora`.

## Further Documentation

- [Development Guide](./development.md) — Docker Compose workflows, local domains, pre-commit hooks
- [Deployment Guide](./deployment.md) — Production setup with Traefik and HTTPS
- [Backend README](./backend/README.md) — Backend-specific setup and testing
- [Frontend README](./frontend/README.md) — Frontend-specific setup and E2E testing
