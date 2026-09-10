"""Create only the demo's public-client registration; never grant consent."""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlencode, urlsplit

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.graph_permissions import GRAPH_SCOPES  # noqa: E402

GRAPH_APP_ID = "00000003-0000-0000-c000-000000000000"
APP_NAME = "opinion-voice-local-demo"
OWNER_MARKER = "opinion-voice-poc-public-client-v1"
LEGACY_SCOPES = ("User.Read", "Sites.Read.All", "Files.ReadWrite.All")
SCOPES = GRAPH_SCOPES


class SetupError(RuntimeError):
    pass


def azure(*args: str):
    result = subprocess.run(
        ["az", *args, "--output", "json", "--only-show-errors"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise SetupError(f"Azure CLI failed ({' '.join(args[:3])}): {result.stderr.strip()}")
    return json.loads(result.stdout) if result.stdout.strip() else None


def permission_request(scopes: list[dict], names: tuple[str, ...] = SCOPES) -> list[dict]:
    permissions = []
    for name in names:
        matches = [scope for scope in scopes if scope["value"] == name and scope["isEnabled"]]
        if len(matches) != 1:
            raise SetupError(f"Expected one enabled delegated Microsoft Graph scope: {name}")
        permissions.append({"id": matches[0]["id"], "type": "Scope"})
    return [{"resourceAppId": GRAPH_APP_ID, "resourceAccess": permissions}]


def validate_identity(app: dict) -> None:
    if (
        app.get("displayName") != APP_NAME
        or app.get("serviceManagementReference") != OWNER_MARKER
        or app.get("signInAudience") != "AzureADMyOrg"
        or app.get("isFallbackPublicClient") is not True
        or app.get("passwordCredentials")
        or app.get("keyCredentials")
    ):
        raise SetupError(
            "Existing registration is not the expected secret-free demo public client."
        )


def permission_set(resources: list[dict]) -> set[tuple[str, str, str]]:
    return {
        (resource["resourceAppId"], permission["id"], permission["type"])
        for resource in resources
        for permission in resource["resourceAccess"]
    }


def validate_app(app: dict, required: list[dict]) -> None:
    validate_identity(app)
    if permission_set(app.get("requiredResourceAccess", [])) != permission_set(required):
        raise SetupError("Registration permissions differ; review them manually, not by overwrite.")


def graph_collection(url: str) -> list[dict]:
    records = []
    visited = set()
    while url:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.netloc != "graph.microsoft.com"
            or not parsed.path.startswith("/v1.0/")
            or parsed.fragment
            or url in visited
            or len(visited) >= 100
        ):
            raise SetupError("Invalid or excessive Graph pagination during permission review.")
        visited.add(url)
        response = azure("rest", "--method", "get", "--url", url)
        if not isinstance(response, dict) or not isinstance(response.get("value"), list):
            raise SetupError("Graph permission review returned an unexpected response.")
        records.extend(response["value"])
        url = response.get("@odata.nextLink", "")
    return records


def review_grants(principal_id: str, graph_id: str) -> list[dict]:
    query = urlencode(
        {
            "$filter": f"clientId eq '{principal_id}'",
            "$select": "scope,consentType,resourceId",
        }
    )
    grants = graph_collection(f"https://graph.microsoft.com/v1.0/oauth2PermissionGrants?{query}")
    roles = graph_collection(
        f"https://graph.microsoft.com/v1.0/servicePrincipals/{principal_id}"
        "/appRoleAssignments?$select=appRoleId"
    )
    if roles:
        raise SetupError("Existing app-only permissions require manual review; no grants changed.")
    allowed = set(SCOPES) | {"openid", "profile", "email", "offline_access"}
    for grant in grants:
        if grant.get("resourceId") != graph_id or set(grant.get("scope", "").split()) - allowed:
            raise SetupError(
                "Broader consent grants still exist. Changing requested permissions will not "
                "revoke them; have their owner/administrator review them first. No grants changed."
            )
    return grants


def setup(tenant_id: str, apply: bool, narrow_permissions: bool = False) -> None:
    account = azure("account", "show")
    if account["tenantId"].lower() != tenant_id.lower():
        raise SetupError("Azure CLI is signed into a different tenant; no changes made.")
    graph = azure("ad", "sp", "show", "--id", GRAPH_APP_ID)
    required = permission_request(graph["oauth2PermissionScopes"])
    apps = [
        app
        for app in azure("ad", "app", "list", "--display-name", APP_NAME)
        if app["displayName"] == APP_NAME
    ]
    if len(apps) > 1:
        raise SetupError(
            "Multiple matching registrations found; resolve ambiguity before proceeding."
        )
    if not apps and not apply:
        print(f"Would create {APP_NAME} in tenant {tenant_id}.")
        print(f"Delegated permissions: {', '.join(SCOPES)}. No secret or consent grant.")
        print("Run again with --apply after approving the registration.")
        return
    migrating = False
    if apps:
        app = apps[0]
        validate_identity(app)
        if permission_set(app.get("requiredResourceAccess", [])) != permission_set(required):
            legacy = permission_request(graph["oauth2PermissionScopes"], LEGACY_SCOPES)
            if permission_set(app.get("requiredResourceAccess", [])) != permission_set(legacy):
                raise SetupError(
                    "Unexpected registration permissions; refusing automatic migration."
                )
            migrating = True
            if apply and not narrow_permissions:
                raise SetupError(
                    "Owned legacy registration found. Review and use --apply --narrow-permissions "
                    "to replace its requests with User.Read + Files.ReadWrite."
                )
    else:
        app = azure(
            "ad",
            "app",
            "create",
            "--display-name",
            APP_NAME,
            "--sign-in-audience",
            "AzureADMyOrg",
            "--is-fallback-public-client",
            "true",
            "--service-management-reference",
            OWNER_MARKER,
            "--required-resource-accesses",
            json.dumps(required),
        )
    principals = azure("ad", "sp", "list", "--filter", f"appId eq '{app['appId']}'")
    if len(principals) > 1:
        raise SetupError("Multiple service principals found for the demo application.")
    grants = review_grants(principals[0]["id"], graph["id"]) if principals else []
    if migrating:
        if not apply:
            print(f"Owned legacy registration found: {APP_NAME}.")
            print("Would replace Sites.Read.All + Files.ReadWrite.All with Files.ReadWrite.")
            print("Run with --apply --narrow-permissions after approving this change.")
            print("No permissions, consent grants, or tenant policies changed.")
            return
        azure(
            "ad",
            "app",
            "update",
            "--id",
            app["id"],
            "--required-resource-accesses",
            json.dumps(required),
        )
        app = azure("ad", "app", "show", "--id", app["id"])
    validate_app(app, required)
    state = {
        "tenant_id": tenant_id,
        "client_id": app["appId"],
        "application_object_id": app["id"],
        "display_name": APP_NAME,
        "ownership_marker": OWNER_MARKER,
        "requested_delegated_scopes": list(SCOPES),
        "admin_consent_granted_by_script": False,
        "existing_delegated_grants": grants,
    }
    if apply:
        state_dir = ROOT / ".local"
        state_dir.mkdir(mode=0o700, exist_ok=True)
        state_path = state_dir / "m365-app.json"
        state_path.write_text(json.dumps(state, indent=2) + "\n")
        state_path.chmod(0o600)
    if not principals and apply:
        principals = [azure("ad", "sp", "create", "--id", app["appId"])]
    if principals:
        state["service_principal_id"] = principals[0]["id"]
        if apply:
            state_path.write_text(json.dumps(state, indent=2) + "\n")
    print(json.dumps(state, indent=2))
    print("Requested permissions configured; this script has NOT granted consent.")
    print("Sign into the app and review ordinary user consent, subject to tenant policy.")
    print(
        "If approval is blocked, stop and contact the administrator; do not weaken tenant policy."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument(
        "--apply", action="store_true", help="Create the registration, but not consent."
    )
    parser.add_argument(
        "--narrow-permissions",
        action="store_true",
        help="With --apply, migrate only the owned legacy registration to narrow file scopes.",
    )
    args = parser.parse_args()
    try:
        setup(args.tenant_id, args.apply, args.narrow_permissions)
    except (SetupError, OSError, ValueError) as error:
        print(f"M365 setup failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
