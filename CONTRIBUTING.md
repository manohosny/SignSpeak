# Contributing to SignSpeak

SignSpeak is a real-time two-way sign-language translation app — speech → signing avatar and sign → speech — built on a FastAPI backend and a React frontend.

For setting up the development environment (Docker Compose, local domains, pre-commit hooks), see the [Development Guide](development.md).

## Branch naming

Branch from `master` using a type prefix plus a short scope:

- `feat/<scope>-<short-description>` — new functionality (e.g. `feat/segmentation-motion-pause`)
- `fix/<scope>-<short-description>` — bug fixes (e.g. `fix/ws-keypoint-framing`)
- `docs/<scope>-<short-description>` — documentation only (e.g. `docs/fairness-protocol`)

## Commit messages

Use [Conventional Commits](https://www.conventionalcommits.org/) with a scope, matching the existing history:

```
feat(segmentation): motion-pause boundary so signs end without leaving frame
fix(lint+tests): clear ruff errors and update segmentation tests to new defaults
chore(types+lint): mypy strict clean (109->0) and biome clean
docs(plan): rest-pose sign segmentation implementation plan
```

Types in use: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`. Keep the subject imperative and concrete — say what changed and why it matters.

## Pull requests

All changes land via pull request — no direct pushes to `master`.

- Every PR needs **at least one review** before merge.
- Keep PRs focused on a single change; reference related issues.
- Update tests when changing behavior; update docs when changing workflows or interfaces.
- All required CI checks must be green before merge.

### Solo-phase self-review checklist

During solo development phases (no second reviewer available), a PR may be self-merged **only** after completing this checklist and with all required CI checks green:

- [ ] Full backend suite passes locally against a throwaway Postgres with an **explicit local `DATABASE_URL`** (see the README backend test commands — `DATABASE_URL=''` is silently ignored because of `env_ignore_empty=True`; `tests/conftest.py` refuses non-local DB hosts as a safety net).
- [ ] Frontend unit tests pass (`cd frontend && bun run test:unit` — Vitest).
- [ ] Lint gates pass: `uv run ruff check app`, `uv run ruff format app --check`, and `uv run mypy app` in `backend/`; `bun run lint` (Biome) in `frontend/`.
- [ ] Self-review of the full diff in the PR UI, with the same scrutiny you would apply to someone else's change.

## CI gates

The following workflows in [`.github/workflows/`](.github/workflows/) gate every PR:

| Workflow | What it checks |
| --- | --- |
| `pre-commit.yml` | Ruff check + format, Biome, mypy (`backend/app`), generated frontend SDK, misc hygiene hooks |
| `test-backend.yml` | Backend pytest suite against a Dockerized Postgres, with a 90% coverage floor |
| `test-frontend.yml` | Biome lint, TypeScript typecheck, Vitest unit tests |
| `playwright.yml` | End-to-end Playwright suite, sharded 4 ways |
| `test-docker-compose.yml` | Full-stack compose smoke test plus Trivy image vulnerability scanning |
| `secret-scan.yml` | Gitleaks secret scanning over the full git history |

## Where documentation lives

- [README](README.md) — project overview, quickstart, common tasks, privacy & known model limitations
- [DOCUMENTATION.md](DOCUMENTATION.md) — implementation and testing documentation per component
- [deployment.md](deployment.md) — production deployment with Traefik and HTTPS
- [deploy/gcp/README.md](deploy/gcp/README.md) — GCP deployment, including the "Operations" runbook for the live VM
- [docs/](docs/) — process documents, e.g. the fairness evaluation protocol

Put new documentation next to what it describes (backend specifics in `backend/README.md`, frontend specifics in `frontend/README.md`) and link it from the README's "Further Documentation" section.

## Questions?

Open a GitHub issue — including for questions; a question issue is cheaper than a wrong assumption.
