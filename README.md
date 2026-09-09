# Opinion Voice PoC

White-label German voice/text thinking partner for an executive discussing
approved fictional railway documents. The intended runtime uses one Foundry
prompt agent, Voice Live, delegated Graph retrieval from SharePoint, and reviewed
Word summaries uploaded directly through Graph. See [plan.md](plan.md).

## Current Status

The local implementation is substantially in place, but **the cloud voicebot
has not been verified end to end**. See the [handoff and next steps](docs/handoff.md)
for the saved state on 9 September 2026 and the [setup guide](docs/setup.md).

- Implemented in code: configuration, delegated Graph authentication/file access,
  bounded SharePoint PDF snapshots, Foundry prompt-agent/conversation integration,
  Voice Live bridge, browser controls, summary review, Word rendering/upload,
  synthetic PDFs, diagnostic commands and Bicep infrastructure.
- Locally checked: dependency imports, configuration, PDF extraction, schema/state
  probes, browser-script syntax, desktop/mobile rendering and Bicep compilation.
- Still pending: Azure sign-in renewal/provisioning, Graph app consent and folder
  configuration, live speech/text continuity, real upload/retry verification, and
  demo rehearsal. Avatar is not implemented.
- Liveness is not cloud readiness. No canned conversation or mocked upload is
  presented as live success. Existing local tests remain optional debugging tools.

## Local Setup

Requirements: Python 3.12 and [uv](https://docs.astral.sh/uv/).
Node.js, browser installation, test execution, and Docker are not required to
start the app. Azure credentials are not required for this first increment.

```bash
uv sync --locked --no-dev
uv run --frozen --no-dev uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

Open http://127.0.0.1:8000. The supported start command binds to loopback only.
Do not expose this development server remotely. Host validation is an additional
check, not a replacement for authentication. Cloud adapters must be implemented
before any non-synthetic or remote use.

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

[.env.example](.env.example) records the configuration names consumed by the app.
Keep actual URLs and configuration in ignored `.env` files; use interactive
delegated sign-in and do not store access tokens or passwords there. Never commit
raw audio or summaries. Missing configuration leaves integrations unavailable.

Next checkpoint: one approved SharePoint PDF read through Graph, a cited answer
by voice through the prompt agent, a typed follow-up, then approved DOCX rendering
and a real upload/download. Test safe retry and report permission limitations.
Azure/Graph checks will be explicitly opted-in and run locally.