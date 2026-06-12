# Security Policy

Security is very important for this project and its community. 🔒

Learn more about it below. 👇

## Versions

The latest version or release is supported.

You are encouraged to write tests for your application and update your versions frequently after ensuring that your tests are passing. This way you will benefit from the latest features, bug fixes, and **security fixes**.

## Reporting a Vulnerability

If you think you found a vulnerability, and even if you are not sure about it, please report it right away by sending an email to: security@tiangolo.com. Please try to be as explicit as possible, describing all the steps and example code to reproduce the security issue.

I (the author, [@tiangolo](https://twitter.com/tiangolo)) will review it thoroughly and get back to you.

## Public Discussions

Please restrain from publicly discussing a potential security vulnerability. 🙊

It's better to discuss privately and try to find a solution first, to limit the potential impact as much as possible.

## Secrets Handling

Secrets live only in untracked `.env` files locally and in GitHub Secrets for CI/CD — never in committed code or config. The backend config (`backend/app/core/config.py`) refuses to boot in non-local environments with placeholder secrets: `SECRET_KEY` must be set explicitly, and `changethis` values raise hard errors outside `ENVIRONMENT=local`. CI runs secret scanning over the full git history via gitleaks ([`.github/workflows/secret-scan.yml`](.github/workflows/secret-scan.yml)) on every push and pull request. One historical leak exists: a `.env` file with live database credentials was committed in early history; it is tracked in [SECURITY-ROTATE-ME.md](SECURITY-ROTATE-ME.md) with the required rotation steps — until those are completed, the exposed credentials must be treated as compromised.

## Content Safety

Transcripts and sign translations are user-generated content that gets broadcast to other meeting participants, persisted, and spoken aloud via TTS. A config-flagged output filter (`CONTENT_FILTER_ENABLED`, implemented in `backend/app/core/content_filter.py`) runs on this output before broadcast, persistence, and TTS synthesis. The policy: PII patterns (such as phone numbers, email addresses, and card-like number sequences) are redacted in place, and profanity is blocked from being voiced or displayed. The filter is applied server-side so it covers both pipeline directions (speech→sign and sign→speech), and it can be disabled per deployment via the config flag for environments where raw passthrough is required (e.g. accessibility evaluations with consenting participants).

---

Thanks for your help!

The community and I thank you for that. 🙇
