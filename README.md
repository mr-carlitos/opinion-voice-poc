# Opinion Voice PoC

White-label German voice/text thinking partner for an executive discussing
approved fictional railway documents. The intended runtime uses one Foundry
prompt agent, Voice Live, configurable Graph access to SharePoint, and reviewed
Word summaries uploaded directly through Graph. See [plan.md](plan.md).

## Current Status

**The complete journey passed with synthetic microphone input in full Chromium
against real Azure and SharePoint services.** A human microphone/speaker rehearsal
and conversational-latency assessment remain outstanding. See the [handoff](docs/handoff.md)
for the current checkpoint on **10 September 2026** and the [setup guide](docs/setup.md).

- Implemented in code: configuration, delegated/application Graph authentication,
  bounded SharePoint PDF snapshots, Foundry prompt-agent/conversation integration,
  Voice Live bridge, browser controls, summary review, Word rendering/upload,
  synthetic PDFs, diagnostic commands and Bicep infrastructure.
- Locally checked: dependency imports, configuration, PDF extraction, schema/state
  probes, browser-script syntax, desktop/mobile rendering and Bicep compilation.
- Provisioned: Azure sign-in is restored; the minimal Sweden Central
  `rg-opinion-voice-poc` Foundry account/project now uses **GPT-5.1 `2025-11-13`,
  Standard (capacity 100)**. The former GPT-4.1-mini GlobalStandard deployment
  was retired on 10 September after successful replacement checks. No Azure app
  hosting, database or search service was provisioned. This is infrastructure
  success, not proof of application readiness.
- Microsoft 365: the operator approved application mode using an existing
  `Sites.Selected` application identity. Six synthetic PDFs were uploaded and read
  back (12 pages), including `30 Fahrzeuge`. A synthetic Word file was uploaded,
  downloaded and verified; a repeated save reused the same remote item.
- Word integrity: SharePoint added document-package metadata. Verification checks
  the authored Word parts and permitted metadata changes, not raw ZIP byte
  equality. The source/stored hashes are recorded in ignored local state.
- Delegated mode remains available with `User.Read` + `Files.ReadWrite`, but its
  sharing-link and direct-ID folder requests returned 403 in this tenant.
  Application mode is explicitly labelled; it is not per-user permission trimming.
- Regional-model live check: prompt agent version 2 used GPT-5.1, Voice Live
  generated German audio with the correct SharePoint fact, and structured evidence
  checking/summary generation succeeded. Microphone input/browser playback were
  not tested by that probe. First upstream audio was 1.29 seconds; evidence checking
  added 16.4 seconds. The app buffers audio for evidence checking, so this is
  not evidence of 1.29-second user-perceived response time.
- Integrated live journey: synthetic German microphone question, cited answer,
  typed follow-up retaining context, changed position, structured summary, form
  edit/apply, explicit save, actual Word download and same-item retry all passed.
  The saved document preserved the three exact headings and edited stance.
- Startup improved: the six-PDF load fell from 16.27s to 4.84s in a direct
  comparison; a complete browser session started in 6.33s. No corpus cache was added.
- Still pending: real human microphone/speaker rehearsal, live interruption and
  failure-path rehearsal, and lower/less variable response latency. Measured
  validated turns took about 5-15 seconds, not a natural-conversation sign-off.
  Native stock-avatar transport is implemented but disabled by default; the
  real handshake on 11 September 2026 failed with `avatar_service_internal_error`
  after ICE configuration, before an SDP answer or video frames.
  Audio-only streaming fallback returned a greeting (first received PCM 1.953s
  after connection; not a physical audio-latency measurement).
- Liveness is not cloud readiness. No canned conversation or mocked upload is
  presented as live success. Existing local tests remain optional debugging tools.

## Local Setup

Requirements: Python 3.12 and [uv](https://docs.astral.sh/uv/).
Node.js, browser installation, test execution, and Docker are not required to
start the local server. Azure and the configured Microsoft 365 identity are
required for the implemented live integrations, not for startup/liveness alone.

```bash
uv sync --locked --no-dev
uv run --frozen --no-dev uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

Open http://127.0.0.1:8000. The supported start command binds to loopback only.
Do not expose this development server remotely. Host validation is an additional
check, not a replacement for authentication. Cloud adapters are implemented but
the synthetic-input journey is verified, not human audio hardware. This remains a localhost, single-user,
synthetic-data demo; remote access and real customer data are not approved.

With Node.js installed, `npm start` is a shortcut for the same server command;
it does not run tests or wait for GitHub.

## Optional Local Debugging

GitHub Actions and mandatory test-driven development are out of scope for this
demo. Develop and run locally, inspect server/browser errors directly, and use
only the focused checks that help diagnose the current problem. No remote run
or full test suite is a prerequisite for continuing development.

The existing checks remain available on demand. To use them, install the dev
dependencies (Node.js 24 is needed for the browser checks):

```bash
uv sync --locked
npm ci
npx playwright install chromium
```

On Linux, missing browser libraries may require an administrator to run the
documented `npx playwright install --with-deps chromium` setup command.

```bash
npm run test:python
npm run test:e2e
npx playwright show-report
```

Playwright starts/stops a real FastAPI server on port 8765; it fails rather than
reusing an unknown existing process. Each browser test gets an isolated context.
Python tests generate and reopen actual DOCX bytes in memory, without Office.

Local reports, screenshots, traces, and server output can be inspected directly
by the coding assistant during development. `npm test` is an optional combined
check, not a required gate. See [debugging notes](docs/testing.md).
Browser traces must never be enabled on real private user conversations without
an explicit data-handling decision.

## Configuration and Next Integration Check

Model defaults are GPT-5.1 `2025-11-13`, Standard, capacity 100 in Sweden Central.
Provisioning rejects GlobalStandard; no global fallback is configured.
Standard constrains inference to the selected Azure geography, not necessarily
one datacenter/region within that geography. This is not a blanket end-to-end
EU Data Boundary assessment of Voice Live, Foundry storage and Microsoft 365.
See [Microsoft's deployment-type guidance](https://learn.microsoft.com/en-us/azure/foundry/foundry-models/concepts/deployment-types).

`scripts/check_model.py` is an explicitly billable live diagnostic using the real
SharePoint corpus: typed input over Voice Live, generated audio (not persisted),
evidence validation and a structured summary. It cleans up its conversation and
saves timing/status metrics to ignored `.local/model-check.json`. It does not
exercise microphone capture, browser playback or user approval/save.

[.env.example](.env.example) records the configuration names consumed by the app.
Keep real client IDs, deployment endpoints and SharePoint sharing-link URLs in
ignored `.env`, not documentation, deployment-state records or screenshots.
`GRAPH_AUTH_MODE=delegated` uses interactive device sign-in with `GRAPH_CLIENT_ID`.
The approved demo uses `GRAPH_AUTH_MODE=application` and
`GRAPH_APPLICATION_CREDENTIALS_FILE` pointing to a separate ignored file containing
`GRAPH_TENANT_ID`, `GRAPH_APP_CLIENT_ID` and `GRAPH_APP_CLIENT_SECRET`. The file must
remain inside the local project; its other settings do not override the app.
No token or secret is returned to the browser. Never commit credentials, raw audio
or summaries. The backend uses Azure CLI identity only for Foundry.

- Keep `SHAREPOINT_INPUT_FOLDER_URL` and `SHAREPOINT_OUTPUT_FOLDER_URL`. Supply
  approved HTTPS commercial SharePoint folder sharing links for initial Graph
  `/shares` resolution, without automatic link redemption or new access grants.
- Alternatively, pair each canonical folder URL with its
  `SHAREPOINT_INPUT_DRIVE_ID` / `SHAREPOINT_INPUT_FOLDER_ID` or
  `SHAREPOINT_OUTPUT_DRIVE_ID` / `SHAREPOINT_OUTPUT_FOLDER_ID`. IDs become
  authoritative only after Graph validation; never guess them from a sharing link.
  Direct URLs without paired IDs are unsupported because there is no site discovery.
- Input/output separation is checked against resolved canonical URLs and IDs.
  Missing configuration or denied access fails explicitly, never to local PDFs.
- Neither delegated `Files.ReadWrite` nor application `Sites.Selected` is a
  two-folder token boundary. Application mode uses the app's existing site grants,
  not the browser user's SharePoint rights; folder allowlists do not change ACLs.
  Reviewer management and multi-user privacy remain deferred; the approved Graph
  route retains its reduced-scope **C2 incomplete** label.

The [setup guide](docs/setup.md) documents the read-only registration check,
explicit `--apply --narrow-permissions` legacy migration, and operator review
before ordinary device consent. Setup never grants consent or directory roles;
admin consent or tenant-policy changes are not the default remedy for a denial.

Next checkpoint: rehearse with the operator's actual microphone and speakers,
interrupt an answer, exercise an unsupported question and inspect perceived latency.
The synthetic-input combined journey and actual reviewed Word save passed;
they do not establish physical audio quality or universal model behavior.
Azure/Graph checks remain explicitly opted-in and local;
`--upload-corpus` and `--save-example` write approved synthetic artifacts.