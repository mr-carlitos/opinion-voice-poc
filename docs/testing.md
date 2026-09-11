# Local Debugging

Scope: mixed FastAPI API and browser UI, localhost first. The Graph, Foundry,
Voice Live and reviewed-summary adapters are implemented, but the cloud voicebot
has not passed live end-to-end acceptance. GitHub Actions and mandatory TDD are
deferred. Exercise the working demo locally and inspect runtime errors directly;
use existing focused checks only when helpful. No CI wait or full suite is required.

## Evidence checkpoint — 10 September 2026

September11 diagnostic additions: synthetic tests verify browser failure stages,
ICE errors/state captured before peer cleanup, retained DOMException messages,
service detail propagation, shared diagnostic IDs, redaction/field allowlists,
bounded records and log rotation/private permissions. These tests do not identify
the cause of the operator's latest `browser_connection_failed`; a new reproduction
with the instrumentation is required. See setup.md for the log location.

**Integrated live result:** full Chromium with a synthetic German WAV microphone
passed the actual browser capture/worklet, Voice Live, GPT-5.1, SharePoint corpus
and reviewed Word-save journey. Typed follow-up retained spoken context; a changed
position appeared in the draft; version2 form edits were saved; the real downloaded
Word file retained the exact headings and edited stance. Repeat save returned the
same item. Session/conversation cleanup passed and no browser script errors occurred.

The ordinary headless-shell browser rejected `getUserMedia` with NotSupportedError;
the full installed Chromium (`channel: 'chromium'`) supported the synthetic audio
fixture. This was a test-environment issue, not evidence that a human microphone
works. No physical speaker audibility or actual microphone quality is claimed.

Backend startup was6.33s; validated conversational turns varied from5.37s to14.56s;
summary8.41s and reviewed upload3.62s. Full evidence checking remains required.
Human hardware, live barge-in/failure rehearsal and latency are still outstanding.

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
| Live conversation | Combined synthetic microphone/voice/text, reviewed-summary upload/download and repeat save passed. Human microphone/speaker rehearsal remains outstanding. |

Successful provisioning, a valid token, or successful consent alone does not
prove application readiness. Add observed results only after the actual operation
passes; do not upgrade historical foundation checks into current live evidence.

Startup follow-up: scoped connection reuse and immediate use of fresh download
URLs reduced a real six-PDF load from 16.27s to 4.84s (single comparison), with
19 versus 13 metadata requests including input-folder resolution. No cross-session
corpus cache was introduced. Post-download ID/version checks, scoped parent/drive
validation and streamed size limits remain enforced. Synthetic regression cases
also verify that bearer tokens are not sent to preauthenticated file URLs.

Local startup tests explicitly clear cloud configuration, even when ignored
`.env` is present. Both desktop/mobile startup and retry cases passed. They do not
authenticate against cloud services or claim live voice behavior.

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
5. Live acceptance (**synthetic input passed; human rehearsal pending**): review the
   selected identity and intended operations, connect that identity, read
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

Application-mode Graph PDF access, synthetic microphone/typed continuity and
the actual conversation's review/approval/upload/download/retry were verified live.
Human audio hardware and live interruption/failure-path rehearsal remain unverified.
The delegated file-access route still returned403.
Avatar transport is implemented and disabled by default. Deterministic signaling
and browser lifecycle tests are not evidence that native media works in Azure.
Do not label those tests as passing cloud avatar acceptance.

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
do not guarantee grounding or production privacy. The full synthetic-input journey
passed actual services; do not upgrade that to human audio-quality or production
acceptance.

## Native avatar v2 checks — 11 September 2026

Local validation: **152 Python tests and 34 desktop/mobile browser tests passed**.
Scoped Python lint/format and JavaScript syntax checks passed, as did
`git diff --check`. Repository-wide `npm run lint` encountered unrelated pending
format/import issues in `scripts/generate_sample_pdfs.py`,
`tests/test_foundry.py`, `tests/test_spoken_commands.py` and
`tests/test_streaming_mode.py`; those other worktree changes were preserved.

- `tests/test_avatar.py`: strict/default boundary, opt-in capability, ICE/SDP
  bounds and allowlisting, offer/answer lifecycle, greeting gate, no duplicate
  PCM, interrupt/clear, Stop, upstream/browser failures and server timeout.
- `tests/e2e/avatar.spec.js`: deterministic receive-only peer setup, delayed media
  readiness, one offer/readiness message, interrupt/playback mute, malformed
  answer, timeout, track/peer/media-element release (desktop and mobile Chromium).
- Voice, streaming, Foundry summary, session-version and HTTP edited-draft
  regressions run alongside these. The bridge passes a copied `user_turns` list
  to semantic summary validation and marks only a successful draft as validated.
  Mock validation failures reject edits and block saving; they are not live-model
  quality evidence.
- Real synthetic browser probe, existing resource: two bounded attempts received
  ICE; the diagnosed attempt returned `avatar_service_internal_error` before
  `session.avatar.connecting`, zero video width, zero decoded frames and no
  greeting. No complete avatar handshake or synchronized audio/video is claimed.
- Real explicit audio-only fallback: connected, 36 PCM chunks, one completed
  greeting, first received audio 1953ms after connection, avatar unchecked/hidden.
  This is not end-of-user-speech or first-audible timing. The owned test
  conversation was deleted after Stop; no document upload was performed.

No live service tokens, SDP, ICE credentials, screenshots or recordings were
captured. Test servers were local and no provisioning/grants/model change was
performed. Physical audio, real avatar frames, network recovery and a complete
avatar-to-Word rehearsal remain pending.

### Bounded avatar rejection follow-up — 11 September 2026

**Live acceptance remains blocked: no SDP answer, no video frames, no audible
avatar output.** Exactly two further live connections were opened; no retries
remain within this diagnostic budget. Neither model nor regional deployment,
authentication, grants or resources were changed.

- Resource Health reported `Available`, with no known Azure platform problem.
  The existing account is `ai-opinion-3ks5lhyvoieoi`, SwedenCentral; project and
  agent are `opinion-voice`, existing agent version `3`, model `gpt-5.1`, unchanged
  API version `2026-04-10`.
- Current application avatar request is already the minimal stock configuration:
  `character=lisa`, `style=casual-sitting`, `customized=false`. It does not specify
  an avatar type, resolution, bitrate, crop or other optional video settings.
  Both diagnostic connections requested that same avatar, modalities
  `["text","audio"]`, voice `azure-standard/de-DE-KatjaNeural`, and
  `turn_detection=null`; optional transcription/noise/VAD customization was omitted.
- Attempt 1: 16:33:35 UTC. The diagnostic reader failed on the initial
  `session.created` event's null avatar before collecting acceptance or error
  evidence. This was a diagnostic bug, not evidence of a cloud rejection. Its
  websocket closed; the owned empty conversation was identified by its exact
  creation time (16:33:34 UTC) and deleted. No offer or media was recorded.
- Attempt 2: 16:34:21–16:34:22 UTC. `session.updated` accepted
  `modalities=["audio","text","avatar"]`, the requested German voice, PCM16 input
  and output, disabled turn detection, and
  `avatar={type:"video-avatar",character:"lisa",style:"casual-sitting",
  customized:false,video:null,scene:null,model:null,image_prompt_url:null,
  output_protocol:"webrtc",output_audit_audio:false}`.
  Thus resolution was **not explicitly negotiated** (`video:null`), rather than
  an invalid requested resolution. The documented stock default is 1920×1080.
  Service ICE arrived; the browser gathered candidates and sent a receive-only
  audio/video offer at 16:34:22.151 UTC. At 16:34:22.542 UTC the service returned:
  - type: `server_error`
  - code: `avatar_service_internal_error`
  - message: `Avatar connection failed: WebRTC SDP negotiation failed: peer connect created failure: Failed to set remote video description send parameters`
  - param: null; error.event_id: null; no inner error/details/request ID supplied
  - server event ID: `event_6L51e2WhtOegPOq6ZDcMGi`
  - session ID: `sess_bAAfGn8rv04wsskVOIlUn`
  - client update/connect event IDs: `minimal-avatar-20260911-1` /
    `minimal-avatar-connect-20260911-1` (the diagnostic reused these labels).
  No HTTP request ID was captured. The websocket/browser were closed and this
  owned diagnostic conversation was deleted immediately.

**Concrete compatibility finding:** a subsequent offline capability check of the
installed Playwright Chromium found VP8, VP9 and AV1, but **no H.264** video
receiver codec. Microsoft documents H.264 as the real-time avatar codec. This
offers a concrete explanation for the remote video-description rejection; it
does not prove that a supported browser will pass the remaining service/media
handshake. No third live attempt was made. The player now checks H.264 support
before constructing/sending an incompatible offer and displays an explicit
browser-compatibility message. Ten scoped desktop/mobile avatar browser tests
passed, including codec rejection; JavaScript syntax and `git diff --check`
passed. These are local checks, not live media evidence.

Official primary references checked for this follow-up:
- Microsoft Learn `speech-service/voice-live-how-to`: stock `lisa` /
  `casual-sitting`, optional video settings, service-provided ICE flow.
- Microsoft Learn `speech-service/regions`: SwedenCentral supports real-time
  avatar.
- Microsoft Learn `speech-service/text-to-speech-avatar/what-is-text-to-speech-avatar`:
  default video resolution and H.264 real-time output.

Next action: explicitly authorize a new bounded live check using a browser whose
WebRTC receiver capabilities include H.264 (not this codec-limited test Chromium).
Verify increasing inbound `framesDecoded` and native audio with no PCM playback
path before claiming success. If the same rejection persists with H.264, open
Azure support for this existing SwedenCentral resource with the UTC time,
session/event IDs and accepted settings above; ask for the backend SDP
negotiation failure details. Do not send tokens, full SDP or ICE credentials.
No screenshots, recordings, secrets or media payloads were retained.