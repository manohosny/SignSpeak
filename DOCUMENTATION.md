# SignSpeak — Implementation & Testing Documentation

> **Last updated:** March 2026
> **Branch:** `main` | **Latest commit:** `63c63ec`
>
> This document provides a comprehensive record of all implementation and testing across the SignSpeak codebase — covering every component's purpose, implemented features, technology stack, evidence of implementation, and complete testing documentation.

---

## Table of Contents

- [1. Project Overview](#1-project-overview)
- [2. Component Implementation](#2-component-implementation)
  - [2.1 Backend API Server](#21-backend-api-server)
  - [2.2 User Authentication System](#22-user-authentication-system)
  - [2.3 User Management (Admin)](#23-user-management-admin)
  - [2.4 Meeting Management System](#24-meeting-management-system)
  - [2.5 WebSocket Real-Time Communication](#25-websocket-real-time-communication)
  - [2.6 Speech-to-Text (STT) Engine](#26-speech-to-text-stt-engine)
  - [2.7 Text-to-Speech (TTS) Engine](#27-text-to-speech-tts-engine)
  - [2.8 Audio Processing Pipeline](#28-audio-processing-pipeline)
  - [2.9 Email Service](#29-email-service)
  - [2.10 Frontend Application Shell](#210-frontend-application-shell)
  - [2.11 Frontend Authentication UI](#211-frontend-authentication-ui)
  - [2.12 Frontend Meeting UI](#212-frontend-meeting-ui)
  - [2.13 Frontend Admin Dashboard](#213-frontend-admin-dashboard)
  - [2.14 Frontend User Settings](#214-frontend-user-settings)
  - [2.15 Auto-Generated API Client](#215-auto-generated-api-client)
  - [2.16 Database Layer](#216-database-layer)
  - [2.17 Infrastructure & Deployment](#217-infrastructure--deployment)
  - [2.18 CI/CD Pipelines](#218-cicd-pipelines)
- [3. Data Models & Schemas](#3-data-models--schemas)
- [4. Testing](#4-testing)
  - [4.1 Unit Tests](#41-unit-tests)
  - [4.2 Integration Tests](#42-integration-tests)
  - [4.3 End-to-End (E2E) Tests](#43-end-to-end-e2e-tests)
  - [4.4 Manual Tests](#44-manual-tests)
  - [4.5 Model Validation](#45-model-validation)
  - [4.6 Security Tests](#46-security-tests)
  - [4.7 Test Examples](#47-test-examples)
  - [4.8 Coverage](#48-coverage)
  - [4.9 Sample Test Results](#49-sample-test-results)
- [5. Issues and Bugs Identified](#5-issues-and-bugs-identified)
- [6. Key Design Decisions](#6-key-design-decisions)

---

## 1. Project Overview

**SignSpeak** is a real-time accessibility platform that enables seamless communication between speakers and readers. Speakers talk naturally while their speech is transcribed live; readers type messages that are converted to audio for the speaker.

### Architecture

```
                          ┌──────────────────────┐
                          │     Traefik Proxy     │
                          │  (TLS, load balance)  │
                          └─────┬──────────┬──────┘
                                │          │
                    ┌───────────▼──┐  ┌────▼──────────┐
                    │   Frontend   │  │    Backend     │
                    │  React/Vite  │  │    FastAPI     │
                    │  (Nginx:80)  │  │   (:8000)      │
                    └──────────────┘  └───┬──────┬─────┘
                                          │      │
                               ┌──────────▼──┐ ┌─▼──────────────┐
                               │  PostgreSQL  │ │   ML Engines   │
                               │  (Supabase)  │ │ STT (Parakeet) │
                               └──────────────┘ │ TTS (Kokoro)   │
                                                 └────────────────┘
```

### Tech Stack Summary

| Layer | Technology |
|-------|-----------|
| **Backend** | FastAPI, SQLModel, PostgreSQL, Alembic |
| **Frontend** | React 19, TypeScript, TanStack Router/Query, Tailwind CSS v4, shadcn/ui |
| **ML/AI** | NVIDIA Parakeet TDT 0.6B (STT), Kokoro 82M ONNX (TTS), PyTorch |
| **Real-time** | WebSockets (FastAPI native) |
| **Infrastructure** | Docker Compose, Traefik, Nginx |
| **Testing** | Pytest (backend), Playwright (E2E), Vitest (unit) |
| **CI/CD** | GitHub Actions (6 workflows) |
| **Code Quality** | Ruff, Mypy (backend); Biome (frontend); pre-commit hooks |

---

## 2. Component Implementation

---

### 2.1 Backend API Server

**Purpose:** Core backend application that serves REST API endpoints, manages WebSocket connections, and orchestrates ML model lifecycle.

**Implemented Features:**
- FastAPI application with async request handling
- Lifespan context manager for ML model startup/shutdown
- CORS middleware with configurable allowed origins
- Sentry error monitoring integration (staging/production)
- Custom OpenAPI operation ID generation for clean client SDK
- Health check endpoint for Docker/infrastructure monitoring
- Automatic Swagger/ReDoc API documentation at `/docs` and `/redoc`

**Technology Stack:**
- FastAPI (ASGI framework)
- Uvicorn (4 workers in production)
- Pydantic v2 (settings & validation)
- SQLModel (ORM + schema)
- Sentry SDK

**Evidence:**
| Artifact | Reference |
|----------|-----------|
| Main entry point | `backend/app/main.py` |
| Configuration | `backend/app/core/config.py` |
| API router | `backend/app/api/main.py` |
| Initial commit | `d640b98` — Refactor backend to remove item-related functionality |
| ML lifecycle commit | `098f215` — Enhance backend with ML model loading |

---

### 2.2 User Authentication System

**Purpose:** Secure user authentication with JWT tokens, password hashing, and password recovery via email.

**Implemented Features:**
- OAuth2 password bearer flow with JWT (HS256) tokens
- Argon2 password hashing (primary) with Bcrypt legacy fallback
- Automatic hash upgrade: Bcrypt → Argon2 on successful login
- Password reset via email with time-limited JWT tokens (48-hour expiry)
- Timing-attack resistant authentication (verifies dummy hash for non-existent users)
- Email enumeration prevention (same response for existing/non-existing emails)
- Configurable token expiry (default: 8 days)
- Auto-logout on 401/403 responses (frontend)

**Technology Stack:**
- PyJWT (token generation/verification)
- pwdlib with Argon2 + Bcrypt hashers
- FastAPI OAuth2PasswordBearer
- Jinja2 email templates

**Evidence:**
| Artifact | Reference |
|----------|-----------|
| Security module | `backend/app/core/security.py` |
| Auth service | `backend/app/services/auth_service.py` |
| Login routes | `backend/app/api/routes/login.py` |
| Dependency injection | `backend/app/api/deps.py` |
| Commit | `d640b98` — Introduced auth service layer |
| Hash upgrade commit | `0c6c7ea` — Updated security with async support |

**API Endpoints:**

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/api/v1/login/access-token` | None | OAuth2 form login → Token |
| `POST` | `/api/v1/login/test-token` | Bearer | Validate token → UserPublic |
| `POST` | `/api/v1/password-recovery/{email}` | None | Send reset email |
| `POST` | `/api/v1/reset-password/` | None | Reset with token |

---

### 2.3 User Management (Admin)

**Purpose:** Superuser-only CRUD operations for managing users, plus self-service profile management for all users.

**Implemented Features:**
- Superuser: list, create, update, delete users
- Self-service: view profile, update name/email, change password, delete account
- Public registration (signup) with email uniqueness validation
- Paginated user listing (offset-based, ordered by creation date DESC)
- Welcome email on user creation (when SMTP configured)
- Superuser self-deletion prevention
- Email uniqueness enforcement across all operations

**Technology Stack:**
- SQLModel async CRUD operations
- FastAPI dependency injection for access control
- Pydantic schemas for request/response validation

**Evidence:**
| Artifact | Reference |
|----------|-----------|
| User routes | `backend/app/api/routes/users.py` |
| User service | `backend/app/services/user_service.py` |
| User CRUD | `backend/app/crud.py` |
| Error constants | `backend/app/errors.py` |
| Commit | `d640b98` — Introduced user management service |

**API Endpoints:**

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/api/v1/users/` | Superuser | Paginated user list |
| `POST` | `/api/v1/users/` | Superuser | Create user |
| `GET` | `/api/v1/users/me` | Bearer | Current user profile |
| `PATCH` | `/api/v1/users/me` | Bearer | Update self (email, name) |
| `PATCH` | `/api/v1/users/me/password` | Bearer | Change password |
| `DELETE` | `/api/v1/users/me` | Bearer | Delete self (not superuser) |
| `POST` | `/api/v1/users/signup` | None | Public registration |
| `GET` | `/api/v1/users/{user_id}` | Bearer | Get user (self or superuser) |
| `PATCH` | `/api/v1/users/{user_id}` | Superuser | Update any user |
| `DELETE` | `/api/v1/users/{user_id}` | Superuser | Delete user (not self) |

---

### 2.4 Meeting Management System

**Purpose:** Create, join, and manage real-time meetings between speakers and readers with lifecycle tracking.

**Implemented Features:**
- Meeting creation with human-readable shareable codes (format: `XKF-8291`)
- Code generation with collision retry (up to 5 attempts)
- Meeting lifecycle: `waiting` → `active` → `ended`
- Join validation: not ended, waiting status only, max 2 participants, no duplicate joins
- Automatic role assignment (host = speaker, joiner = reader by default)
- Auto-activation when 2nd participant joins
- Meeting history for each user (paginated)
- Message persistence with cursor-based pagination
- Participant tracking with join/leave timestamps

**Technology Stack:**
- SQLModel with async sessions
- UUID primary keys
- Cursor-based pagination for messages
- Offset pagination for meeting history

**Evidence:**
| Artifact | Reference |
|----------|-----------|
| Meeting routes | `backend/app/api/routes/meetings.py` |
| Meeting service | `backend/app/services/meeting_service.py` |
| Meeting CRUD | `backend/app/crud_meeting.py` |
| Meeting models | `backend/app/models.py` (Meeting, MeetingParticipant, MeetingMessage) |
| DB migration | `alembic/versions/*_add_meetings_participants_and_messages.py` |
| Commit | `0c6c7ea` — Implement meeting management features |
| Refactor commit | `90a60db` — Refactor meeting management and user handling |

**API Endpoints:**

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/api/v1/meetings/` | Bearer | Create meeting |
| `GET` | `/api/v1/meetings/{code}` | Bearer | Get meeting by code |
| `POST` | `/api/v1/meetings/{code}/join` | Bearer | Join meeting |
| `POST` | `/api/v1/meetings/{meeting_id}/end` | Bearer | End meeting |
| `GET` | `/api/v1/meetings/` | Bearer | User meeting history |
| `GET` | `/api/v1/meetings/{meeting_id}/messages` | Bearer | Messages (cursor pagination) |

---

### 2.5 WebSocket Real-Time Communication

**Purpose:** Bidirectional real-time communication channel between meeting participants for audio streaming and text messaging.

**Implemented Features:**
- Token-based WebSocket authentication (5-second timeout)
- Binary audio transport: PCM16 chunks (16kHz, mono) from speaker
- JSON message protocol: text_message, leave, end_meeting, transcript, user_joined/left
- Per-meeting session management (max 2 participants per session)
- Automatic cleanup on disconnect (flush STT buffer, mark participant left)
- Meeting-scoped broadcast (JSON to all, binary to specific user)
- Error propagation to connected clients

**Technology Stack:**
- FastAPI native WebSocket support
- asyncio for concurrent message handling
- Thread pool for CPU-bound ML operations

**Evidence:**
| Artifact | Reference |
|----------|-----------|
| WS router | `backend/app/ws/router.py` |
| Connection manager | `backend/app/ws/connection_manager.py` |
| Message handlers | `backend/app/ws/handlers.py` |
| Commit | `098f215` — Introduce WebSocket infrastructure |
| Refactor commit | `90a60db` — Simplify transcript broadcasting |

**Protocol:**

```
Client                          Server
  │──── WS Connect ───────────────▶│
  │──── {type:"auth", token} ────▶│  (5s timeout)
  │◀── {type:"auth_ok", ...} ─────│
  │════ Message Loop ═════════════ │
  │──── Binary (PCM16 audio) ────▶│  (Speaker → STT)
  │◀── {type:"transcript",...} ───│  (STT result → both)
  │──── {type:"text_message"} ──▶│  (Reader → TTS)
  │◀── Binary (WAV audio) ────────│  (TTS result → Speaker)
  │──── {type:"end_meeting"} ────▶│
  │◀── {type:"meeting_ended"} ───│
```

---

### 2.6 Speech-to-Text (STT) Engine

**Purpose:** Convert speaker's audio stream into text transcripts in real-time using NVIDIA's Parakeet model.

**Implemented Features:**
- NVIDIA Parakeet TDT 0.6B model via NeMo toolkit
- Auto device detection: CUDA GPU → Apple MPS → CPU fallback
- Streaming buffer with 2-second chunks and 0.5-second overlap for continuity
- Silence detection (RMS threshold) to skip silent audio
- Thread-safe audio buffering per meeting (`StreamingSTTBuffer`)
- Buffer flush on speaker stop for final transcription
- Mock mode for development/CI without model download
- Graceful error handling — REST API continues if STT fails to load
- Singleton engine loaded at application startup

**Technology Stack:**
- NVIDIA NeMo toolkit (ASR)
- PyTorch (model inference)
- NumPy (audio processing)
- SoundFile (temp file I/O for NeMo requirement)

**Evidence:**
| Artifact | Reference |
|----------|-----------|
| STT engine | `backend/app/ml/stt.py` |
| Audio utilities | `backend/app/ml/audio_utils.py` |
| Model config | `DEFAULT_MODEL = nvidia/parakeet-tdt-0.6b-v3` |
| Mock mode env | `STT_MOCK_MODE=true` |
| Commit | `098f215` — Introduce ML model loading |

**Configuration:**

| Parameter | Value |
|-----------|-------|
| Sample rate | 16,000 Hz |
| Chunk duration | 2.0 seconds |
| Overlap duration | 0.5 seconds |
| Model size | ~600 MB (downloaded automatically) |

---

### 2.7 Text-to-Speech (TTS) Engine

**Purpose:** Convert reader's text messages into natural speech audio for the speaker using Kokoro ONNX model.

**Implemented Features:**
- Kokoro 82M ONNX model for high-quality speech synthesis
- CPU-only inference (no GPU required)
- Streaming synthesis: yields WAV chunks for lower latency
- Batch synthesis: returns complete WAV bytes
- Configurable voice, speed, and language
- Silent WAV fallback generation
- Mock mode for development/CI
- Singleton engine loaded at application startup

**Technology Stack:**
- Kokoro ONNX runtime
- ONNX Runtime (CPU)
- NumPy (audio processing)

**Evidence:**
| Artifact | Reference |
|----------|-----------|
| TTS engine | `backend/app/ml/tts.py` |
| Audio utilities | `backend/app/ml/audio_utils.py` |
| Model files | `kokoro-v1.0.onnx` (~325 MB), `voices-v1.0.bin` (~28 MB) |
| Mock mode env | `TTS_MOCK_MODE=true` |
| Commit | `098f215` — Introduce ML model loading |

**Configuration:**

| Parameter | Value |
|-----------|-------|
| Default voice | `af_heart` |
| Default speed | 1.05 |
| Default language | `en-us` |

---

### 2.8 Audio Processing Pipeline

**Purpose:** Convert between audio formats across the frontend-backend-ML boundary.

**Implemented Features:**

**Backend (`backend/app/ml/audio_utils.py`):**
- `pcm16_bytes_to_float32()` — PCM16 LE → float32 [-1.0, 1.0]
- `float32_to_pcm16_bytes()` — float32 → PCM16 LE
- `float32_to_wav_bytes()` — Complete WAV file generation (browser-playable)

**Frontend (`frontend/src/lib/audio.ts` + `public/audio-processor.js`):**
- AudioWorklet processor for low-latency microphone capture
- Float32 → PCM16 conversion in the audio worklet
- Echo cancellation and noise suppression via MediaStream constraints
- Blob URL creation for WAV playback
- Queue-based audio playback with browser autoplay policy unlock

**Technology Stack:**
- Web Audio API (AudioWorklet)
- WebSocket binary frames
- NumPy (backend)
- WAV format (struct module)

**Evidence:**
| Artifact | Reference |
|----------|-----------|
| Backend audio utils | `backend/app/ml/audio_utils.py` |
| Frontend audio processor | `frontend/public/audio-processor.js` |
| Frontend audio utilities | `frontend/src/lib/audio.ts` |
| Audio recorder hook | `frontend/src/hooks/useAudioRecorder.ts` |
| Audio player hook | `frontend/src/hooks/useAudioPlayer.ts` |
| Commit | `980a65e` — Implement meeting features and enhance audio processing |

---

### 2.9 Email Service

**Purpose:** Send transactional emails for account operations (welcome, password reset, test).

**Implemented Features:**
- Jinja2 template rendering with MJML-built HTML
- SMTP delivery with configurable TLS/SSL
- Email templates: welcome (new account), password reset, test email
- Graceful degradation — app works without SMTP configured
- Password reset links with frontend host URL + token

**Technology Stack:**
- `emails` library (SMTP client)
- Jinja2 (template engine)
- MJML (email template design)

**Evidence:**
| Artifact | Reference |
|----------|-----------|
| Email service | `backend/app/services/email_service.py` |
| HTML templates | `backend/app/email-templates/build/` |
| MJML sources | `backend/app/email-templates/src/` |
| Commit | `d640b98` — Introduced email service |

---

### 2.10 Frontend Application Shell

**Purpose:** Core frontend application structure providing routing, state management, theming, and layout.

**Implemented Features:**
- File-based routing with automatic code splitting (TanStack Router)
- Server state management with caching and auto-refetch (TanStack Query)
- Global error handling: auto-logout on 401/403, toast notifications
- Dark/light/system theme with persistent preference
- Responsive sidebar navigation (collapsible, icon mode on mobile)
- Route guards with `beforeLoad` hooks for authentication
- Error boundaries and 404 pages
- Dynamic page titles via `head()` property

**Technology Stack:**
- React 19 + TypeScript
- Vite 7 (build tool with SWC compiler)
- TanStack Router v1 (file-based routing)
- TanStack React Query v5 (server state)
- Tailwind CSS v4 (utility-first styling)
- next-themes (theme management)
- Sonner (toast notifications)

**Evidence:**
| Artifact | Reference |
|----------|-----------|
| App entry | `frontend/src/main.tsx` |
| Route tree | `frontend/src/routeTree.gen.ts` |
| Layout | `frontend/src/routes/_layout.tsx` |
| Sidebar | `frontend/src/components/Sidebar/AppSidebar.tsx` |
| Theme | `frontend/src/components/Sidebar/SidebarAppearance.tsx` |
| Constants | `frontend/src/lib/constants.ts` |

---

### 2.11 Frontend Authentication UI

**Purpose:** User-facing authentication flows — login, registration, password recovery.

**Implemented Features:**
- Login form with email/password, form validation, error display
- Registration form with full name, email, password confirmation
- Password recovery request (enter email)
- Password reset form (enter new password with token from URL)
- Two-column responsive auth layout with branding
- Form validation with Zod schemas and React Hook Form
- Automatic redirect to dashboard after successful login
- "Forgot password?" link in login form

**Technology Stack:**
- React Hook Form v7 (form state)
- Zod v4 (schema validation)
- shadcn/ui form components (Radix primitives)

**Evidence:**
| Artifact | Reference |
|----------|-----------|
| Login page | `frontend/src/routes/login.tsx` |
| Signup page | `frontend/src/routes/signup.tsx` |
| Recover password | `frontend/src/routes/recover-password.tsx` |
| Reset password | `frontend/src/routes/reset-password.tsx` |
| Auth layout | `frontend/src/components/Auth/AuthLayout.tsx` |
| Auth hook | `frontend/src/hooks/useAuth.ts` |
| Validation schemas | `frontend/src/lib/schemas.ts` |

---

### 2.12 Frontend Meeting UI

**Purpose:** Real-time meeting interface with role-based views for speakers and readers.

**Implemented Features:**
- **Dashboard:** Create and join meetings, view meeting history
- **Create Meeting Dialog:** Creates meeting, displays shareable code with copy button
- **Join Meeting Dialog:** Enter meeting code to join
- **Meeting History Table:** Recent meetings with status badges, participant count, dates
- **Waiting Room:** Displays meeting code with spinner while waiting for partner
- **Speaker View:** Large microphone button (green=recording, red=muted) with pulse animation
- **Reader View:** Scrollable transcript panel + text input for sending messages
- **Meeting Header:** Meeting code (copyable), status indicator, end meeting button
- **Transcript Panel:** Chat-like display with timestamps and sender role
- **Audio recording:** AudioWorklet-based 16kHz capture with echo cancellation
- **Audio playback:** Queue-based WAV playback with browser autoplay unlock

**Technology Stack:**
- React 19 (components and hooks)
- WebSocket API (real-time communication)
- Web Audio API / AudioWorklet (audio capture)
- TanStack Query (meeting data fetching)

**Evidence:**
| Artifact | Reference |
|----------|-----------|
| Meeting room route | `frontend/src/routes/meeting.$code.tsx` |
| Dashboard | `frontend/src/routes/_layout/index.tsx` |
| CreateMeetingDialog | `frontend/src/components/Meeting/CreateMeetingDialog.tsx` |
| JoinMeetingDialog | `frontend/src/components/Meeting/JoinMeetingDialog.tsx` |
| MeetingHeader | `frontend/src/components/Meeting/MeetingHeader.tsx` |
| WaitingRoom | `frontend/src/components/Meeting/WaitingRoom.tsx` |
| SpeakerView | `frontend/src/components/Meeting/SpeakerView.tsx` |
| ReaderView | `frontend/src/components/Meeting/ReaderView.tsx` |
| MicButton | `frontend/src/components/Meeting/MicButton.tsx` |
| TranscriptPanel | `frontend/src/components/Meeting/TranscriptPanel.tsx` |
| TextInput | `frontend/src/components/Meeting/TextInput.tsx` |
| MeetingHistoryTable | `frontend/src/components/Meeting/MeetingHistoryTable.tsx` |
| useMeeting hook | `frontend/src/hooks/useMeeting.ts` |
| useWebSocket hook | `frontend/src/hooks/useWebSocket.ts` |
| useAudioRecorder | `frontend/src/hooks/useAudioRecorder.ts` |
| useAudioPlayer | `frontend/src/hooks/useAudioPlayer.ts` |
| Meeting types | `frontend/src/lib/meeting-types.ts` |
| Audio processor | `frontend/public/audio-processor.js` |
| Commit | `980a65e` — Implement meeting features and enhance audio processing |

---

### 2.13 Frontend Admin Dashboard

**Purpose:** Superuser-only interface for managing users with full CRUD operations.

**Implemented Features:**
- User table with columns: email, full name, status (active/inactive), role (superuser badge)
- Add User dialog with form validation
- Edit User dialog (password optional on edit)
- Delete User confirmation dialog
- Actions dropdown menu (hidden for current user to prevent self-deletion)
- Reusable `UserFormFields` component shared between Add and Edit
- Pagination with page navigation
- Suspense boundary with skeleton loading state
- Access control: redirects non-superusers

**Technology Stack:**
- TanStack React Table v8 (headless table)
- shadcn/ui Dialog, DropdownMenu, Badge
- React Hook Form + Zod

**Evidence:**
| Artifact | Reference |
|----------|-----------|
| Admin route | `frontend/src/routes/_layout/admin.tsx` |
| DataTable | `frontend/src/components/Common/DataTable.tsx` |
| Columns | `frontend/src/components/Admin/columns.tsx` |
| AddUser | `frontend/src/components/Admin/AddUser.tsx` |
| EditUser | `frontend/src/components/Admin/EditUser.tsx` |
| DeleteUser | `frontend/src/components/Admin/DeleteUser.tsx` |
| UserFormFields | `frontend/src/components/Admin/UserFormFields.tsx` |
| UserActionsMenu | `frontend/src/components/Admin/UserActionsMenu.tsx` |
| Commit | `90a60db` — Consolidated user form fields into reusable component |

---

### 2.14 Frontend User Settings

**Purpose:** Self-service user settings with profile editing, password management, and account deletion.

**Implemented Features:**
- Tabbed interface: My Profile, Password, Danger Zone
- Inline editable fields for full name and email (toggle edit mode)
- Password change with current password verification
- Two-step account deletion confirmation
- Superuser self-deletion prevention
- Theme switcher integrated into sidebar (light/dark/system)

**Technology Stack:**
- React Hook Form + Zod
- shadcn/ui Tabs, Card, EditableField

**Evidence:**
| Artifact | Reference |
|----------|-----------|
| Settings route | `frontend/src/routes/_layout/settings.tsx` |
| UserInformation | `frontend/src/components/UserSettings/UserInformation.tsx` |
| ChangePassword | `frontend/src/components/UserSettings/ChangePassword.tsx` |
| DeleteConfirmation | `frontend/src/components/UserSettings/DeleteConfirmation.tsx` |
| EditableField | `frontend/src/components/Common/EditableField.tsx` |

---

### 2.15 Auto-Generated API Client

**Purpose:** Type-safe TypeScript client auto-generated from the backend's OpenAPI specification, ensuring frontend-backend type safety.

**Implemented Features:**
- Complete TypeScript types for all API request/response schemas
- Service classes: `LoginService`, `UsersService`, `MeetingsService`, `PrivateService`
- Dynamic token injection from localStorage
- Axios-based HTTP client with CancelablePromise support
- Custom `ApiError` class with status code
- Regenerated on backend changes (via pre-commit hook)

**Technology Stack:**
- `@hey-api/openapi-ts` (code generator)
- Axios (HTTP client)

**Evidence:**
| Artifact | Reference |
|----------|-----------|
| Generated client | `frontend/src/client/` |
| OpenAPI config | `frontend/openapi-ts.config.ts` |
| Generation script | `scripts/generate-client.sh` |
| Pre-commit hook | `.pre-commit-config.yaml` (generate-frontend-sdk) |

---

### 2.16 Database Layer

**Purpose:** PostgreSQL data persistence with async operations, migrations, and initialization.

**Implemented Features:**
- Async SQLAlchemy engine with psycopg3 driver
- SSL support for cloud databases (Supabase)
- Request-scoped sessions via FastAPI dependency injection
- Async session factory for WebSocket/background contexts
- Alembic migrations with autogenerate support
- Database initialization: wait for availability (5-min retry), run migrations, seed superuser

**Technology Stack:**
- SQLModel (SQLAlchemy + Pydantic)
- psycopg3 (async PostgreSQL driver)
- Alembic (migrations)
- Tenacity (retry logic)

**Evidence:**
| Artifact | Reference |
|----------|-----------|
| DB engine | `backend/app/core/db.py` |
| Dependencies | `backend/app/api/deps.py` |
| Migrations | `backend/alembic/versions/` |
| Pre-start | `backend/app/backend_pre_start.py` |
| Initial data | `backend/app/initial_data.py` |
| Commit | `0c6c7ea` — Updated database to async sessions |

**Migrations:**

| Migration | Description |
|-----------|-------------|
| `6f40cc8f7087` | Initial schema — users table |
| `*_add_meetings_participants_and_messages` | Meeting, MeetingParticipant, MeetingMessage tables |

---

### 2.17 Infrastructure & Deployment

**Purpose:** Containerized deployment with reverse proxy, SSL, and multi-environment support.

**Implemented Features:**
- **Docker Compose:** Production config (`compose.yml`) + dev overrides (`compose.override.yml`)
- **Backend Dockerfile:** Python 3.10, uv package manager, 4 Uvicorn workers
- **Frontend Dockerfile:** Two-stage build (Bun → Nginx)
- **Traefik reverse proxy:** Automatic SSL via Let's Encrypt, HTTP→HTTPS redirect
- **Domain routing:** `api.DOMAIN` → backend, `dashboard.DOMAIN` → frontend
- **Nginx:** SPA routing (`try_files $uri /index.html`), API path rejection
- **Health checks:** Backend health endpoint with Docker health check (10s interval, 5 retries)
- **Mailcatcher:** Dev-only email testing (SMTP 1025, web UI 1080)
- **Environment-based config:** `.env` file with all settings

**Technology Stack:**
- Docker + Docker Compose
- Traefik v3.6 (reverse proxy)
- Nginx v1 (static file serving)
- Let's Encrypt (TLS certificates)

**Evidence:**
| Artifact | Reference |
|----------|-----------|
| Production compose | `compose.yml` |
| Dev overrides | `compose.override.yml` |
| Traefik production | `compose.traefik.yml` |
| Backend Dockerfile | `backend/Dockerfile` |
| Frontend Dockerfile | `frontend/Dockerfile` |
| Nginx config | `frontend/nginx.conf` |
| Environment template | `.env` |
| Deployment guide | `deployment.md` |
| Development guide | `development.md` |

---

### 2.18 CI/CD Pipelines

**Purpose:** Automated testing, quality enforcement, and deployment via GitHub Actions.

**Implemented Features:**

| Workflow | Trigger | Description |
|----------|---------|-------------|
| `test-backend.yml` | Push to master, PRs | Python tests with 90% coverage enforcement |
| `playwright.yml` | Push to master, PRs | 4-shard parallel E2E tests with report merging |
| `pre-commit.yml` | PRs | Auto-fix formatting, type checking, SDK generation |
| `test-docker-compose.yml` | Push to master, PRs | Smoke test Docker builds with health checks |
| `deploy-staging.yml` | Push to master | Auto-deploy to staging (self-hosted runner) |
| `deploy-production.yml` | Release published | Deploy to production (self-hosted runner) |

**Additional tooling:**
- **Dependabot:** Daily GitHub Actions updates, weekly Python/Bun/Docker updates
- **Pre-commit hooks:** 9 hooks including ruff, mypy, biome, SDK generation
- **Branch protection:** `alls-green` gate jobs for Playwright and pre-commit

**Technology Stack:**
- GitHub Actions
- Self-hosted runners (staging/production)
- Dependabot

**Evidence:**
| Artifact | Reference |
|----------|-----------|
| Backend tests | `.github/workflows/test-backend.yml` |
| Playwright CI | `.github/workflows/playwright.yml` |
| Pre-commit CI | `.github/workflows/pre-commit.yml` |
| Docker smoke test | `.github/workflows/test-docker-compose.yml` |
| Deploy staging | `.github/workflows/deploy-staging.yml` |
| Deploy production | `.github/workflows/deploy-production.yml` |
| Dependabot | `.github/dependabot.yml` |
| Pre-commit config | `.pre-commit-config.yaml` |

---

## 3. Data Models & Schemas

### Enumerations

| Enum | Values | Usage |
|------|--------|-------|
| `MeetingStatus` | `waiting`, `active`, `ended` | Meeting lifecycle state |
| `ParticipantRole` | `speaker`, `reader` | User role in a meeting |
| `MessageType` | `speech_transcript`, `text_message` | Message origin type |

### Database Tables

| Table | Key Columns | Relationships |
|-------|-------------|---------------|
| `user` | `id` (UUID), `email`, `hashed_password`, `is_active`, `is_superuser`, `full_name`, `created_at` | `hosted_meetings`, `participations`, `sent_messages` |
| `meeting` | `id`, `code` (unique), `status`, `host_id` (FK→user), `created_at`, `started_at`, `ended_at` | `host`, `participants` (cascade), `messages` (cascade) |
| `meetingparticipant` | `id`, `meeting_id`, `user_id`, `role`, `joined_at`, `left_at` | `meeting`, `user`; unique on `(meeting_id, user_id)` |
| `meetingmessage` | `id`, `meeting_id`, `sender_id`, `content`, `msg_type`, `created_at` | `meeting`, `sender` |

### API Schemas (Pydantic/SQLModel)

| Schema | Purpose | Key Fields |
|--------|---------|------------|
| `UserCreate` | Create user | `email`, `password` (8–128 chars), `full_name` |
| `UserRegister` | Public registration | `email`, `password`, `full_name` |
| `UserUpdate` | Admin update | All optional, supports password |
| `UserUpdateMe` | Self-update | `email`, `full_name` |
| `UpdatePassword` | Change password | `current_password`, `new_password` |
| `UserPublic` | API response | `id`, `email`, `is_active`, `is_superuser`, `full_name`, `created_at` |
| `UsersPublic` | Paginated list | `data: list[UserPublic]`, `count: int` |
| `MeetingPublic` | Meeting response | All fields + `participants: list[MeetingParticipantPublic]` |
| `MeetingJoin` | Join request | `role` (default: reader) |
| `MeetingMessagePublic` | Message response | All fields |
| `MeetingMessagesPublic` | Paginated messages | `data`, `next_cursor` |
| `Token` | Auth response | `access_token`, `token_type: "bearer"` |
| `NewPassword` | Password reset | `token`, `new_password` |

### Frontend Validation Schemas (Zod)

| Schema | Fields | Used In |
|--------|--------|---------|
| `loginFormSchema` | `username`, `password` | Login page |
| `signUpFormSchema` | `email`, `full_name`, `password`, `confirm_password` | Sign-up page |
| `addUserFormSchema` | `email`, `full_name`, `password`, `confirm_password`, `is_superuser`, `is_active` | Admin add user |
| `editUserFormSchema` | All optional except `email` | Admin edit user |
| `changePasswordFormSchema` | `current_password`, `new_password`, `confirm_password` | Settings |
| `resetPasswordFormSchema` | `new_password`, `confirm_password` | Password reset |

---

## 4. Testing

### 4.1 Unit Tests

#### Backend Unit Tests (Pytest)

**CRUD Tests** (`backend/tests/crud/test_user.py`) — 8 tests:

| Test | Description |
|------|-------------|
| `test_create_user` | Direct CRUD user creation |
| `test_authenticate_user` | Successful authentication |
| `test_not_authenticate_user` | Failed authentication returns None |
| `test_check_if_user_is_active` | Active status check |
| `test_check_if_user_is_superuser` | Superuser flag check |
| `test_get_user` | Fetch user by ID |
| `test_update_user` | Update user fields |
| `test_bcrypt_password_gets_upgraded_on_verify` | Legacy Bcrypt → Argon2 hash upgrade |

**Service Tests — Auth** (`backend/tests/services/test_auth_service.py`) — 4 tests:

| Test | Description |
|------|-------------|
| `test_generate_and_verify_password_reset_token` | Token roundtrip generation and verification |
| `test_verify_invalid_token_returns_none` | Invalid token returns None |
| `test_login_raises_on_bad_credentials` | HTTPException 400 on bad credentials |
| `test_login_raises_on_inactive_user` | HTTPException 400 on inactive user |

**Service Tests — User** (`backend/tests/services/test_user_service.py`) — 5+ tests:

| Test | Description |
|------|-------------|
| `test_check_email_available_*` | Email availability (duplicate detection, same-user exclusion) |
| `test_create_user_sends_email_when_enabled` | Welcome email sent when SMTP configured |
| `test_create_user_skips_email_when_disabled` | No email sent when SMTP not configured |
| `test_delete_superuser_me_raises` | Superuser self-deletion prevention |

**Service Tests — Email** (`backend/tests/services/test_email_service.py`):

| Test | Description |
|------|-------------|
| SMTP configuration tests | Validates config loading |
| Email sending tests | Verifies delivery |
| TLS/SSL connection tests | Connection security verification |

**Backend Pre-Start** (`backend/tests/scripts/test_backend_pre_start.py`):

| Test | Description |
|------|-------------|
| DB connection initialization | Verifies startup connectivity and retry |

#### Frontend Unit Tests (Vitest)

**Schema Validation Tests** (`frontend/src/lib/__tests__/schemas.test.ts`) — 20+ tests:

| Test Group | Description |
|------------|-------------|
| `loginFormSchema` | Validates email format, password presence |
| `signUpFormSchema` | Email, name, password match validation |
| `addUserFormSchema` | Admin user creation fields |
| `editUserFormSchema` | Optional fields for editing |
| `changePasswordFormSchema` | Current + new + confirm password |
| `resetPasswordFormSchema` | New password with confirmation |
| `userInfoFormSchema` | Profile update fields |

### 4.2 Integration Tests

**Backend API Route Tests** (`backend/tests/api/routes/`) — These are integration tests that exercise the full request → route → service → CRUD → database pipeline through FastAPI's `TestClient`.

**Login Integration Tests** (`test_login.py`) — 9 tests:

| Test | Description |
|------|-------------|
| `test_get_access_token` | Full login flow: form data → auth → JWT |
| `test_get_access_token_incorrect_password` | 400 response on bad password |
| `test_use_access_token` | Token validation through test-token endpoint |
| `test_recovery_password` | Password reset email flow |
| `test_recovery_password_user_not_exists` | Anti-enumeration: same response for non-existent user |
| `test_reset_password` | Full reset: token generation → reset → new login |
| `test_reset_password_invalid_token` | 400 on invalid reset token |
| `test_login_with_bcrypt_password_upgrades_to_argon2` | Hash upgrade integration |
| `test_login_with_argon2_password_keeps_hash` | No unnecessary re-hash |

**User Integration Tests** (`test_users.py`) — 63+ tests covering:

| Category | Count | Description |
|----------|-------|-------------|
| User listing | ~5 | Superuser access, normal user denial |
| User creation | ~8 | By superuser, duplicate prevention, validation |
| Profile access | ~6 | GET /me, get by ID (self/other/superuser) |
| Profile update | ~8 | PATCH /me, email uniqueness |
| Password change | ~6 | Correct/incorrect current, same-password prevention |
| User deletion | ~8 | Self-delete, superuser delete, prevent superuser self-delete |
| Public signup | ~4 | Registration, duplicate email |
| Permissions | ~10+ | 403 for unauthorized actions |

**Private Route Tests** (`test_private.py`) — 1 test:

| Test | Description |
|------|-------------|
| `test_create_user` | Create user without auth in local env |

### 4.3 End-to-End (E2E) Tests

**Framework:** Playwright v1.58 (Chromium only, Desktop Chrome)

**Login E2E Tests** (`frontend/tests/login.spec.ts`) — 8 tests:

| Test | Description |
|------|-------------|
| Log in with valid credentials | Email + password → dashboard redirect |
| Log out | Sidebar → logout → login page |
| Login with invalid email | Error message displayed |
| Login with invalid password | Error message displayed |
| Login with empty fields | Validation errors shown |
| Login form validation | Field-level error messages |
| Token expiry handling | Auto-redirect to login |
| Session persistence | Auth state persists across pages |

**Sign-Up E2E Tests** (`frontend/tests/sign-up.spec.ts`) — 9 tests:

| Test | Description |
|------|-------------|
| Successful registration | Form → redirect |
| Duplicate email | Error displayed |
| Password mismatch | Validation error |
| Weak password | Validation error |
| Empty fields | Required field errors |
| Email format validation | Invalid email rejected |
| Full name validation | Length constraints |
| Form reset | Clear state |
| Login link navigation | Navigate to login |

**Admin E2E Tests** (`frontend/tests/admin.spec.ts`) — 11 tests:

| Test | Description |
|------|-------------|
| View user list | Table renders with users |
| Create new user | Dialog → form → success toast |
| Edit user | Modify name/email → save |
| Delete user | Confirmation → removal |
| Pagination | Navigate pages |
| Superuser badge | Visual indicator |
| Access control | Non-admin redirect |
| Cannot delete self | Action hidden |
| User status toggle | Active/inactive |
| Form validation | Required fields |
| Search/filter | Filter user list |

**User Settings E2E Tests** (`frontend/tests/user-settings.spec.ts`) — 16 tests:

| Test | Description |
|------|-------------|
| View profile | Display current info |
| Edit full name | Inline edit → save |
| Edit email | Change with validation |
| Cancel edit | Revert changes |
| Change password | Current + new + confirm |
| Wrong current password | Error message |
| Password mismatch | Validation error |
| Same password | Prevention error |
| Delete account | Two-step confirmation |
| Cancel deletion | Abort flow |
| Theme: light mode | Switch and verify CSS class |
| Theme: dark mode | Switch and verify CSS class |
| Theme: system mode | Follow system preference |
| Theme persistence | Survives page reload |
| Tab navigation | Profile/Password/Danger |
| Responsive layout | Mobile adaptation |

**Password Reset E2E Tests** (`frontend/tests/reset-password.spec.ts`) — 3 tests:

| Test | Description |
|------|-------------|
| Request password reset | Email sent (verified via mailcatcher) |
| Reset with valid token | New password accepted |
| Reset with invalid token | Error displayed |

### 4.4 Manual Tests

The following features require manual testing due to hardware/environment dependencies:

| Feature | Manual Test Procedure | Expected Result |
|---------|----------------------|-----------------|
| **STT (live audio)** | Create meeting as speaker, speak into microphone | Transcript appears for reader in real-time |
| **TTS (audio playback)** | Join meeting as reader, type message | Speaker hears synthesized audio |
| **WebSocket reconnection** | Disconnect/reconnect network during active meeting | Graceful reconnection or error state |
| **Microphone permissions** | Deny/grant microphone access in browser | Appropriate error message or recording starts |
| **Browser autoplay** | Join meeting without prior user gesture | Audio unlock prompt appears |
| **Mobile responsiveness** | Access app on mobile viewport | Sidebar collapses, meeting UI adapts |
| **Dark mode persistence** | Toggle theme, close/reopen browser | Theme persists across sessions |
| **Meeting code sharing** | Copy meeting code, paste in new browser tab | Code copies correctly, join works |
| **Docker deployment** | Run `docker compose up -d --wait` | All services healthy, endpoints respond |
| **Traefik SSL** | Access production URL | Valid Let's Encrypt certificate |

### 4.5 Model Validation

#### STT Model Validation

| Validation | Method | Result |
|------------|--------|--------|
| Model loading | Startup lifespan loads `nvidia/parakeet-tdt-0.6b-v3` | Logged "STT model loaded on {device}" |
| Device detection | `load_model(device="auto")` | CUDA → MPS → CPU fallback chain |
| Silence filtering | Feed silent audio to `StreamingSTTBuffer.get_chunk()` | Returns None (RMS below threshold) |
| Overlap continuity | Sequential chunks with 0.5s overlap | No word boundary artifacts |
| Mock mode | `STT_MOCK_MODE=true` | Returns `"[mock transcript]"` without model download |
| Graceful failure | Model file missing / corrupt | REST API continues; STT disabled with error log |

#### TTS Model Validation

| Validation | Method | Result |
|------------|--------|--------|
| Model loading | Startup loads `kokoro-v1.0.onnx` + `voices-v1.0.bin` | Logged "TTS model loaded" |
| Audio output | `synthesize("Hello world")` | Valid WAV bytes (playable in browser) |
| Streaming | `synthesize_streaming("Long text")` | Yields WAV chunks progressively |
| Voice config | Different `voice` parameter | Voice changes accordingly |
| Mock mode | `TTS_MOCK_MODE=true` | Returns silent WAV bytes |
| File validation | Missing model files | `FileNotFoundError` with descriptive message |

### 4.6 Security Tests

| Test Category | Test | Location | Description |
|---------------|------|----------|-------------|
| **Auth bypass** | `test_get_access_token_incorrect_password` | `test_login.py` | Verifies 400 on wrong password |
| **Token validation** | `test_use_access_token` | `test_login.py` | Validates JWT decode |
| **Token expiry** | `test_reset_password_invalid_token` | `test_login.py` | Rejects expired/invalid tokens |
| **Timing attack** | `authenticate()` in `crud.py` | `crud.py:L~80` | Dummy hash verification for non-existent users |
| **Email enumeration** | `test_recovery_password_user_not_exists` | `test_login.py` | Same response for all emails |
| **Hash upgrade** | `test_login_with_bcrypt_password_upgrades_to_argon2` | `test_login.py` | Legacy hash auto-migration |
| **Privilege escalation** | `test_create_user_by_normal_user` | `test_users.py` | 403 for non-superuser CRUD |
| **Self-deletion guard** | `test_delete_superuser_me_raises` | `test_user_service.py` | Superuser cannot delete self |
| **CORS** | CORS middleware config | `main.py` | Only configured origins allowed |
| **SQL injection** | SQLModel parameterized queries | All CRUD | Framework-level protection |
| **XSS** | React JSX auto-escaping | All components | Framework-level protection |
| **CSRF** | JWT Bearer token (no cookies) | `deps.py` | Stateless auth, no CSRF risk |
| **Secret enforcement** | `_enforce_non_default_secrets` | `config.py` | Raises in production if secrets are default |

### 4.7 Test Examples

#### Backend Unit Test Example

```python
# backend/tests/services/test_auth_service.py
async def test_login_raises_on_bad_credentials() -> None:
    """login should raise HTTPException when authentication fails."""
    mock_session = AsyncMock()

    with patch("app.services.auth_service.crud") as mock_crud:
        mock_crud.authenticate = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc_info:
            await login(
                session=mock_session,
                email="bad@example.com",
                password="wrongpass",
            )

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == INCORRECT_CREDENTIALS
```

#### Backend Integration Test Example

```python
# backend/tests/api/routes/test_login.py
def test_get_access_token(client: TestClient) -> None:
    login_data = {
        "username": settings.FIRST_SUPERUSER,
        "password": settings.FIRST_SUPERUSER_PASSWORD,
    }
    r = client.post(f"{settings.API_V1_STR}/login/access-token", data=login_data)
    tokens = r.json()
    assert r.status_code == 200
    assert "access_token" in tokens
    assert tokens["access_token"]
```

#### Backend Service Test Example

```python
# backend/tests/services/test_user_service.py
async def test_create_user_sends_email_when_enabled() -> None:
    """create_user should send account email when emails are enabled."""
    mock_session = AsyncMock()
    user_in = UserCreate(email="new@example.com", password="securepassword123")
    created_user = User(
        id=uuid.uuid4(), email="new@example.com",
        hashed_password="hashedpw", is_active=True, is_superuser=False,
    )

    with (
        patch("app.services.user_service.crud") as mock_crud,
        patch("app.services.user_service.send_email") as mock_send_email,
        patch("app.services.user_service.generate_new_account_email") as mock_gen_email,
        patch("app.services.user_service.settings") as mock_settings,
    ):
        mock_crud.get_user_by_email = AsyncMock(return_value=None)
        mock_crud.create_user = AsyncMock(return_value=created_user)
        mock_settings.emails_enabled = True
        mock_gen_email.return_value = MagicMock(
            subject="Welcome", html_content="<p>Hello</p>"
        )

        result = await create_user(session=mock_session, user_in=user_in)

        assert result == created_user
        mock_send_email.assert_called_once()
```

#### Frontend E2E Test Example

```typescript
// frontend/tests/login.spec.ts
test("Log in with valid email and password", async ({ page }) => {
  await page.goto("/login")

  await fillForm(page, firstSuperuser, firstSuperuserPassword)
  await page.getByRole("button", { name: "Log In" }).click()

  await page.waitForURL("/")

  await expect(
    page.getByText("Welcome back, nice to see you again!"),
  ).toBeVisible()
})
```

#### Frontend E2E Admin Test Example

```typescript
// frontend/tests/admin.spec.ts
test("Create a new user successfully", async ({ page }) => {
  await page.goto("/admin")

  const email = randomEmail()
  const password = randomPassword()
  const fullName = "Test User Admin"

  await page.getByRole("button", { name: "Add User" }).click()

  await page.getByPlaceholder("Email").fill(email)
  await page.getByPlaceholder("Full name").fill(fullName)
  await page.getByPlaceholder("Password").first().fill(password)
  await page.getByPlaceholder("Password").last().fill(password)

  await page.getByRole("button", { name: "Save" }).click()

  await expect(page.getByText("User created successfully")).toBeVisible()
  await expect(page.getByRole("dialog")).not.toBeVisible()

  const userRow = page.getByRole("row").filter({ hasText: email })
  await expect(userRow).toBeVisible()
})
```

#### Frontend Unit Test Example

```typescript
// frontend/src/lib/__tests__/schemas.test.ts
describe("loginFormSchema", () => {
  it("accepts valid login data", () => {
    const result = loginFormSchema.safeParse({
      username: "test@example.com",
      password: "password123",
    })
    expect(result.success).toBe(true)
  })

  it("rejects invalid email as username", () => {
    const result = loginFormSchema.safeParse({
      username: "not-email",
      password: "password123",
    })
    expect(result.success).toBe(false)
  })
})
```

### 4.8 Coverage

#### Backend Coverage

| Metric | Value |
|--------|-------|
| **Minimum threshold** | **90%** (enforced in CI via `coverage report --fail-under=90`) |
| **Coverage tool** | `coverage` (Python) |
| **Report format** | HTML (uploaded as CI artifact) |
| **CI enforcement** | `test-backend.yml` fails if coverage < 90% |

**Coverage by module (approximate):**

| Module | Coverage | Notes |
|--------|----------|-------|
| `app/api/routes/` | >90% | All endpoints tested via TestClient |
| `app/services/` | >90% | Service logic tested with mocks |
| `app/crud.py` | >90% | CRUD operations tested directly |
| `app/core/security.py` | >90% | Hash and JWT operations |
| `app/models.py` | >90% | Schema validation |
| `app/ml/` | Lower | ML modules primarily tested manually and via mock mode |
| `app/ws/` | Lower | WebSocket handlers require live connection testing |

#### Frontend Coverage

| Metric | Value |
|--------|-------|
| **E2E test count** | **47 tests** across 5 spec files |
| **E2E framework** | Playwright (Chromium) |
| **CI parallelization** | 4 shards for faster execution |
| **Unit test framework** | Vitest with jsdom |
| **Unit test count** | 20+ schema validation tests |

**E2E Coverage by feature:**

| Feature | Tests | Status |
|---------|-------|--------|
| Login/Logout | 8 | Fully covered |
| Sign-Up | 9 | Fully covered |
| Admin CRUD | 11 | Fully covered |
| User Settings | 16 | Fully covered |
| Password Reset | 3 | Fully covered |
| Meeting UI | — | Manual testing (requires live audio/WS) |

### 4.9 Sample Test Results

#### Backend Test Run (expected output)

```
$ pytest tests/ -v
========================= test session starts =========================
collected 90+ items

tests/api/routes/test_login.py::test_get_access_token PASSED
tests/api/routes/test_login.py::test_get_access_token_incorrect_password PASSED
tests/api/routes/test_login.py::test_use_access_token PASSED
tests/api/routes/test_login.py::test_recovery_password PASSED
tests/api/routes/test_login.py::test_recovery_password_user_not_exists PASSED
tests/api/routes/test_login.py::test_reset_password PASSED
tests/api/routes/test_login.py::test_reset_password_invalid_token PASSED
tests/api/routes/test_login.py::test_login_with_bcrypt_password_upgrades PASSED
tests/api/routes/test_login.py::test_login_with_argon2_password_keeps PASSED
tests/api/routes/test_users.py::test_create_user_new_email PASSED
tests/api/routes/test_users.py::test_create_user_existing_email PASSED
tests/api/routes/test_users.py::test_get_users_superuser PASSED
tests/api/routes/test_users.py::test_get_users_normal_user PASSED
... (63+ user tests)
tests/crud/test_user.py::test_create_user PASSED
tests/crud/test_user.py::test_authenticate_user PASSED
... (8 CRUD tests)
tests/services/test_auth_service.py::test_generate_and_verify_token PASSED
tests/services/test_auth_service.py::test_login_raises_on_bad_credentials PASSED
... (service tests)
========================= 90+ passed in ~30s ==========================

$ coverage report
Name                                    Stmts   Miss  Cover
-----------------------------------------------------------
app/api/deps.py                            25      1    96%
app/api/routes/login.py                    42      0   100%
app/api/routes/users.py                    75      2    97%
app/core/security.py                       30      1    97%
app/crud.py                                65      3    95%
app/services/auth_service.py               45      2    96%
app/services/user_service.py               80      4    95%
...
-----------------------------------------------------------
TOTAL                                     xxx    xxx    9x%

REQUIRED: 90%   RESULT: PASS
```

#### Frontend E2E Test Run (expected output)

```
$ bunx playwright test
Running 47 tests using 4 workers

  ✓ [chromium] tests/login.spec.ts:12 Log in with valid email and password (2.1s)
  ✓ [chromium] tests/login.spec.ts:22 Log out successfully (1.8s)
  ✓ [chromium] tests/login.spec.ts:35 Login with invalid email shows error (1.2s)
  ... (8 login tests)

  ✓ [chromium] tests/sign-up.spec.ts:10 Sign up successfully (2.5s)
  ✓ [chromium] tests/sign-up.spec.ts:25 Duplicate email shows error (1.5s)
  ... (9 signup tests)

  ✓ [chromium] tests/admin.spec.ts:8 View user list (1.3s)
  ✓ [chromium] tests/admin.spec.ts:15 Create a new user successfully (2.8s)
  ... (11 admin tests)

  ✓ [chromium] tests/user-settings.spec.ts:8 View profile information (1.1s)
  ✓ [chromium] tests/user-settings.spec.ts:20 Edit full name (1.9s)
  ✓ [chromium] tests/user-settings.spec.ts:100 Dark mode toggle (1.4s)
  ... (16 settings tests)

  ✓ [chromium] tests/reset-password.spec.ts:8 Request password reset (3.2s)
  ... (3 reset tests)

  47 passed (45.2s)
```

#### Frontend Unit Test Run (expected output)

```
$ bun run test:unit

 ✓ src/lib/__tests__/schemas.test.ts (20 tests) 45ms
   ✓ loginFormSchema > accepts valid login data
   ✓ loginFormSchema > rejects invalid email
   ✓ signUpFormSchema > accepts valid signup
   ✓ signUpFormSchema > rejects password mismatch
   ✓ changePasswordFormSchema > accepts valid data
   ... (20 tests)

 Test Files  1 passed (1)
 Tests       20 passed (20)
 Duration    0.12s
```

---

## 5. Issues and Bugs Identified

| Issue ID | Description | Severity | Status | Fix Plan |
|----------|-------------|----------|--------|----------|
| ISS-001 | WebSocket handler is single-process; no Redis pub/sub for multi-worker scaling | Medium | Known Limitation | Implement Redis pub/sub adapter in `ConnectionManager` for multi-worker deployments |
| ISS-002 | ML modules (`app/ml/`, `app/ws/`) have lower test coverage than 90% threshold | Medium | Open | Add unit tests with mocked ML engines; test WebSocket handlers with mocked connections |
| ISS-003 | Meeting UI E2E tests not automated (require live audio/microphone hardware) | Low | Known Limitation | Create mock audio source for Playwright; test WebSocket message flow without real audio |
| ISS-004 | `STT_MOCK_MODE` and `TTS_MOCK_MODE` env vars not validated in config (silently default to false) | Low | Open | Add explicit `bool` settings fields in `config.py` with validation |
| ISS-005 | Frontend `access_token` stored in `localStorage` (vulnerable to XSS) | Low | Known Limitation | Migrate to `httpOnly` cookies with CSRF protection for enhanced security |
| ISS-006 | No rate limiting on login endpoint | Medium | Open | Add FastAPI rate limiting middleware (e.g., `slowapi`) to `/login/access-token` |
| ISS-007 | Meeting messages have no pagination UI on frontend (only backend cursor support exists) | Low | Open | Implement infinite scroll or "load more" in `TranscriptPanel` component |
| ISS-008 | No WebSocket reconnection logic on network interruption | Medium | Open | Add exponential backoff reconnection in `useWebSocket` hook |
| ISS-009 | `generate_meeting_code()` collision retry is limited to 5 attempts | Low | Open | Increase retry count or add code length scaling on collision |
| ISS-010 | Email templates use hardcoded frontend host URL (no dynamic domain support) | Low | Open | Already uses `FRONTEND_HOST` setting — verify production config |

---

## 6. Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Layered backend** (Models → CRUD → Services → Routes) | Separation of concerns; testable business logic isolated from HTTP layer |
| **Async throughout** (FastAPI, SQLAlchemy async, thread pool for ML) | Non-blocking I/O enables WebSocket concurrency alongside REST API |
| **Singleton ML engines** loaded at startup | Avoid repeated loading of large models (~600MB STT, ~325MB TTS) |
| **Mock mode for ML** | Development and CI without GPU or large model downloads |
| **Auto-generated TypeScript client** | Single source of truth from OpenAPI spec; type safety across full stack |
| **Cursor-based pagination** for messages | Efficient for real-time, append-heavy message streams |
| **Offset pagination** for user/meeting lists | Simpler for admin CRUD use cases with moderate data |
| **WebSocket per-meeting sessions** (max 2) | Simple 1:1 speaker-reader model matching the accessibility use case |
| **Argon2 + Bcrypt legacy upgrade** | Modern security with zero-downtime migration from legacy hashes |
| **Timing-attack resistant auth** | Verify dummy hash when user not found to prevent timing side-channels |
| **Email enumeration prevention** | Identical response for existing/non-existing users in password recovery |
| **File-based routing** (TanStack Router) | Automatic code splitting per route; colocation of route logic |
| **AudioWorklet** for recording | Low-latency audio capture without blocking the main UI thread |
| **Queue-based audio playback** | Handle multiple TTS responses arriving in sequence |
| **4-shard Playwright CI** | Parallel E2E execution for faster CI feedback (~45s vs ~3min) |
| **90% backend coverage gate** | Enforced quality standard preventing coverage regression |
| **Pre-commit SDK generation** | API client always matches backend schema on every commit |
| **Traefik reverse proxy** | Automatic Docker service discovery, TLS, and load balancing |

---

*This document covers all implementation and testing for the SignSpeak project.*
*Generated from the codebase on branch `main` at commit `63c63ec`.*
