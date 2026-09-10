# Local Debugging

Scope: mixed FastAPI API and browser UI, localhost first. The Graph, Foundry,
Voice Live and reviewed-summary adapters are implemented, but the cloud voicebot
has not passed live end-to-end acceptance. GitHub Actions and mandatory TDD are
deferred. Exercise the working demo locally and inspect runtime errors directly;
use existing focused checks only when helpful. No CI wait or full suite is required.

## Evidence checkpoint — 10 September 2026

The latest model is **GPT-5.1 `2025-11-13`, Standard capacity 100 in Sweden Central**;
the former GlobalStandard GPT-4.1-mini deployment has been deleted. These model
facts supersede older entries in the table. Runtime summary/evidence calls use the
same deployment; no global fallback is configured.

`scripts/check_model.py` passed a real typed-input Voice Live request with generated
audio and the corpus fact, evidence validation and structured summary. It does not
test microphone or browser playback. Sample timings: first upstream audio 1.29s,
response completion 2.42s, evidence check 16.4s, summary 11.27s. Audio buffering
means actual audible latency includes evidence time. This is a compatibility
result, not a natural-conversation performance sign-off.

| Area | Recorded status |
| --- | --- |
| Local implementation | Imports/configuration, PDF extraction, state/schema probes, browser syntax/rendering and Bicep compilation were checked previously. These are not live integration evidence. |
| Azure infrastructure | Login restored; minimal Sweden Central `rg-opinion-voice-poc` Foundry account/project and GPT-4.1-mini `2025-04-14` GlobalStandard capacity 20 provisioned successfully. No Azure hosting/database/search services. |
| Graph registration/consent | Public-client app exists without secrets or app-only permissions. Broad requests were replaced with `User.Read` + `Files.ReadWrite`. Ordinary per-user consent and `/me` profile lookup succeeded. |
| SharePoint folder resolution | Input sharing-link metadata request returned HTTP 403 after successful sign-in. The initial diagnostic discarded provider error codes; exact cause remains unknown. No document contents read or uploaded. |
| Foundry text | Foundry-only diagnostic created/reused prompt agent version 1 and returned a completed German response. No Voice Live claim. |
| Application identity | Existing application `Sites.Selected` role verified; isolated metadata access succeeded. Operator explicitly approved reuse for this synthetic demo. Runtime supports labelled application mode without changing grants/ACLs. |
| Live file access | Six manifest PDFs uploaded/read back, 12 pages and `30 Fahrzeuge` verified. Synthetic Word upload/download verified authored package content; retry reused the same item. |
| Word storage metadata | SharePoint changed the ZIP package by adding property/custom XML metadata. Original Word payload parts remain identical; allowlisted metadata comparison replaces invalid raw-byte assumptions. Unexpected parts/content or changed relationships fail closed. |
| Browser/backend | Application-mode label and connection worked without a device code. A real six-source session was created and cleaned up. First attempt hit a Graph transport timeout; successful retry was slow, so startup latency/reliability remains a concern. |
| Live conversation | The combined microphone/voice/text, reviewed-summary journey remains **UNVERIFIED**. |

Successful provisioning, a valid token, or successful consent alone does not
prove application readiness. Add observed results only after the actual operation
passes; do not upgrade historical foundation checks into current live evidence.

`--resolve-folders` now reports each folder separately, retains safe Graph error
codes/request IDs, and exits nonzero without a traceback for expected service
failures. It saves no successful configuration if either folder fails, and does
not read document contents, upload files, redeem links or change permissions.
Focused synthetic cases cover 403/Conditional Access reporting and these no-write
boundaries; they do not establish real SharePoint access.

## Critical Journeys

1. Startup without required configuration: liveness succeeds, readiness reports
   unavailable integrations, and session/export requests fail closed. With
   configuration present, startup alone still does not prove live access. The
   browser cannot imply a working service from liveness.
2. Word export: synthetic structured content becomes a real DOCX, is reopened,
   and preserves the three required headings, empty categories, and source metadata.
3. Validation: invented source IDs and model-supplied destination/owner are rejected.
4. Browser recovery: a failed readiness request is visible and retry recovers without
   enabling an unavailable voice session. Capture console errors and failed requests.
5. Live acceptance (**implemented path, UNVERIFIED**): review the narrow
   registration and intended operations, complete ordinary device sign-in, read
   one approved PDF through Graph, verify a synthetic DOCX upload/download, then
   ask by speech, follow up by text, review and approve, upload/download the reviewed
   summary and retry without duplication. Clean up only test-owned artifacts.

## Identity and Folder Checks

The approved runtime now uses `GRAPH_AUTH_MODE=application` and a separately
ignored credential file. Application authentication must use Graph `.default`
without a device-code prompt or `/me`; no delegated/CLI fallback is allowed.
The UI and local document attribution must clearly identify application mode,
not a human user. Focused checks cover the tenant/file guard, secret redaction,
both identity modes and the no-write diagnostic boundaries.

Use the [setup guide](setup.md) for the read-only registration plan and explicit
`--apply --narrow-permissions` migration of only the expected owned legacy app.
The script never grants consent or directory roles. Azure CLI login and the
application's delegated device sign-in are separate, with runtime Graph tokens
in process memory. Do not repeat Azure login to solve a Graph consent problem.

For the retained delegated alternative and common folder adapter:

- The reviewed public-client request contains `User.Read` + `Files.ReadWrite`,
  not the old `Sites.Read.All` / `Files.ReadWrite.All`, app-only permissions or a
  client secret. Tenant policy controls ordinary user consent; the prior 403
  admin-consent failure does not make user consent intrinsically admin-only.
- An approved HTTPS commercial SharePoint folder sharing link resolves through
  Graph `/shares` without automatic redemption or new access grants. Resolution
  denied by the selected API/scope is a real blocker, not a reason to broaden access.
- A canonical folder URL requires both matching drive/folder IDs for its input
  or output setting; direct URLs without IDs fail explicitly because there is no
  site discovery. IDs are authoritative only after Graph validation, never after
  guessing from a sharing-link token.
- Resolved canonical URLs/IDs identify separate input/output folders. Same-folder
  aliases and parent/child overlap are rejected; changing link spelling cannot
  bypass separation. Missing or denied configuration never selects local PDFs.
- One approved PDF is actually read from the exact library with real item/version,
  source URL and page evidence. Follow with an approved synthetic DOCX write and
  download to the separate output library. A token or folder-resolution success
  does not prove either file operation will work.

`--foundry-only` isolates Foundry and can create/reuse an agent version and incur
model usage. `--upload-corpus` explicitly writes approved synthetic manifest PDFs;
`--save-example` explicitly writes and downloads a synthetic DOCX. Neither write
flag is a read-only consent probe or authorized merely by publishing the repo.
Keep real sharing links only in ignored `.env`, never screenshots, logs or local
deployment-state records. Record sanitized outcomes and necessary resolved IDs.

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
synthetic and in memory or ignored project-local artifacts; no real secrets
belong in tests.

Use an existing focused test or browser check when it saves debugging time.
Retain useful local tooling without expanding the test harness for its own sake.
Do not wait on remote CI runs or create authentication work solely for CI.

## Current Gaps

Application-mode Graph PDF access and independent synthetic Word upload/retry
are verified live. Voice continuity and the actual conversation's review/approval
workflow remain unverified. The delegated file-access route still returned 403.
Avatar remains disabled and unimplemented. Do not add a passing placeholder for
cloud tests; use the existing, separately opted-in local diagnostics and manual
journey rather than building a new harness.

`Files.ReadWrite` is not a two-folder token security boundary. Prefer a dedicated
non-admin synthetic test identity; application restrictions do not narrow all
access available to that token or change SharePoint ACLs. Exact-library/API scope
support was denied in this tenant. The explicitly approved application
`Sites.Selected` identity now supplies access, not participant-level permission
trimming. Folder-selected grants remain a separately approved alternative.

The approved Graph snapshot route remains **C2 incomplete**. Permission revocation
is not rechecked mid-session; a new session is required to refresh source content.
Reviewer management and multi-user privacy, including A15/A17, are deferred and
unverified. Prompt-based behavior in `agent/instructions.md` and evidence checks
do not guarantee grounding or production privacy. The full live journey remains
**UNVERIFIED** until exercised with actual services and approved synthetic data.