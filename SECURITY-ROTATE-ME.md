# Security: rotate committed secrets

The repository's `.env` file was committed to git history with **live secrets** for the
Supabase Postgres database. This document lists the rotation steps that the maintainer
(only you have the credentials) must perform. Until these are done, treat the existing
secrets as compromised.

> **Status:** `.env` and `frontend/.env` have been removed from git tracking
> (`git rm --cached`) — they remain on disk locally but new commits no longer include
> them. The secret still lives in **past commits**, so rotation below is still required.
> `frontend/.env` held only non-secret local URLs; `frontend/.env.example` is now the
> committed template.

## What was exposed

Found in [.env](.env) at commit `e462356` and earlier:

| Secret | Location | Status |
|---|---|---|
| Supabase Postgres password (`postgres.ifdtfigdqjwdcdsbepwa` / `Cofi0ee7C74Resgq`) | `DATABASE_URL=…` line 35 | **Compromised — rotate** |
| JWT `SECRET_KEY` | `SECRET_KEY=changethis` line 21 | Default placeholder; rotate before any non-local deploy |
| `FIRST_SUPERUSER_PASSWORD` | line 23 | Default placeholder; rotate before deploy |

## Rotation steps

### 1. Rotate the Supabase Postgres password

```bash
# In the Supabase dashboard:
#   Project Settings → Database → Connection string → Reset password
# Copy the new password.
```

Update your local `.env` (now untracked) with the new connection string.
Update your deployment platform's secret store with the new connection string.

### 2. Generate a new JWT signing key

```bash
openssl rand -hex 32
```

Replace `SECRET_KEY` in your local `.env` and your deployment secret store. **Note:**
existing JWTs become invalid the moment you rotate — every user will be logged out
once and need to sign in again.

### 3. Rotate the bootstrap superuser password

```bash
openssl rand -base64 24
```

Update `FIRST_SUPERUSER_PASSWORD` and re-run `app/initial_data.py` against any
environment where the placeholder was ever used. If a superuser already exists with
the placeholder password, change it via the API or directly in the DB.

### 4. (Optional) Purge from git history

The committed secret remains in the git log and any clone or fork. If you have
control over all clones, you can purge it:

```bash
# WARNING: rewrites history. All collaborators must re-clone.
brew install git-filter-repo
git filter-repo --path .env --invert-paths
git push --force-with-lease origin main
```

If purging history isn't feasible (public fork, multiple collaborators), rely on
rotation — the secret in history is useless once invalidated.

### 5. Verify

After rotation:

```bash
git status .env                     # should be untracked
git ls-files | grep '^.env$'        # should output nothing
git log --all -- .env | head -5     # if purged, returns nothing
```

Smoke-test the app:

```bash
cp .env.example .env
# fill .env with the new credentials
docker compose up -d --build
curl -f http://localhost:8000/api/v1/utils/health-check/
```

## Going forward

- `.env` is now in `.gitignore`; `.env.example` is the canonical template.
- In `staging` and `production`, the backend refuses to boot with `SECRET_KEY=changethis`
  (see [backend/app/core/config.py](backend/app/core/config.py)).
- Use the deployment platform's secret store (Supabase, Vercel, Railway, GitHub Actions
  secrets, etc.) — never commit a real secret to the repo.
