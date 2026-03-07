# SignSpeak

A real-time accessibility platform that enables seamless communication between speakers and readers. Speakers talk naturally while their speech is transcribed live; readers type messages that are converted to audio for the speaker.

## Features

- **Speech-to-Text (STT)** — Live transcription using NVIDIA Parakeet TDT 0.6B via NeMo
- **Text-to-Speech (TTS)** — Message vocalization using Kokoro 82M ONNX
- **Real-time meetings** — WebSocket-based communication with shareable meeting codes
- **Role-based participation** — Speaker and reader roles with tailored UIs
- **Meeting lifecycle** — Create, join, and manage meetings (waiting → active → ended)
- **User authentication** — JWT-based auth with email password recovery
- **Dark mode** — Full theme support across the app

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Backend** | FastAPI, SQLModel, PostgreSQL, Alembic |
| **Frontend** | React 19, TypeScript, TanStack Router/Query, Tailwind CSS, shadcn/ui |
| **ML/AI** | NVIDIA Parakeet TDT 0.6B (STT), Kokoro 82M ONNX (TTS), PyTorch |
| **Real-time** | WebSockets (FastAPI native) |
| **Infrastructure** | Docker Compose, Traefik, Nginx |
| **Testing** | Pytest (backend), Playwright (E2E), Vitest (unit) |

## Prerequisites

- **Docker & Docker Compose** (recommended for full-stack)
- **Python 3.10+** with [uv](https://docs.astral.sh/uv/) package manager
- **Bun** (or Node.js) for the frontend
- **PostgreSQL 12+** (or a cloud provider like Supabase)

## Quick Start (Docker)

```bash
# 1. Clone the repository
git clone <repo-url>
cd SignSpeak

# 2. Configure environment
cp .env .env.local   # Edit .env with your database URL, secrets, etc.

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

# Install dependencies
uv sync

# Install ML dependencies (optional — requires ~2GB for models)
uv sync --extra ml

# Run database migrations
alembic upgrade head

# Seed initial superuser
python app/initial_data.py

# Start dev server with hot reload
fastapi dev app/main.py
```

The backend runs at http://localhost:8000.

> **Tip:** Set `STT_MOCK_MODE=true` and `TTS_MOCK_MODE=true` in your `.env` to run without downloading ML models during development.

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

## How It Works

1. A **speaker** creates a meeting and gets a shareable code (e.g., `XKF-8291`)
2. A **reader** joins using the code
3. The speaker's audio is streamed via WebSocket → the backend runs **STT** → transcripts are broadcast to the reader in real-time
4. The reader types messages → the backend runs **TTS** → audio is sent back to the speaker

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
pytest                              # Run tests
ruff check .                        # Lint
ruff format .                       # Format
mypy app                            # Type check
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

## Further Documentation

- [Development Guide](./development.md) — Docker Compose workflows, local domains, pre-commit hooks
- [Deployment Guide](./deployment.md) — Production setup with Traefik and HTTPS
- [Backend README](./backend/README.md) — Backend-specific setup and testing
- [Frontend README](./frontend/README.md) — Frontend-specific setup and E2E testing
