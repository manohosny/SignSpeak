// k6 baseline load test for SignSpeak.
//
// Targets the cheap, always-on HTTP surface (liveness, readiness, OpenAPI,
// frontend shell) to measure transport + app-server capacity without
// exercising the ML models. WebSocket/ML load is bounded separately by
// design: one model inference at a time per engine, with per-connection
// buffering (see backend/app/ws/).
//
// Usage:
//   k6 run loadtest/k6-baseline.js                                   # local compose
//   k6 run -e API_BASE=https://api.<ip>.sslip.io \
//          -e WEB_BASE=https://dashboard.<ip>.sslip.io \
//          -e INSECURE=1 loadtest/k6-baseline.js                     # production
//
// Pass -e MAX_VUS=100 to raise concurrency. Defaults are deliberately
// modest so the test is safe to run against the live single-VM deploy.

import http from 'k6/http'
import { check } from 'k6'

const API_BASE = __ENV.API_BASE || 'http://localhost:8000'
const WEB_BASE = __ENV.WEB_BASE || 'http://localhost:5173'
const MAX_VUS = Number(__ENV.MAX_VUS || 50)
// /api/v1/openapi.json is intentionally disabled outside ENVIRONMENT=local
// (backend/app/main.py) — pass SKIP_OPENAPI=1 when targeting staging/prod.
const SKIP_OPENAPI = __ENV.SKIP_OPENAPI === '1'
// Pass SKIP_WEB=1 when no frontend is serving (API-only baseline).
const SKIP_WEB = __ENV.SKIP_WEB === '1'

const scenarios = {
  api: {
    executor: 'ramping-vus',
    exec: 'apiSurface',
    startVUs: 1,
    stages: [
      { duration: '15s', target: Math.ceil(MAX_VUS / 4) },
      { duration: '30s', target: MAX_VUS },
      { duration: '30s', target: MAX_VUS },
      { duration: '15s', target: 0 },
    ],
  },
}
if (!SKIP_WEB) {
  scenarios.web = {
    executor: 'constant-vus',
    exec: 'webShell',
    vus: Math.max(2, Math.ceil(MAX_VUS / 10)),
    duration: '90s',
  }
}

export const options = {
  insecureSkipTLSVerify: __ENV.INSECURE === '1',
  scenarios,
  thresholds: Object.assign(
    {
      // The checklist asks for average and p95 latency under concurrency.
      'http_req_duration{endpoint:livez}': ['p(95)<500', 'avg<200'],
      http_req_failed: ['rate<0.01'],
    },
    SKIP_OPENAPI ? {} : { 'http_req_duration{endpoint:openapi}': ['p(95)<1000'] },
  ),
}

export function apiSurface() {
  const live = http.get(`${API_BASE}/api/v1/utils/healthz/live`, {
    tags: { endpoint: 'livez' },
  })
  check(live, { 'livez 200': (r) => r.status === 200 })

  const ready = http.get(`${API_BASE}/api/v1/utils/healthz/ready`, {
    tags: { endpoint: 'readyz' },
  })
  // 200 = models warm, 503 = still loading; both prove the server answers
  // under load instead of hanging or crashing.
  check(ready, { 'readyz answers': (r) => r.status === 200 || r.status === 503 })

  if (!SKIP_OPENAPI) {
    const spec = http.get(`${API_BASE}/api/v1/openapi.json`, {
      tags: { endpoint: 'openapi' },
    })
    check(spec, { 'openapi 200': (r) => r.status === 200 })
  }
}

export function webShell() {
  const page = http.get(`${WEB_BASE}/`, { tags: { endpoint: 'frontend' } })
  check(page, { 'frontend 200': (r) => r.status === 200 })
}
