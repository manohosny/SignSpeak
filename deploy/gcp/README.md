# Deploying SignSpeak to Google Cloud

> **What is actually live (2026-06):** a CPU-only `e2-standard-16`
> (16 vCPU / 64 GB) in `us-central1-a` at `34.10.142.210.sslip.io`, running
> `compose.yml` + `deploy/gcp/compose.cpu.yml` behind **Caddy**
> (`docker-compose.caddy.yml` + `Caddyfile`) — not the GPU/Traefik plan below.
> The GPU quota was unavailable on the trial account, so the stack falls back
> to CPU; Traefik was replaced by Caddy because Traefik pins Docker API 1.24,
> below Engine 29's minimum (see `Caddyfile` header).

## Cost — live CPU deployment
- `e2-standard-16` on-demand ≈ **$0.54/hr** → ~$390/month if left running 24/7.
- With idle-stop between demos (~30–40 hrs/month) ≈ **$16–22/month** compute,
  plus ~$10–15/month for the 100 GB disk and static IP while stopped.
- The most expensive component is the VM itself; everything else (Supabase
  Postgres free tier, GHCR, sslip.io DNS, Let's Encrypt) is $0. There are no
  per-request AI API costs — all models are local.

The original GPU plan below is kept for when a GPU quota is available.

---

# GPU plan (original, $300 trial)

A single NVIDIA L4 VM runs the whole `docker compose` stack — all four server
models co-resident on one GPU for lowest latency. Postgres is external (free
tier). You idle-stop the VM between demos to stretch the $300 credit.

See the full rationale in `/.claude/plans/i-want-to-deploy-zazzy-narwhal.md`.

## What runs where
- **Browser (no server):** YOLOX-tiny + RTMW pose via `onnxruntime-web`.
- **GPU VM (this guide):** Parakeet STT, Uni-Sign sign→text, mBART gloss
  translation (all CUDA), Kokoro TTS (CPU), frontend, Redis, Traefik.
- **External free tier:** Postgres (Supabase or Neon).

## Cost (GPU, idle-stop)
`g2-standard-8` + L4 ≈ ~$1/hr while running. ~30–40 hrs/month of demos ≈
$30–40/month → credit lasts ~7–8 months. Stopped VM ≈ ~$10/month (disk + IP).

---

## Step 0 — Prerequisites (DO FIRST)
1. **Upgrade the free trial to a paid account** (still uses the $300 credit;
   no real charge until exhausted). GPUs are blocked on the un-upgraded trial.
2. **Request GPU quota:** Console → IAM & Admin → Quotas → filter
   `NVIDIA L4 GPUs`, region `us-central1` → request **1**. Wait for approval.
3. **Create the external Postgres** (Supabase or Neon), copy its SSL
   connection string for `DATABASE_URL`.

## Step 1 — Create the VM (run locally)
```bash
bash deploy/gcp/01-create-vm.sh
```
Note the printed **Static IP** and `DOMAIN=<ip>.sslip.io`.

## Step 2 — Set up the VM (run on the VM)
```bash
gcloud compute ssh signspeak --zone=us-central1-a
# on the VM:
bash 02-setup-vm.sh        # NVIDIA driver + Docker + toolkit + traefik network
# log out / back in so the docker group applies
```
(Copy the repo to the VM first — `git clone` your fork, or
`gcloud compute scp --recurse` the project.)

## Step 3 — Configure env
```bash
cp deploy/gcp/.env.gcp.example .env
# edit .env: set DOMAIN/FRONTEND_HOST/BACKEND_CORS_ORIGINS to the sslip.io
# values, SECRET_KEY (openssl rand -hex 32), DATABASE_URL, superuser creds.
```

## Step 4 — Start Traefik (TLS)
```bash
export TRAEFIK_ACME_EMAIL=you@example.com
docker compose -f deploy/gcp/docker-compose.traefik.yml -p traefik up -d
```

## Step 5 — Build image + stage model weights
```bash
docker compose build backend frontend

# Option A: download weights from upstream
export UNISIGN_CKPT_URL="<Uni-Sign how2sign_pose_only_slt.pth download URL>"
bash deploy/gcp/03-stage-models.sh

# Option B: scp weights you already have locally, into the volumes.
#   The volumes are project-prefixed (signspeak_*). Easiest is to scp the files
#   to the VM, then `docker compose run --rm --no-deps --entrypoint bash backend`
#   and `cp` them to /app/backend/models and /home/appuser/.signspeak/models.
```
`mBART-50-LoRA` and `Parakeet` are **not** staged — they auto-download from
Hugging Face into the `model-cache-hf` volume on first boot (persisted after).

## Step 6 — Launch the app
```bash
docker compose up -d   # redis -> prestart (migrations) -> backend -> frontend
```
First boot downloads mBART + Parakeet and warms all models (~minutes). Watch:
```bash
docker compose logs -f backend
nvidia-smi              # expect ~12–13 GB VRAM once warm
```

## Step 7 — Verify (see plan's verification section)
```bash
# GPU reaches the model code:
docker compose exec backend python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
# Models ready (200, was 503 during load):
curl -k https://api.<ip>.sslip.io/api/v1/utils/healthz/ready
```
Then open `https://dashboard.<ip>.sslip.io`, create a meeting, and test both
directions (speak → avatar; sign → speech). Camera/mic prompts only appear over
HTTPS — confirm the padlock and a `wss://` connection in DevTools → Network.

## Idle-stop (save credit)
Manual:
```bash
gcloud compute instances stop  signspeak --zone=us-central1-a   # after a demo
gcloud compute instances start signspeak --zone=us-central1-a   # before a demo
```
Optional auto-shutdown — install `idle-shutdown.sh` as a systemd timer that
stops the VM after ~30 min idle. The VM's service account needs the
`compute.instances.stop` permission (Compute Instance Admin on itself).
```bash
sudo cp deploy/gcp/idle-shutdown.sh /usr/local/bin/signspeak-idle.sh
sudo chmod +x /usr/local/bin/signspeak-idle.sh
# create /etc/systemd/system/signspeak-idle.{service,timer} (OnUnitActiveSec=5min),
# then: sudo systemctl enable --now signspeak-idle.timer
```

## Notes
- **Repo changes already made for cloud:** `compose.yml` backend memory raised
  to 26G and a `signspeak-models` volume + `SIGN_TO_TEXT_*` paths added;
  `backend/Dockerfile` creates `~/.signspeak/models` so the volume is writable.
- **Real domain later:** change `DOMAIN` (+ DNS A records `api`/`dashboard` →
  static IP) and restart; Traefik re-issues certs automatically.

---

# Operations (live CPU deployment)

## Service level objectives
- **Availability target: 99% during announced demo windows.** Outside demo
  windows the VM may be deliberately idle-stopped to save credit — that is
  planned downtime, not an incident.
- **Latency budgets** (CPU VM, per stage — all stages already emit
  `duration_ms` via the `time_stage` structured logger):
  - HTTP API requests: p95 < 500 ms (verified: p95 99 ms at 50 VUs,
    `loadtest/RESULTS.md`)
  - STT utterance → transcript: < 2 s
  - Gloss translation (mBART, cached LRU): < 1 s
  - Sign segment → recognized word (Uni-Sign): < 3 s
  - Watchdog ceilings (hard): `*_TIMEOUT_SECONDS` in
    `backend/app/core/config.py` (20–30 s) — a hung inference frees the
    session instead of stalling it.

## Rollback on the VM
The live VM runs locally-built images, so rollback = rebuild at a known-good
commit (model weights and DB live in volumes/external Postgres and are
unaffected; migrations are additive-only by policy):

```bash
gcloud compute ssh signspeak --zone=us-central1-a
cd SignSpeak
git log --oneline -5                  # pick the last known-good commit
git checkout <good-sha>
docker compose -f compose.yml -f deploy/gcp/compose.cpu.yml build backend frontend
docker compose -f compose.yml -f deploy/gcp/compose.cpu.yml up -d
curl -fsS https://api.34.10.142.210.sslip.io/api/v1/utils/healthz/ready
```

If a migration must be reverted: `docker compose exec backend alembic
downgrade -1` **before** switching the code back.

(The GitHub Actions deploy workflows in `.github/workflows/deploy-*.yml`
implement tag-based pull + automatic rollback-on-unhealthy; they take over
once the VM is registered as a self-hosted runner and images come from GHCR.)

## Production triage checklist
1. **Detect:** healthcheck — `curl -fsS .../api/v1/utils/healthz/live` (web
   tier up?) then `/healthz/ready` (models warm? 503 = still loading).
2. **Container state:** `docker compose ps` — backend `unhealthy` or
   restart-looping means OOM or model-load failure; check
   `docker stats --no-stream` against the 26G/40G limits.
3. **Logs:** `docker compose logs -f backend | grep -E 'ERROR|WARN'` — every
   log line carries `meeting_id`/`user_id`/`role` and per-stage
   `duration_ms`, so one meeting's pipeline can be reconstructed end-to-end.
4. **Errors with stack traces:** Sentry (if `SENTRY_DSN` is set in the VM's
   `.env`) — events arrive with audio buffers scrubbed.
5. **Fix:** config-only fixes are env edits + `up -d`; code fixes follow the
   rollback procedure above (forward to a fix commit instead of backward).
