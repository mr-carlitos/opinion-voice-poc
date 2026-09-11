# PoC Handoff - 10 September 2026

## Current resume point

This section supersedes the historical 9 September notes below.

- Diagnostic e428b451d4b4 identified the operator's actual avatar handshake failure:
  H264 supported, local offer created, ICE still gathering after30s, offer_sent=false.
  Browser previously waited exclusively for end-of-candidates. Added bounded3s
  gathering fallback to send the current offer once; late completion cannot send
  it twice and Stop clears both timers. Remote negotiation/network media success
  remains to be verified on the operator browser; this is not a codec failure.
- September11 avatar diagnostics: failures now produce a shared diagnostic ID
  in UI/terminal and ignored `.local/diagnostics.jsonl`. Browser preserves failure
  stage, WebRTC states, codec support, offer/answer flags and safe ICE errors
  before cleanup; actual exception names/messages are retained with redaction.
  Azure avatar errors retain safe service message/details and available session/
  event IDs. Bridge propagation preserves the same diagnostic ID. No raw SDP,
  ICE credentials, media or arbitrary event dump. Reproduce after server restart
  and hard refresh, then inspect the JSONL record rather than guessing from
  browser_connection_failed. The reported user failure has not yet been reproduced
  with this added instrumentation.
- September 11 v2 continuation: approved streaming/native-avatar code and
  redesigned conversation/review UI implemented. Local `.env` explicitly enables
  streaming and offers avatar selection; checked-in defaults remain strict/
  avatar-off. The legacy AVATAR_ENABLED flag is not the new capability switch.
- Summary validation now checks generated and edited drafts before they can be
  saved. Live regional-model probes accepted a correct30-vehicle fact and a changed
  subjective preference, rejected300 vehicles. The validator was clarified to
  recognize the common source appendix without requiring inline citations.
  These examples reduce uncertainty, not a guarantee of semantic correctness.
- Avatar live media remains blocked in the Linux test browser: accepted stock
  configuration/ICE, then SDP video negotiation rejection; installed Chromium
  lacks H.264. Browser codec guard now explains this. Test in desktop Chrome/Edge
  with H.264; real avatar frames/audio have NOT yet been verified.
- Interruption refinement: browser playback now stops as soon as the server sends
  speech_started, without waiting for transcription. Only when audio is playing
  does the browser report its item/playback position; stale reports cannot cancel
  a different new response. Speech onset alone still does not cancel pending
  generation/evidence checks. This supersedes the earlier no-playback-stop behavior.
  Actual onset delay still includes VAD/network detection; no zero-latency claim.
- Noisy-room follow-up: actual Voice Live probe confirmed missing-item errors
  omit the client event_id. Cleanup correlation now also matches the service's
  exact missing-item message to an outstanding ID we requested; unrelated errors
  remain visible. Successful deletion acknowledgments clear outstanding requests.
- Turn detection now uses azure_semantic_vad_multilingual, threshold0.6,
  speech_duration200ms, prefix420ms, silence500ms and azure_deep_noise_suppression.
  Configuration accepted live with existing GPT5.1 prompt agent/API version.
  A speech_started event alone no longer cancels model output or browser playback;
  only a transcribed contribution triggers interruption. This deliberately trades
  instant barge-in for resilience to noise. Browser acoustic echo cancellation is
  retained; server echo cancellation/filler suppression are not enabled because
  playback is delayed by our evidence gate. Real noisy-room acceptance still pending.
- The harmless malformed heading in the ignored reference credential file was
  changed to a dotenv comment; secret values were unchanged.
- Follow-up after failed human rehearsal: a delayed browser playback-interrupt
  report for an old answer could cancel the new response after its user transcript
  appeared. The bridge now distinguishes the reported playback item from the
  active response, clears the completed assistant item before starting a queued
  turn, and avoids duplicate finalization while evidence checking is running.
  Regression proves the next assistant answer is released after a stale
  interruption. A separate live synthetic cancellation/delete probe succeeded.
  The exact remaining cause of the operator's uncorrelated invalid-delete error
  is not proven; do not label human rehearsal passed until retested.
- Presentation patch: audio checkboxes replaced with explicit microphone and
  playback toggle buttons (aria-pressed); microphone access remains opt-in.
  Spoken "OK, jetzt Zusammenfassung erstellen" and equivalent affirmative
  phrases are accepted; negative/discussion phrases and save approval remain
  separate. Cancel cleanup is deduplicated and excludes non-message reasoning
  items; only invalid-ID errors correlated to our own cleanup request are treated
  as already-absent items, not blanket-suppressed.
- Conservative evidence optimization: full corpus and structured checks retained;
  compact corpus-first request, low verbosity, explicit reasoning none. A small
  correct/incorrect fact comparison measured3.36/1.52s before and1.67/1.47s after.
  This does not guarantee overall voice latency. No unchecked streaming or
  model/region change. Restart the operator-owned server to pick up this patch.
- **Latest fleet integration result:** full Chromium (not headless shell) passed
  the entire live journey with a synthetic German WAV fed through browser
  `getUserMedia`/AudioWorklet: one spoken question, cited fact, typed follow-up
  retaining context, changed position, summary, versioned form edit/apply, explicit
  button save, real Word download and same-item retry. All Azure/Graph/model calls
  were real; the microphone input was synthetic. No human audio hardware claim.
- Saved Word verification confirmed all three exact headings and the edited
  synthetic stance. Owned artifact identifiers/timings are in ignored
  `.local/live-browser-result.json`. The diagnostic app session and its Foundry
  conversation were deleted; the approved synthetic Word output remains.
- Measured integration timings: backend startup 6.33s (corpus 4.44s), start through
  validated greeting 12.6s, synthetic speech/cited answer 12.39s, typed contextual
  follow-up 5.37s, changed-position response 14.56s, summary 8.41s, approved upload
  3.62s. These are samples; evidence gating still produces noticeable latency.
- Scoped HTTP reuse and immediate use of freshly fetched download URLs reduced a
  separate same-corpus load from16.27s to4.84s. No cross-session source cache:
  version/ID rechecks, source scope, and download bounds remain enforced.
- Voice cancellation can now run while evidence checking is in flight. Cancelled,
  unsupported and unheard output is removed; accepted/queued turns are counted
  once. Review/save now captures the presented version and freezes bytes for safe
  failure/retry. HTTP recovery returns the authoritative review snapshot; stale
  edits/approvals are rejected. Browser drops stale audio and stops it on close.
- Reconnecting the same session's voice channel is explicitly rejected to avoid
  replaying the greeting/context. Review/save remains available over HTTP after
  disconnect. Delete the session and start another conversation when reconnecting.
- Current server: loopback port8010, attached process for this session. No new
  commits were made after checkpoint72cfc42; review the new fleet changes before
  committing. Remaining manual work: actual microphone/speaker rehearsal, live
  interruption/failure paths, and conversational latency.
- **Latest model migration, 10 September:** user selected GPT-5.1 Regional/Standard
  in Sweden Central over newer GPT-5.x EU Data Zone alternatives. Deployment
  `gpt-5.1`, version `2025-11-13`, Standard capacity 100 is succeeded and selected
  in `.env` and code/IaC defaults. The superseded `gpt-4.1-mini` GlobalStandard
  deployment was deleted after successful compatibility checks. No global fallback.
- Prompt agent version 2 passed actual Voice Live audio generation for the
  SharePoint fact, structured evidence checking, and summary. The API rejected
  `text.format` overrides with an agent reference; backend summary now calls the
  same model with the same conversation and repository instructions instead.
- Live measured sample: corpus load 16.21s; Voice session ready 0.38s; first
  upstream audio 1.29s; response completed 2.42s; evidence validation 16.4s;
  summary 11.27s. Metrics are in `.local/model-check.json`; no audio persisted.
  The probe's conversation was deleted. App buffers audio for evidence, so
  audible latency remains unresolved. Microphone/browser playback not yet tested.
- Model deployment geography does not certify every Speech/Foundry/M365 flow.
  Current Standard documentation permits operations across regions within the
  chosen Azure geography. Avoid fixed-region/datacenter or blanket EU-boundary claims.
- Next priority is evidence-check latency and the real browser voice/text/review
  journey using the new model. Earlier prompt version 1/model references below
  are historical. No server was running at the start of this migration.
- **Latest result:** the operator explicitly approved application-identity runtime
  reuse and synthetic file checks. `GRAPH_AUTH_MODE=application` is active, using
  the existing credential file without copying its secret into app configuration.
  Delegated mode remains available; no consent/ACL changes were made.
- Live file evidence: six PDFs uploaded and read back (12 pages), `30 Fahrzeuge`
  verified, synthetic Word upload/download succeeded, and retry reused the same
  item. SharePoint adds Word package metadata: integrity now checks authored
  parts plus narrowly allowed metadata changes, not raw ZIP byte equality.
  Source/stored hashes and owned item IDs are in ignored `.local` state.
- Application mode is labelled in the UI and document attribution. It is a
  local synthetic single-user identity, not per-user SharePoint permission
  trimming. Full microphone/voice/text and reviewed-summary acceptance remains
  outstanding.
- Browser evidence: the application-mode label/connect action worked without
  device sign-in. A real backend session was created with all six SharePoint
  sources and versions, then deleted together with its Foundry conversation.
  The first session attempt hit a Graph transport timeout and the successful
  retry was slow; startup latency/reliability still needs attention.
- The local server was started on `http://127.0.0.1:8010` as an attached CLI
  process. Check responsiveness before restarting it; no persistent background
  service or remote hosting was configured.
- Azure sign-in was restored and the approved minimal Sweden Central Foundry
  account, project, GPT-4.1-mini GlobalStandard capacity 20 and roles were
  provisioned. The quota-key mismatch and concurrent project/model creation
  conflict were repaired in the provisioning script and Bicep.
- The Foundry-only diagnostic returned a completed German text response using
  prompt agent version 1. This is not Voice Live or end-to-end evidence.
- The public-client app registration's broad Graph requests were replaced with
  **User.Read + Files.ReadWrite**. No app-only permissions, client secrets,
  tenant-wide consent or SharePoint ACL changes were introduced.
- The operator completed ordinary per-user consent. The grant is confirmed and
  the application's Graph `/me` call succeeded. The next input-folder
  `/shares/.../driveItem` request returned HTTP 403, request ID
  `693557f2-89cb-441b-b601-d0a3647d1991`. No document contents read or uploaded.
- That original error handler discarded Graph's error codes. The diagnostic now
  preserves safe nested codes/request IDs, reports both input and output metadata
  outcomes during `--resolve-folders`, and handles expected service errors without
  a traceback. It does not redeem links, widen scopes or change policies.
- New existing-access sharing links also returned 403 for both folders. The
  operator then supplied browser address-bar URLs. A separate read-only lookup
  with the existing Azure CLI operator login returned canonical library/folder
  IDs for both approved folders; both were empty. This proves operator metadata
  access, not runtime app access. No app consent or ACL changes were made.
- Ignored `.env` now uses those canonical URLs and verified IDs instead of
  sharing links. Discovery provenance is in ignored
  `.local/sharepoint-folder-discovery.json`. The runtime app's unchanged
  `User.Read` + `Files.ReadWrite` direct-ID check also returned HTTP 403
  `accessDenied` for both folders, after successful sign-in and `/me`.
  The input request ID was `958a04ec-1958-453d-acd3-68e0181ee664`; output was
  `39d926b2-c211-403e-b821-592a05c74149`. Sharing-link resolution is therefore
  not the sole blocker. Stop repeated sign-ins/link changes and review the
  app-specific authorization or policy. A selected-site/folder permission route
  needs separate approval and authorized resource grants; do not implement it
  automatically or substitute operator credentials for runtime reads/uploads.
- Reference comparison: the public Ruling Radar repository uses client-credentials
  authentication and application `Sites.Selected`, rather than delegated user
  tokens. An operator-owned registration matching its manifest was found; its
  actual Graph application `Sites.Selected` grant was confirmed. A site-grant
  listing under the operator identity was denied, so the write role is unknown.
- With the operator's explicitly supplied existing credential in ignored
  `.env.agenticrulingradar`, an isolated app-only check successfully resolved both
  approved folders by their verified IDs. No document contents read, no uploads
  or permission changes, no runtime authentication switch. The old app's separate
  broad delegated grants were not used. Secret values were not displayed or
  copied into this document. Metadata success does not establish write access.
- The operator subsequently approved reusing the existing application identity;
  the current runtime/file results are recorded at the top of this note.
  Do not describe guessed causes or successful consent as successful file access.
- Configuration is in ignored `.env`. Sharing links and tokens must not be
  copied into docs or logs. Tokens remain in memory; a new diagnostic invocation
  needs a fresh app sign-in, not another Azure CLI login.
- Background agents were cancelled after partial edits. Main assistant took
  over directly; there are no background coding agents. The local server state
  is described above and must be checked on resume. Changes are uncommitted.
  See [setup.md](setup.md).

## Historical checkpoint - 9 September 2026

## Pause and estimate

The operator asked to stop for the day. Resume from this note, not from the
earlier GitHub authentication or portal-only investigation. No deployment or
live write was attempted as part of this handoff.

Estimated baseline completion: **about 65% overall**. Roughly 75% of the planned
code is present, but live-demo readiness is only about 35-40%. These are engineering
estimates, not measured acceptance coverage. The real end-to-end customer journey
has not passed yet; integration problems can change the remaining effort.

Allow **5-9 hours of active development/integration work** for the baseline,
assuming Azure sign-in, model quota, Graph consent and SharePoint folders are
available promptly. Allow **another 1-3 hours** to attempt a stock avatar after
the baseline works. These are not delivery guarantees: tenant/admin waits are
additional elapsed time, and a Voice Live/Foundry compatibility problem could
push the baseline beyond this range. Skip the avatar if it risks the deadline.

## Decisions already made

- One Foundry **prompt agent**, not a hosted agent.
- Localhost FastAPI backend and a small German browser interface.
- Voice Live for speech and text in one Foundry conversation.
- Delegated Graph access to approved SharePoint PDFs, not Work IQ MCP or the
  native Copilot-based SharePoint retrieval service.
- For this small corpus, fetch a bounded full-text snapshot at session start.
  This is not query-time semantic retrieval. Repository PDFs are never the runtime
  knowledge fallback. Keep real document IDs, URLs and page references.
- Deterministic python-docx rendering and direct Graph upload after review and
  explicit approval. Input and output folders stay separate.
- Synthetic demo material only. Existing SharePoint ACLs remain unchanged;
  reviewer management and cross-user privacy verification are deferred, not passed.
- Azure target: Sweden Central, resource group `rg-opinion-voice-poc`.
  Switzerland North supports the core path but not the optional real-time avatar
  in the checked regional table. Current IaC uses Global Standard inference;
  no Sweden-only, EU-only or Swiss-only processing claim is warranted.
- Deadline over budget optimization; no further numeric-budget question needed.
- GitHub Actions disabled. No mandatory TDD, full test suite or remote CI wait.
  Existing local tests/Playwright are optional debugging aids.
- Avatar is optional and disabled by default. The native v2 transport is now
  implemented locally; see the dated update below for the live-service blocker.

The controlling decisions are also in [plan.md](../plan.md).

## What exists

| Area | Implementation | Evidence and remaining work |
| --- | --- | --- |
| Local app/configuration | [app/main.py](../app/main.py), [app/config.py](../app/config.py), [browser UI](../app/static/index.html) | Local server and desktop/mobile rendering checked. Missing cloud configuration leaves start disabled. |
| Graph authentication and files | [app/graph.py](../app/graph.py) | Device sign-in, folder resolution, download and upload/conflict handling implemented. Real Graph calls not yet verified. |
| Corpus handling | [app/grounding.py](../app/grounding.py) | Manifest-scoped PDF snapshot with bounds and source metadata. Needs a real SharePoint read. |
| Synthetic briefing pack | [sample-data](../sample-data/), [generator](../scripts/generate_sample_pdfs.py) | Six PDFs generated; text extraction and page counts checked. Not uploaded to SharePoint. Visual PDF inspection/evidence-key completeness should not be assumed. |
| Foundry | [app/foundry.py](../app/foundry.py), [instructions](../agent/instructions.md) | Agent versioning, conversation initialization, summary schema and evidence-check code implemented; live responses not verified. |
| Voice | [app/voice.py](../app/voice.py), [microphone code](../app/static/microphone.js) | SDK bridge, audio/text events, cancellation and spoken commands implemented; no completed live microphone-to-agent conversation yet. |
| Summary/export | [app/sessions.py](../app/sessions.py), [renderer](../app/export.py) | Draft/review/save code and real Word rendering. Foundational renderer checks passed; actual approved upload/retry flow remains unverified. |
| Azure | [infra/main.bicep](../infra/main.bicep), [provisioning script](../scripts/provision.sh) | Template compiled. Resource provisioning and live quota validation blocked by expired/revoked Azure sign-in. |
| Diagnostics | [scripts/live_check.py](../scripts/live_check.py), [setup guide](setup.md) | Runnable command entry points checked. Provides explicit Foundry, corpus upload and Word upload/download checks; not live success evidence. |

## Last known local evidence

- Dependency imports, configuration checks, summary/state probes, JavaScript
  syntax checks and PDF generation/extraction completed during implementation.
- The current Bicep template compiled locally, but was edited during the session:
  reread it before deployment and preserve operator edits.
- A real local browser check used installed Playwright Chromium, not the browser
  MCP service (which lacked Chrome). Desktop 1365x950 and mobile 390x844 rendered
  without horizontal overflow; the image loaded, retry worked, start remained
  disabled without configuration, and no browser script errors were observed.
- Screenshots are under ignored `.local/screenshots/`, named `app-1365.png` and
  `app-390.png`. Automated rendering checks passed; final visual review remains.
- Earlier foundation tests passed before the integration changes. Do not claim
  the old suite proves the current voice/Graph implementation.
- The last app address was http://127.0.0.1:8010. It may still be running. Check
  the existing process before starting another; do not kill unrelated terminals.

## Blockers and risks

1. **Azure sign-in:** model/quota calls returned `AADSTS50173` (revoked grant).
   The operator must renew interactive Azure CLI sign-in. Cached account metadata
   alone does not prove a usable access token. Do not repeat auth in a loop.
2. **Azure resources:** no new PoC resources were created at the last provisioning
   attempt. Check actual state before applying IaC; do not assume it is empty if
   the operator has since made changes. Model/SKU/capacity and roles need live checks.
3. **M365 prerequisites:** an approved public-client app registration and delegated
   Graph consent are needed. See [setup.md](setup.md) for the current requested
   scopes and their broad access implications. Do not silently grant consent or
   weaken tenant policy. Azure sign-in and M365 device sign-in are separate.
4. **Folder configuration:** the operator has not yet supplied input/output URLs.
   Put real values in ignored `.env` using [.env.example](../.env.example).
   Use direct folder URLs, not browser view/sharing links. Do not store tokens.
5. **Highest technical uncertainty:** a Graph-preloaded conversation must work
   with this exact Voice Live prompt-agent mode, SDK versions and API settings.
   Speech/text continuity, supported event names, interruption and spoken save
   need real checks. Generic SDK examples are not proof of the combination.
6. **Latency:** assistant audio is currently buffered until a second model call
   checks evidence. Measure the actual time to first audible reply early; this
   may be too slow for a convincing natural conversation. Do not silently bypass
   grounding checks or claim the model validator guarantees correctness.
7. **Snapshot limits:** source updates appear only in a new session; permission
   revocation is not rechecked mid-session. No native permission-trimming parity
   or instant refresh claim. The current brief retains the approved Graph route's
   C2 incompleteness label pending explicit revision and live evidence.
8. **Privacy/cleanup:** localhost single-user demo only. Sessions/tokens are in
   memory. Service-side conversations can survive a process crash. No complete
   multi-user isolation, retention automation or production-readiness claim.

## Resume order

1. Read this file, [setup.md](setup.md), the top of [plan.md](../plan.md), and git
   status. Preserve uncommitted work, especially recent IaC edits. Do not return
   to GitHub workflow authorization, CI watching, or general architecture research.
2. Ask the operator to renew Azure sign-in using the existing setup instructions.
   Confirm the authorized subscription and inspect live resource/model/quota state.
   Run the provisioning script's check first, then its explicit `--apply` path
   subject to the required deployment procedure. Use real deployment outputs in
   `.env`; do not invent endpoints. No new app hosting/search/database is needed.
3. Run the Foundry-only diagnostic first to isolate Azure auth, model and prompt
   agent issues from M365. It creates/reuses an agent version and incurs model
   usage; it is not merely a read-only health check.
4. Obtain the two SharePoint URLs and approved Graph app client ID/consent. Resolve
   both folders, explicitly upload the manifest PDFs, then read them back through
   Graph. Verify the distinctive fact `30 Fahrzeuge` in the SharePoint corpus.
5. Run the synthetic Word upload/download check independently of voice. Verify
   actual bytes and the returned item URL. Repair auth/path/conflict issues here
   before combining services.
6. Start the local app and exercise one full live journey: German greeting,
   speech question about that fact, real citation, typed follow-up retaining
   context, changed position, summary with three exact headings, edit/apply,
   explicit button/spoken approval, real upload and authorized download.
7. Check only critical failure paths: unsupported question, stop/barge-in, no
   duplicate turns, refusal to save an unapproved or stale draft, repeat save,
   and an upload failure not reported as success. Inspect terminal/browser output
   directly; no CI wait or new full test harness.
8. Correct observed integration defects, measure response latency, inspect the
   Word/PDF layout and rehearse the short customer scenario. Update live evidence
   and limitations honestly. Fill remaining evidence-key/demo-guide gaps only
   after the vertical slice works.
9. Attempt a stock avatar only if the baseline is stable and time permits.
   Verify regional/network/WebRTC support, retain the audio-only switch, and skip
   rather than compromise the baseline.
10. Review and commit/push the finished work when authorized. Keep credentials,
    `.local`, raw audio, user summaries and debug artifacts out of Git. Finish
    documentation and an owned-artifact cleanup checklist.

### Existing local commands

Run from the repository root. The diagnostics below are optional and explicit;
the upload commands write synthetic artifacts to the configured SharePoint folders.
They are documented here for the next session, not executed during this handoff.

```bash
uv sync --locked --no-dev
uv run --frozen --no-dev python scripts/live_check.py --foundry-only
uv run --frozen --no-dev python scripts/live_check.py --upload-corpus
uv run --frozen --no-dev python scripts/live_check.py --save-example
uv run --frozen --no-dev uvicorn app.main:app --host 127.0.0.1 --port 8010 --no-access-log
```

The CLI Graph check and browser app have separate in-memory authentication
sessions; signing in to one does not automatically sign in the other.

## Effort estimate by remaining area

| Work | Active effort, assuming prerequisites available |
| --- | --- |
| Azure provisioning and M365 setup | 1-2 hours |
| Live Graph and voice/conversation integration fixes | 2-4 hours |
| Review/export failure handling, latency, rehearsal and docs | 2-3 hours |
| Optional stock avatar | +1-3 hours |

The baseline is **5-9 hours**, not a promise of a finished demo at a specific
time. If consent cannot be obtained or the chosen voice/conversation path is
unsupported, report the blocker and smallest alternative; do not silently switch
agent type, use local files as runtime grounding, or call mocks end-to-end success.

## Repository and pause state

- Private repository: https://github.com/mr-carlitos/opinion-voice-poc.
- The operator requested a commit and push of the complete end-of-day checkpoint
   on `main`, including application code, IaC, synthetic data and this handoff.
   Check git status and the remote commit when resuming for any subsequent edits.
   Ignored credentials, environment settings and local diagnostic artifacts are
   intentionally excluded from the checkpoint. Do not reset/clean the worktree.
- The local CI workflow is deleted and repository Actions were disabled earlier.
  Do not restart remote-run monitoring. Local tests remain available on demand.
- This handoff adds documentation only. It does not change the application,
  deploy resources, stop local servers or remove artifacts.

## Native v2 implementation update — 11 September 2026

This update supersedes earlier statements that avatar transport is unimplemented.
Local capability/session opt-in, bounded ICE/base64-SDP forwarding, vanilla
WebRTC media, greeting gate, no duplicate PCM, interruption/clear, timeout,
fallback and cleanup are implemented. `strict`/audio-only remains the default;
`streaming` explicitly forgoes independent conversational pre-speech checking.
Generated and edited summaries retain semantic checks and version-bound save.
The single prompt agent and GPT-5.1 Standard Sweden Central deployment are unchanged.

Native **live acceptance is blocked**: the existing resource returned ICE, then
`avatar_service_internal_error` before an SDP answer; no avatar frames or greeting.
No root cause is proven by that code. Audio-only streaming on the same resource
did produce a complete greeting, first received PCM at 1.953 seconds after
connection. Synthetic probing did not upload documents, change Azure resources,
change grants, record media, or log transient signaling credentials.

Preserve all uncommitted work. No implementation commit/push was requested in
this task. Use `docs/setup.md` and `docs/testing.md` for configuration, contracts,
tests and the explicit outstanding real-avatar/human-rehearsal boundary.
