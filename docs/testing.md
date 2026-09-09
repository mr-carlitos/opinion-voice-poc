# Local Debugging

Scope: mixed FastAPI API and browser UI, localhost first. No legacy tests exist.
This is a repository foundation, not a completed cloud voicebot. GitHub Actions
and mandatory TDD are deferred. Implement the working demo first and inspect
runtime errors directly; use existing local checks only when helpful.

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
  `npm test` is an optional combined local check, including lint and format checks.
  None is a mandatory development or publishing gate.
- JUnit, HTML reports, browser console/request logs, server startup output, and
  Playwright failure traces/screenshots let the coding assistant inspect errors
  locally without the operator copying them into chat. Never capture real user
  sessions, credentials, raw audio, or private summaries in debugging artifacts.
- If the browser cannot install or launch, report the failure separately. API
  tests do not replace browser verification. Do not claim live E2E success.

## Development Loop

Implement the smallest useful integration, run it locally, inspect its output,
and repair observed failures. Do not require a new test before every feature,
coverage targets, a complete suite run, or GitHub Actions status. Keep fixtures
synthetic and in memory/temporary directories; no real secrets belong in tests.

Use an existing focused test or browser check when it saves debugging time.
Retain useful local tooling without expanding the test harness for its own sake.
Do not wait on remote CI runs or create authentication work solely for CI.

## Current Gaps

Voice, delegated identity, Graph retrieval/upload, approved-summary state,
idempotent remote saves, and avatar integration are not implemented or live-tested.
Do not add a passing placeholder for cloud tests. Add a separately opted-in local
live test once the service adapters and approved SharePoint folders exist. Keep
live writes explicit; publishing a repository does not authorize test writes to
Microsoft 365. The full live journey above remains unverified until exercised.