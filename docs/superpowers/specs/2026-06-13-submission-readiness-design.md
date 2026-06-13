# Submission-Readiness Design — SignSpeak Repository

**Date:** 2026-06-13
**Goal:** Bring the SignSpeak repository into full compliance with the academic
GitHub-submission rubric, so an evaluator can reproduce the project and tick
every required box top-to-bottom from the README.

## Context

The repo is already substantial and professional: a 299-line `README.md`, a
61 KB `DOCUMENTATION.md`, `MATURITY_CHECKLIST.md`, `CONTRIBUTING.md`,
`SECURITY.md`, `deployment.md`, `development.md`, backend/frontend sub-READMEs,
277 backend tests, E2E suites, and a working GCP deployment.

The work is therefore **restructuring + gap-closing, not authoring from scratch**.
Most required content exists; it is just not surfaced in the README in the order
the rubric expects, and two items are genuinely missing or wrong.

### Guiding principle: single-source-of-truth + README-as-index

`DOCUMENTATION.md` is the deep reference. The README must **link** to it, not
duplicate it (duplicated docs drift apart). The README's job is to be a
**rubric-shaped front door**: every checklist item gets a clearly-labeled `##`
section, even when that section is three sentences that link deeper.

## Rubric Audit (every mandatory item → status → action)

| Rubric item | Current status | Action |
|---|---|---|
| Finalized source code | ✅ Present | none |
| Final working build | ✅ Deployed (GCP CPU-only) | reference honestly; do not over-claim a live URL |
| README.md | ⚠️ Strong but wrong structure | restructure to template order |
| Setup instructions | ✅ In README | keep |
| Deployment instructions | ⚠️ `deployment.md` is the **generic inherited** template guide, not the real GCP path | add a Deployment section describing the real `deploy/gcp/` path |
| User documentation | ✅ `DOCUMENTATION.md` | link from README Usage Guide |
| Environment requirements | ✅ README + `.env.example` | keep |
| API documentation | ✅ Swagger `/docs` + `frontend/openapi.json` | add README API section pointing to them |
| Database schema | ⚠️ Only in `DOCUMENTATION.md §3`; no README section, no ERD | add README section + Mermaid ERD |
| Screenshots & sample outputs | ❌ Only **stale FastAPI-template** PNGs in `img/` | add Screenshots section with placeholders + capture guide |
| Required assets | ✅ Present | keep |
| Clear contribution history from all members | ⚠️ Git history correct (3 authors) but README says "built by @manohosny" | replace with Team Members table |

### The two real defects

1. **Authorship contradiction.** `README.md:287` claims solo authorship; `git
   shortlog` on `main` shows three students (Abdulrahman 28, Mariam 19, Youssef
   13 commits). A rubric that warns *"unclear contribution history may be
   questioned during the defense"* makes this the highest-risk item.
2. **No real screenshots.** `img/` holds only inherited template images
   (`dashboard-items.png` references the removed `items` feature). Zero
   screenshots of the actual SignSpeak UI.

## Team Roster (for the Team Members table)

| Role | Name | ID | Program |
|------|------|----|---------|
| Student 1 | Abdulrahman Mohamed Hosny | 202200066 | DSAI |
| Student 2 | Mariam Hani | 202200903 | DSAI |
| Student 3 | Youssef El Dawayaty | 202201209 | DSAI |
| Supervisor | Dr. Mohamed Sami Rakha | — | — |

## Deliverables

### Deliverable 1 — README.md restructured to template order

Target section order (template section → source / action):

| Template section | Source / action |
|---|---|
| Title + short description | Keep existing |
| **Team Members** table | New — from roster above |
| **Supervisor** | New — Dr. Mohamed Sami Rakha |
| **Problem Statement** | New — ~1 paragraph on the Deaf/HoH ↔ hearing barrier |
| Features | Keep existing |
| **System Architecture** | New labeled section + Mermaid flow diagram (both directions) |
| Technologies Used | Keep existing "Tech Stack" (rename to match template) |
| Setup Instructions | Keep existing (Docker + local) |
| **Deployment Instructions** | New — summarize real GCP CPU-only path (`deploy/gcp/`, Caddy TLS), give the live URL `https://dashboard.34.10.142.210.sslip.io` (on-demand VM), link `deploy/gcp/README.md` for bring-up |
| **Usage Guide** | Promote "How It Works" into a numbered end-user walkthrough |
| **Database Schema** | New — 5-table summary + Mermaid ERD + link to `DOCUMENTATION.md §3` |
| **API Documentation** | New — endpoint summary table + Swagger `/docs` + `openapi.json` links |
| **Screenshots / Demo** | New — placeholder image links + capture guide |

Existing valuable sections (Privacy & Known Limitations, ML Models, Further
Documentation) are retained and moved below the rubric sections.

### Deliverable 2 — Diagrams (Mermaid, GitHub-native, text-in-README)

- **System Architecture:** a `flowchart` showing Direction A (speech → STT →
  gloss → avatar/captions) and Direction B (camera → browser pose → WS keypoints
  → segmentation → Uni-Sign → English → TTS), with the browser/server boundary
  and the privacy boundary (only keypoints leave the device) marked.
- **Database Schema:** an `erDiagram` of User, Meeting, MeetingParticipant,
  MeetingMessage, RevokedRefreshToken and their relationships.

### Deliverable 3 — Screenshots scaffolding

- New `docs/screenshots/` folder containing a `README.md` capture checklist:
  which screens to capture (login/dashboard, meeting create + code, WaitingRoom,
  SpeakerView with live captions, ReaderView with 3D avatar, gloss feed,
  Direction-B signing view) and the exact filenames to drop PNGs into so the
  README image links resolve once the team adds them.
- Remove the stale `img/*.png` FastAPI-template leftovers (`dashboard.png`,
  `dashboard-dark.png`, `dashboard-items.png`, `docs.png`, `login.png`,
  `github-social-preview.png` / `.svg`) — team confirmed they are unwanted.

### Deliverable 4 — Audit report

This spec **is** the committed audit report (the table above). No separate
root-level checklist file — `MATURITY_CHECKLIST.md` already occupies that role
and a third checklist would clutter the root.

## Out of Scope (YAGNI)

- No rewrite of `DOCUMENTATION.md` (link to it instead).
- No capturing screenshots by running the app (team supplies real PNGs).
- No changes to working source code or tests.
- No unrelated refactors.
- The live URL is stated honestly as an **on-demand** demo (the CPU-only VM is
  started to save cost), not an always-on "🟢 live" badge.

## Success Criteria

1. README contains every template section, in template order, each clearly
   labeled with `##`.
2. Team Members table + Supervisor present and matching `git shortlog`.
3. No authorship contradiction anywhere in the README.
4. Database Schema and API Documentation are reachable from the README.
5. A Screenshots section exists with a clear path for the team to add images.
6. Deployment section describes the **real** deployment, not the generic
   template guide.
7. All existing links resolve; `README.md` renders cleanly on GitHub
   (Mermaid included).

## Risks / Notes

- **DSAI** is taken verbatim from the team (Data Science & Artificial
  Intelligence program). Left as the code the team supplied.
- Live demo URL: `https://dashboard.34.10.142.210.sslip.io` (frontend),
  `https://api.34.10.142.210.sslip.io` (backend), per `deploy/gcp/Caddyfile`.
  The VM was **stopped at the time of writing** (health check timed out) — it is
  an on-demand CPU-only instance. The README will present the URL with that
  honest caveat; the team should start the VM before the defense for a live demo.
