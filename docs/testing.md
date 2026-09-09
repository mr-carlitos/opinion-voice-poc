# Testing Strategy

Scope: mixed FastAPI API and browser UI, localhost first. No legacy tests exist.
This first increment establishes CI, not a completed cloud voicebot.

## Critical Journeys

1. Startup: liveness succeeds, readiness reports unavailable integrations, and
   session/export requests fail closed. The browser cannot imply a working service.
2. Word export: synthetic structured content becomes a real DOCX, is reopened,
   and preserves the three required headings, empty categories, and source metadata.
3. Validation: invented source IDs and model-supplied destination/owner are rejected.
4. Browser recovery: a failed readiness request is visible and retry recovers without
   enabling an unavailable voice session. Capture console errors and failed requests.
5. Live acceptance (not implemented yet): sign in, read a known PDF through Graph,
   ask by speech, follow up by text, review and approve, upload a real DOCX, download
   and verify it, retry without duplication, then clean up only test-owned artifacts.

## Tooling and Evidence

- Python 3.12 + uv: pytest, FastAPI TestClient, and real python-docx rendering.
- Node.js + Playwright: Chromium desktop/mobile against a real local HTTP server.
- No database or Docker is required. No mock Azure/Graph response is counted as
  live evidence. Browser network-failure injection is labelled as such.
- Unit/API tests run with `uv run pytest`; browser tests with `npm run test:e2e`.
  `npm test` is the combined local/CI gate, including lint and format checks.
- CI needs no Azure/M365 secrets. Pushes, pull requests, and manual dispatch run
  the same gate. Failed commands fail the job; no continue-on-error or hidden retries.
- JUnit, HTML reports, browser console/request logs, server startup output, and
  Playwright failure traces/screenshots let the coding assistant inspect errors.
  CI retains synthetic test artifacts for seven days. Never capture real user
  sessions, credentials, raw audio, or private summaries in CI artifacts.
- If the browser cannot install or launch, report the failure separately. API
  tests do not replace browser verification. Do not claim a green E2E gate.

## Proportionate TDD

Write one focused failing check for each risky behavior, implement it, then rerun
that check before widening scope. Keep fixtures synthetic and in memory/temporary
directories; no real deployment IDs or secrets belong in tests. No coverage quota.

During an active coding session, inspect local output and GitHub Actions logs,
repair failures, rerun locally, and push the fix. GitHub Actions reports failures
between sessions; it does not start an autonomous coding assistant or auto-push fixes.

## Current Gaps

Voice, delegated identity, Graph retrieval/upload, approved-summary state,
idempotent remote saves, and avatar integration are not implemented or live-tested.
Do not add a passing placeholder for cloud tests. Add a separately opted-in local
live test once the service adapters and approved SharePoint folders exist. Keep
cloud tests off ordinary CI; publishing a repository does not authorize test writes
to Microsoft 365. The full live journey above remains unverified until exercised.