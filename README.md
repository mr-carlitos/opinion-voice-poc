# Opinion Voice PoC

White-label German voice/text thinking partner for an executive discussing
approved fictional railway documents. The intended runtime uses one Foundry
prompt agent, Voice Live, delegated Graph retrieval from SharePoint, and reviewed
Word summaries uploaded directly through Graph. See [plan.md](plan.md).

## Current Status

This is the tested repository foundation, **not a working cloud voicebot yet**.

- Implemented: deterministic Word rendering with required headings, source-ID
  validation, a localhost FastAPI startup screen, Python tests, Playwright desktop
  and mobile smoke flows, and credential-free GitHub Actions.
- Not implemented: voice, agent configuration, Graph authentication/retrieval,
  summary approval/session state, uploads/retry protection, Azure IaC, and avatar.
- The screen deliberately leaves session/export disabled. Liveness is not cloud
  readiness. No canned conversation or mocked upload is presented as success.

## Local Setup

Requirements: Python 3.12, [uv](https://docs.astral.sh/uv/), and Node.js 24.
Docker and Azure credentials are not required for this first increment.

```bash
uv sync --locked
npm ci
npx playwright install chromium
npm test
npm start
```

Open http://127.0.0.1:8000. The supported start command binds to loopback only.
Do not expose this development server remotely. Host validation is an additional
check, not a replacement for authentication. Cloud adapters must be implemented
before any non-synthetic or remote use.

On a Linux machine missing browser libraries, install Playwright's OS dependencies
with the documented `npx playwright install --with-deps chromium` setup command.
This may require administrator action. GitHub-hosted CI installs them automatically.

## Tests and Debugging

```bash
npm test
npm run test:python
npm run test:e2e
npx playwright show-report
```

Playwright starts/stops a real FastAPI server on port 8765; it fails rather than
reusing an unknown existing process. Each browser test gets an isolated context.
Python tests generate and reopen actual DOCX bytes in memory, without Office.

GitHub Actions runs the combined gate on pushes, pull requests, and manual dispatch.
There is no deployment workflow and no Azure/Graph credentials in CI. Failed tests
produce logs, JUnit/HTML reports, screenshots and traces in private workflow
artifacts with seven-day retention. See [testing strategy](docs/testing.md).

During active development the coding assistant can inspect failures directly:

```bash
gh run list --repo mr-carlitos/opinion-voice-poc --limit 5
gh run view RUN_ID --repo mr-carlitos/opinion-voice-poc --log-failed
gh run download RUN_ID --repo mr-carlitos/opinion-voice-poc --dir .local/ci/RUN_ID
```

Actions does not automatically launch an assistant or commit fixes between coding
sessions. Browser traces must never be enabled on real private user conversations
without an explicit data-handling decision.

## Configuration and Next Integration Check

[.env.example](.env.example) records the intended configuration names for upcoming
adapters. This foundation does **not yet consume** those values. Keep actual URLs
and configuration in ignored `.env` files; use interactive delegated sign-in and
do not store access tokens or passwords there. Never commit raw audio or summaries.

Next checkpoint: one approved SharePoint PDF read through Graph, a cited answer
by voice through the prompt agent, a typed follow-up, then approved DOCX rendering
and a real upload/download. Test safe retry and report permission limitations.
Azure/Graph checks will be explicitly opted-in, not run on ordinary CI pushes.