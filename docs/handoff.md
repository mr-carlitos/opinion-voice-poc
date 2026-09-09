# PoC Handoff - 9 September 2026

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
- Avatar is optional, disabled and not implemented. Keep an audio-only fallback.

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
