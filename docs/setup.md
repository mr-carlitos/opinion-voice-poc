# Local Demo Setup

## Current checkpoint — 10 September 2026

**The approved application-identity SharePoint path now works.** Six synthetic
PDFs were uploaded and read back (12 pages), the `30 Fahrzeuge` fact was verified,
and a synthetic Word upload/download plus duplicate-free retry succeeded.
The complete voice/text/review journey subsequently passed with synthetic
microphone input in full Chromium and actual cloud services. A human microphone
and speaker rehearsal remains required; response latency is still noticeable.

**Azure provisioning succeeded; application readiness is still UNVERIFIED.**
Azure CLI login is restored. The approved Sweden Central `rg-opinion-voice-poc`
Foundry account/project now uses **GPT-5.1 `2025-11-13`, Standard, capacity 100**.
The former GPT-4.1-mini GlobalStandard deployment was retired after the replacement
passed live checks. No Azure app hosting, database or search service was provisioned.
Standard inference stays within the selected Azure geography; it is not a promise
of processing in one datacenter or a blanket assessment of all service data flows.
See [deployment types](https://learn.microsoft.com/en-us/azure/foundry/foundry-models/concepts/deployment-types).

The approved Azure context remains:

- Tenant: `b6e35ef2-f3c9-41fb-a100-25270326ea5b`
- Subscription: `87d501de-bf17-4c3e-b4d8-42a5607d7b7c`

The previous `AADSTS50173` blocker is historical. Do not repeat `az login` as the
default next step. Preserve actual deployment outputs in ignored `.env`; do not
invent or publish real endpoints. If provisioning needs to be inspected or
reproduced, `bash scripts/provision.sh` is the read-only quota check and
`bash scripts/provision.sh --apply` is the explicit resource-creation path, not
a prerequisite to repeat for this already-provisioned environment. The quota
check now reads the model SKU's actual `usageName` (`gpt4.1-mini`, not the model
name `gpt-4.1-mini`), and Bicep serializes project/model children after the
observed concurrent `RequestConflict`.

The Microsoft 365 registration now requests only `User.Read` + `Files.ReadWrite`.
**Per-user consent and Graph profile lookup succeeded**, but input-folder
sharing-link resolution returned HTTP 403. The first diagnostic discarded the
provider error code; the exact access-denial cause is not yet established.
No document contents were read or uploaded. Do not repeat tenant-wide admin
consent, broaden scopes, or claim the SharePoint integration is working.

Subsequent comparison: an authorized operator-only metadata lookup obtained
verified canonical URLs/library/folder IDs. The runtime app still received HTTP
403 for both direct-ID folder requests with `User.Read` + `Files.ReadWrite`.
This was not merely a sharing-link problem. Subsequently, an isolated comparison
with an existing application `Sites.Selected` identity succeeded. The operator
then explicitly approved using it for this synthetic demo and the file checks.
No permissions or site grants were changed.

Prompt agent version 2 uses the new regional model. The live model probe returned
German Voice Live audio with the correct SharePoint fact, validated its evidence,
and generated a structured summary in the same conversation. It used typed input,
not a microphone, and did not exercise browser playback.

```bash
# Explicitly billable: reads the real corpus, invokes Voice Live and model calls.
uv run --frozen --no-sync python scripts/check_model.py
```

The probe deletes its conversation and records metrics (no audio) in ignored
`.local/model-check.json`. One measured response produced first upstream audio in
1.29 seconds, completed in 2.42 seconds, then required 16.4 seconds for evidence
validation. The app buffers audio until validation, so this is not a 1.29-second
audible-response claim. Summary generation took 11.27 seconds.

Provisioning defaults now use the selected regional model. Overrides are
`FOUNDRY_MODEL_NAME`, `FOUNDRY_MODEL_VERSION`, `FOUNDRY_MODEL_DEPLOYMENT_NAME`,
`FOUNDRY_DEPLOYMENT_SKU`, and `FOUNDRY_DEPLOYMENT_CAPACITY`. Only Standard and
DataZoneStandard are allowed; selecting a different geography/SKU/model requires
operator approval and fresh capability checks. Global fallback is disabled.

## Local dependencies and private configuration

```bash
uv sync --locked --no-dev
uv run --frozen --no-dev python scripts/generate_sample_pdfs.py
```

Use [.env.example](../.env.example) for setting names and preserve existing values
when preparing ignored `.env`. Keep real client IDs, deployment endpoints and
SharePoint sharing-link URLs there, not in generic documentation or screenshots.
Never put access tokens in `.env` or commit credentials. Application mode reads
an existing client secret from a separate ignored credential file, not browser
code or a committed template.

## Approved application-identity demo mode

In the ignored app `.env`, set:

```dotenv
GRAPH_AUTH_MODE=application
GRAPH_APPLICATION_CREDENTIALS_FILE=.env.graph-application
```

The referenced ignored file must be within this project and contain:

```dotenv
GRAPH_TENANT_ID=<approved-tenant-id>
GRAPH_APP_CLIENT_ID=<approved-application-id>
GRAPH_APP_CLIENT_SECRET=<existing-client-secret>
```

Keep that file private (`chmod 600` on Linux). Only those three settings are
used; other settings in an existing credential file do not override the app.
The tenant must match `AZURE_TENANT_ID`. A missing/invalid credential fails
explicitly, never by falling back to the CLI or another identity. A malformed
header can produce a dotenv warning; use comments (`#`) for descriptive lines.

The browser displays **App-Zugriff verbinden** and an explicit application-mode
warning. Connecting obtains an application token; it does not invoke `/me` or
open a device-code sign-in. The local session/Word attribution reads
`Lokale Demo (Anwendungsidentitaet)`, not a claim of an authenticated participant.
CLI diagnostics select the same configured mode.

The existing application's `Sites.Selected` role and resource access must already
be approved. This switch does not grant consent, add site permissions, expose
secrets, or change folder ACLs. It uses the app's approved site access rather than
each participant's access. Keep the two-folder/manifest checks and synthetic-only
localhost limits. A new application would need its own approved grants.

`scripts/setup_m365.py` manages the separate delegated public-client registration;
do not use it to modify the reused application identity.

## Alternative delegated identity (failed folder access in this tenant)

With `GRAPH_AUTH_MODE=delegated`, use a single-tenant **public client** with device-code sign-in
and only delegated Microsoft Graph **`User.Read` + `Files.ReadWrite`**. No client
secret or app-only/application permissions are used. Ordinary per-user consent
is not intrinsically admin-only; the tenant's configured policy determines
whether a user can consent.

The existing `opinion-voice-local-demo` registration originally declared
`User.Read`, `Sites.Read.All` and `Files.ReadWrite.All`, but these were **never
consented**. A tenant-wide admin-consent attempt returned 403. A read-only tenant
policy check found the broad pair excluded from generic self-consent except for
approved application IDs; this app is not allowlisted. The narrower pair appears
permitted by the configured policy; actual per-user consent was subsequently
confirmed. This is not proof of API access to the selected SharePoint libraries.

### Inspect, explicitly configure, then review consent

Replace `"<tenant>"` with the approved tenant ID. First run the **read-only**
plan/check; this does not create an app or change permissions:

```bash
uv run --frozen --no-dev python scripts/setup_m365.py --tenant-id "<tenant>"
```

For a new environment without the expected registration, explicit creation uses:

```bash
uv run --frozen --no-dev python scripts/setup_m365.py --tenant-id "<tenant>" --apply
```

For the **expected owned legacy registration only**, the approved migration
replaces the broad declared request with the narrow pair. Inspect the plan and
expected application identity first; do not create duplicates or modify an
unrelated app:

```bash
uv run --frozen --no-dev python scripts/setup_m365.py --tenant-id "<tenant>" --apply --narrow-permissions
```

These are different setup cases, not a command sequence to run blindly.
The setup script **never grants consent or directory roles**. This migration
does not authorize tenant-policy, conditional-access or SharePoint ACL changes.
It is not an admin-consent operation. Review the resulting application, tenant
and requested scopes before approving the ordinary device sign-in. If the
request is denied, record the exact failure and stop that live step; do not
silently broaden scopes, redeem a link, grant access or default to admin consent.

Set `AZURE_TENANT_ID` and `GRAPH_CLIENT_ID` privately in `.env`. Authentication
tokens remain in process memory. Azure CLI login supplies the Azure/Foundry
identity; the application's explicit Microsoft 365 device sign-in supplies
delegated Graph identity. CLI diagnostics and the browser app also have separate
in-memory authentication sessions. This is localhost single-user authentication,
not a production OBO implementation.

`Files.ReadWrite` is **not a two-folder token security boundary**: application
folder/manifest checks do not reduce the token to those folders or change
inherited SharePoint access. Prefer a dedicated non-admin synthetic test identity
with only the access needed for the demonstration. Verify the exact libraries and
API operations; a scope accepted at consent can still be rejected by an API.
Application `Sites.Selected` mode is now explicitly approved as described above.
Folder-selected grants remain a separate alternative requiring review, not an
automatic fallback.

## SharePoint folders

Keep both folder URL settings and choose a supported resolution path for each:

| Setting | Approved sharing-link path | Canonical URL with pinned IDs |
| --- | --- | --- |
| `SHAREPOINT_INPUT_FOLDER_URL` | Approved HTTPS commercial SharePoint folder sharing link | Canonical input folder URL |
| `SHAREPOINT_INPUT_DRIVE_ID` + `SHAREPOINT_INPUT_FOLDER_ID` | Not guessed from the link; use only IDs validated through Graph | Both required and validated through Graph |
| `SHAREPOINT_OUTPUT_FOLDER_URL` | Approved HTTPS commercial SharePoint folder sharing link | Canonical output folder URL |
| `SHAREPOINT_OUTPUT_DRIVE_ID` + `SHAREPOINT_OUTPUT_FOLDER_ID` | Not guessed from the link; use only IDs validated through Graph | Both required and validated through Graph |

The sharing-link path uses Graph `/shares` for initial resolution. It does **not**
automatically redeem links, create links or grant new access. If the signed-in
identity cannot already resolve/access the approved resource, surface the failure
for review. Pinned IDs become authoritative only after Graph resolution validates
the actual folder; never derive or guess them from a sharing-link token.

**A direct canonical URL without its paired drive/folder IDs is unsupported**:
the narrow route performs no site discovery. A library view URL containing
`Forms/AllItems.aspx?id=...` is not a canonical folder URL. The target is commercial
SharePoint, not personal OneDrive or sovereign endpoints.

Use separate, non-overlapping folders, never the same folder or a parent/child
pair. Separation is checked using the Graph-resolved canonical URLs and IDs,
not just the supplied link strings. Their ACLs remain unchanged. Missing
configuration, invalid resolution or denied access fails explicitly; repository
PDFs and alternative storage are not runtime fallbacks.

Real sharing-link URLs are sensitive and belong only in ignored `.env`, never
deployment-state records, logs or screenshots. Record only the required owned
artifact/resolved IDs in ignored local state. Folder separation does not prove
cross-user privacy; use only approved synthetic documents.

## Diagnosing delegated folder HTTP 403 (historical failure path)

Run in a separate Linux terminal as the same local user:

```bash
uv run --frozen --no-sync python scripts/live_check.py --resolve-folders
```

The command displays its own device code. After sign-in, it reports input and
output metadata access separately without reading documents or uploading files.
For expected service failures it prints safe Graph error codes and request IDs,
not a traceback, raw response message or sharing-link URL. It still exits
nonzero on failure and does not save a partially successful folder configuration.
Delegated invocations require sign-in because tokens remain in process memory.
Application-mode invocations use the configured private credential instead.

A 403 alone does not distinguish a user access problem, a link-resolution
restriction, a scope limitation, or Conditional Access. If `insufficient_claims`
is reported, review the required authentication challenge rather than weakening
policy. Check the same account's existing access by navigating directly within
the SharePoint site; do not create new links or request additional access as a
silent fix. Opening a sharing link can itself redeem access, so it is not a
neutral permissions check. The application does not automatically redeem links.

See Microsoft's [sharing API](https://learn.microsoft.com/en-us/graph/api/shares-get)
and [authorization error guidance](https://learn.microsoft.com/en-us/graph/resolve-auth-errors).

## Remaining live checks

Session startup now reuses HTTP connections only within the current Graph load.
It consumes each freshly returned file-download URL immediately rather than
requesting that metadata again. URLs and corpus snapshots are not cached between
identities/sessions, and source IDs/versions are rechecked after downloading each
PDF. In one same-corpus comparison the six-PDF load fell from 16.27s to 4.84s;
Graph metadata requests fell from 19 to 13 including input-folder resolution.
These are observed samples, not latency guarantees. The session-creation response
includes `startup_seconds` for folder, corpus, agent and conversation stages.

1. Run the read-only registration plan, perform the explicitly approved narrow
   migration if still required, and review the resulting app/scopes.
2. Review the dedicated test identity, both folder destinations and intended
   operations before ordinary device sign-in. A successful login is not yet
   evidence of SharePoint access.
3. Resolve both folders under that identity and read **one approved PDF** through
   Graph. Confirm its real item/source metadata and distinctive fact. Record
   permission/scope/API failures honestly; no local-file fallback.
4. After explicit write approval, upload and download a **synthetic DOCX** in the
   separate output folder and verify bytes plus access to the returned item.
5. Only then combine the approved corpus, prompt agent and voice/text journey.
   Keep C2's approved reduced-scope incompleteness label and do not mark multi-user
   privacy requirements as passed.

The existing diagnostics have distinct effects:

| Command flag on `scripts/live_check.py` | Purpose and effects |
| --- | --- |
| `--foundry-only` | Isolates Foundry/agent/model checks from Microsoft 365; creates/reuses an agent version and incurs model usage, not merely a read-only health probe. |
| `--resolve-folders` | Checks both configured folders' metadata with one sign-in. No document reads/uploads or permission changes; saves canonical folder IDs only if both resolve and are separate. |
| `--upload-corpus` | **Writes approved synthetic manifest PDFs** to the configured input folder; never an implicit read-only access check. |
| `--save-example` | **Writes a synthetic DOCX** to the output folder and verifies authored package content and all three headings on download. Records whether bytes changed through recognized SharePoint metadata processing. |

Run only the approved checks. If the input PDF is not already present, explicitly
approve the synthetic corpus upload rather than treating sign-in as write consent.

```bash
uv run --frozen --no-dev python scripts/live_check.py --foundry-only
# Explicit synthetic input-folder writes, only after operator review:
uv run --frozen --no-dev python scripts/live_check.py --upload-corpus
# Explicit synthetic output-folder write and download:
uv run --frozen --no-dev python scripts/live_check.py --save-example
npm start
```

In delegated mode the Graph commands prompt for browser device sign-in; application
mode requires no interactive Graph sign-in. `--upload-corpus` writes
only manifest-listed PDFs. Identical reruns are safe; changed existing files
cause an explicit conflict instead of overwriting them. Updating source versions
is currently an operator action in SharePoint, followed by a new app session.
`--save-example` writes a synthetic DOCX and verifies its authored package content.
SharePoint may add custom property/XML metadata and reserialize the ZIP package.
The comparator preserves all original Word payload parts, existing relationships
and metadata values; only recognized storage metadata additions and XML
reserialization are allowed. Bound fields/controls do not qualify for this
normalization. Changed content or unexpected parts fail explicitly. PDFs still
require exact byte equality. Source/stored SHA256 values are recorded separately
under `.local/smoke-item.json`; no raw DOCX byte-equality claim is made.
Owned item IDs are recorded under ignored `.local/`; no script deletes the site.

## Browser journey

Summary commands also accept polite requests and conversational lead-ins, for
example "Fasse unser Gespraech bitte zusammen", "Ich moechte jetzt eine
Zusammenfassung", and "Ja, ist gut. Also eben OK. Jetzt Zusammenfassung erstellen
und fuer diesen Entwurf so freigeben." These enter the same validated draft/review
flow as the button; they do not authorize saving an unseen draft. Recognition is
bounded and deterministic, not universal language understanding. Negated,
reported/quoted, conditional or metalinguistic statements remain conversation.

Open the localhost URL, select **App-Zugriff verbinden** (or sign in to Microsoft
365 in delegated mode), and start a session. Select **Mikrofon einschalten**
for spoken input; select **Mikrofon stummschalten** to stop capture.
**Ton ausschalten/einschalten** separately controls playback. You can also type.
Finish with the button or say "OK, jetzt Zusammenfassung erstellen",
"Bitte meine Meinungsbildung zusammenfassen". Review and optionally edit the
three sections, apply edits, then click save or say "Ja, bitte speichern".
An unqualified "yes" does not authorize a save. A confirmed Graph result is
required before showing a saved file link. Verify final access in SharePoint.

Review edits carry their draft version. While an edit is being acknowledged or
applied, save remains disabled. Once a save freezes a draft, even a failed upload
does not allow silent modification of that version; retry sends the same bytes.
After connection/request failure, the browser fetches the authoritative draft
snapshot. An old spoken approval cannot authorize a newer edited draft.

Use Stop to release the microphone and voice connection. Delete the session to
delete the Foundry conversation and local state; this does not delete saved
SharePoint files. A process restart loses the in-memory session inventory.
Service-side conversations may remain after a crash: remove them in Foundry
and delete only the PoC's explicitly recorded files after the demo.
The same voice session cannot reconnect: this prevents duplicate greetings and
ambiguous response history. HTTP review/save recovery is still available after
voice disconnect; delete and start a new session to resume conversation.

## Limits and verification

- At most six manifest PDFs, eight pages each, 2 MB per file and 100000 extracted
  characters total. No silent trimming and no local PDF runtime fallback.
- A session preloads a Graph-fetched full-text snapshot, not a query-time
  semantic index. Source changes appear in a new session. Permission revocation
  is not rechecked mid-session. Do not claim live permission trimming.
- Up to 30 user turns, 30000 user-text characters, and 30 minutes per session.
- In default `strict` mode assistant audio is buffered until an additional model evidence check passes.
  This increases latency; that check reduces but cannot eliminate unsupported
  claims. It is not proof that all factual statements are correct.
- Voice SDK, conversation continuity, microphone, spoken confirmation and real
  Graph operations are implemented but require live validation in the tenant.
- Agent behavior remains prompt-based in [agent/instructions.md](../agent/instructions.md).
  Consent narrowing does not change the agent instructions or establish guaranteed
  grounding. C2 remains reduced-scope/incomplete; reviewer management and
  multi-user privacy (including A15/A17) are deferred and unverified.
- Native stock-avatar transport is implemented, opt-in and disabled by default;
  real media acceptance is still blocked (see the dated note below).
  This is a prompt agent, not a hosted agent.
- GitHub Actions is disabled. Use server output and local browser diagnostics;
  no CI wait, test-first requirement, or automatic cloud tests are involved.

## Native avatar / streaming v2 (11 September 2026)

### Avatar diagnostics

Restart the server and hard-refresh the browser after changing diagnostic code.
Reproduce the connection failure once. The UI shows a **Diagnose-ID**, shared by
the terminal message and the record in ignored `.local/diagnostics.jsonl`.
Read the last records from the repository root:

```bash
tail -n 5 .local/diagnostics.jsonl
```

Records contain the failure stage/reason, browser connection/ICE/gathering/
signaling states, elapsed time, whether offer/answer were exchanged, codec
support, track counts and up to eight ICE error codes/messages. Browser API
exceptions retain their name and redacted message. When Azure supplies an error,
its code, redacted message, parameter, nested error details and available
session/event/request identifiers are retained. Unexpected bridge exceptions
include redacted messages and file/function/line frames, never local variables.

Browser DevTools Console also shows `[Avatar diagnostic]` before the peer is
closed. This is useful if the WebSocket cannot deliver its report to the backend.
Do not confuse a browser-reported failure with an Azure service error:
`peer_failed`, `remote_description_failed`, `playback_failed`,
`browser_handshake_timeout`, and `h264_unsupported` identify different stages.
An ICE error on one endpoint alone does not terminate negotiation; it is retained
as evidence if the connection ultimately fails.

Raw SDP, ICE credentials, service tokens, URLs/IPs and arbitrary raw event fields
are not recorded. The file is written with private permissions, rotates at about
2 MB into `.local/diagnostics.previous.jsonl`, and is not a cloud telemetry service.
Treat even redacted diagnostic files as local operational information; review
before sharing. File-write failures are explicitly reported in the terminal.
Do not turn on blanket WebSocket/HTTP debug logging to diagnose this problem.

The safe defaults remain `VOICE_DELIVERY_MODE=strict` and
`VOICE_AVATAR_ENABLED=false`. For the approved synthetic streaming demo, explicitly
set `VOICE_DELIVERY_MODE=streaming` and `VOICE_AVATAR_ENABLED=true` before starting
the local server. The user must also select **Avatar verwenden** before creating
each session. Strict mode never accepts an avatar session. An unchecked selection
uses ordinary PCM audio even when the server capability is enabled.

The current demo selects stock character `harry`, style `casual`, with German
male voice `de-DE-ConradNeural`. Set `VOICE_AVATAR_CHARACTER`,
`VOICE_AVATAR_STYLE` and `VOICE_NAME` in ignored `.env` before restarting.
The former `lisa` / `casual-sitting` / `de-DE-KatjaNeural` combination remains
available. The new configuration was accepted by Voice Live on 14 September;
its rendered appearance and voice preference still require operator review.
These are stock avatars, not custom likenesses.

Speech follow-up (14 September): current `.env` now selects the male HD voice
`de-DE-Florian:DragonHDLatestNeural`; Conrad remains an explicit alternative.
Voice Live accepted Florian HD with Harry/casual, and an audio-only live probe
returned the correct30-vehicle fact without inline source markers. Naturalness
and actual avatar playback still require listening in the operator browser.

Conversational instructions no longer request document/page markers inside the
spoken text. Streaming answers receive a separate, nonblocking source-attribution
check after completion; references appear on their original transcript item.
Pending/unsupported/failed attribution is visibly labelled. At most two source
checks run concurrently; excess checks are marked incomplete, not invented.
This adds model usage but does not hold up audio playback. It cannot retract a
spoken unsupported statement, and prompt adherence is not a deterministic audio
filter. Strict mode still checks before playback. Structured summary source
appendices, validation and approval remain unchanged.
Native media uses the same Voice Live prompt-agent conversation, not a separate
synthesizer or model. No deployment, region, grants or service identity change is
needed by the local code. Existing GPT-5.1 Standard in Sweden Central is unchanged.

`GET /api/readiness` exposes `avatar_available`; `POST /api/sessions` accepts
`{"avatar_enabled": true}` (omitting it means audio-only). The server sends only
bounded `avatar_start` ICE configuration and `avatar_answer` SDP. The browser sends
`avatar_offer`, then `avatar_ready` after connected audio/video tracks. SDP is
base64 JSON `{type,sdp}`, at most 131072 encoded characters. Credentials stay
server-side except required transient ICE credentials; no ICE/SDP is logged.
Unknown browser events cannot be forwarded to Voice Live.

The greeting is withheld until media readiness. No PCM is forwarded in avatar
sessions. Browser negotiation expires after 30 seconds; the backend watchdog
expires after 35 seconds. Interrupt silences local media and clears the native
output buffer. Stop/disconnect closes the peer and upstream connection. Failure
offers **Neue Sitzung ohne Avatar vorbereiten**, deleting only the failed local
conversation before returning to an unchecked audio-only startup choice. It never
silently replays partial speech or changes assurance mode.

**Live blocker:** the existing resource supplied ICE configuration but returned
`avatar_service_internal_error` during native negotiation, before an SDP answer
or any video frames. The error alone does not establish a regional, quota or
network root cause. Do not claim avatar support verified on this resource.
An explicitly unchecked audio-only session on the same resource did complete a
streamed greeting. Physical microphone/speaker and avatar acceptance remain open.

Streaming conversational output has **no independent pre-speech evidence check**;
the UI labels that limitation. Both modes semantically validate generated and
edited final summaries and retain version-bound human save approval.