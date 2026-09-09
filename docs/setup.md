# Local Demo Setup

## Current blocker

On 9 September 2026 the live Azure model/quota checks returned AADSTS50173:
the cached operator grant was revoked. No new resources were created. Renew
Azure CLI sign-in before running provisioning; `az account show` alone can
read cached account metadata and is not proof of a usable access token.

```bash
az login --tenant b6e35ef2-f3c9-41fb-a100-25270326ea5b
az account set --subscription 87d501de-bf17-4c3e-b4d8-42a5607d7b7c
bash scripts/provision.sh
bash scripts/provision.sh --apply
```

The first script invocation is a read-only quota check. `--apply` provisions
the approved Sweden Central resource group, Foundry S0 account, project,
GPT-4.1-mini deployment, and local operator roles. Global Standard may process
inference outside Sweden. No app hosting or reserved capacity is provisioned.
The Bicep template compiles; Azure validation and provisioning remain pending.
Read actual deployment outputs for endpoints rather than inventing them.

## Microsoft 365 delegated identity

An administrator must approve a single-tenant **public client** Entra app for
this local demo and enable device-code/public-client authentication. Configure
delegated Microsoft Graph permissions `User.Read`, `Sites.Read.All` and
`Files.ReadWrite.All`. No client secret and no application permissions are used.
These scopes allow broad delegated access within the user's rights; the app
narrows file operations to the configured folders and corpus manifest. Admin
consent and tenant policy must be reviewed separately. Do not grant permissions
or weaken conditional-access policies solely to bypass an error.

Put the tenant ID and that app's client ID into the ignored `.env` file, alongside
the Foundry deployment outputs. Use `.env.example` for setting names. Do not
store passwords or access tokens. Authentication tokens live in process memory.
The Azure CLI user invokes Foundry; the explicit M365 sign-in supplies Graph
identity. This is a localhost single-user design, not a production OBO flow.

## SharePoint folders

Configure direct folder URLs, for example:

```text
https://yourtenant.sharepoint.com/sites/Demo/Shared%20Documents/Input
https://yourtenant.sharepoint.com/sites/Demo/Shared%20Documents/Output
```

Do not use sharing links or URLs containing `Forms/AllItems.aspx?id=...`.
Use separate folders, not a parent and its child. Their ACLs remain unchanged;
only use approved synthetic documents. Multi-user privacy remains unverified.
The adapter currently supports commercial SharePoint sites under `/sites/` or
`/teams/`, not personal OneDrive, sovereign endpoints, nested subsites, or OCR.

```bash
uv sync --locked --no-dev
uv run --frozen --no-dev python scripts/generate_sample_pdfs.py
uv run --frozen --no-dev python scripts/live_check.py --upload-corpus
uv run --frozen --no-dev python scripts/live_check.py --save-example
uv run --frozen --no-dev python scripts/live_check.py --foundry-only
npm start
```

The Graph commands prompt for browser device sign-in. `--upload-corpus` writes
only manifest-listed PDFs. Identical reruns are safe; changed existing files
cause an explicit conflict instead of overwriting them. Updating source versions
is currently an operator action in SharePoint, followed by a new app session.
`--save-example` writes a synthetic DOCX and downloads it to verify exact bytes.
Owned item IDs are recorded under ignored `.local/`; no script deletes the site.

## Browser journey

Open the localhost URL, sign in to Microsoft 365, and start a session. Enable
the microphone for spoken input, or type. Finish with the button or say
"Bitte meine Meinungsbildung zusammenfassen". Review and optionally edit the
three sections, apply edits, then click save or say "Ja, bitte speichern".
An unqualified "yes" does not authorize a save. A confirmed Graph result is
required before showing a saved file link. Verify final access in SharePoint.

Use Stop to release the microphone and voice connection. Delete the session to
delete the Foundry conversation and local state; this does not delete saved
SharePoint files. A process restart loses the in-memory session inventory.
Service-side conversations may remain after a crash: remove them in Foundry
and delete only the PoC's explicitly recorded files after the demo.

## Limits and verification

- At most six manifest PDFs, eight pages each, 2 MB per file and 100000 extracted
  characters total. No silent trimming and no local PDF runtime fallback.
- A session preloads a Graph-fetched full-text snapshot, not a query-time
  semantic index. Source changes appear in a new session. Permission revocation
  is not rechecked mid-session. Do not claim live permission trimming.
- Up to 30 user turns, 30000 user-text characters, and 30 minutes per session.
- Assistant audio is buffered until an additional model evidence check passes.
  This increases latency; that check reduces but cannot eliminate unsupported
  claims. It is not proof that all factual statements are correct.
- Voice SDK, conversation continuity, microphone, spoken confirmation and real
  Graph operations are implemented but require live validation in the tenant.
- Avatar remains disabled and unimplemented. Get the voice/text/save baseline
  working first. This is a prompt agent, not a hosted agent.
- GitHub Actions is disabled. Use server output and local browser diagnostics;
  no CI wait, test-first requirement, or automatic cloud tests are involved.