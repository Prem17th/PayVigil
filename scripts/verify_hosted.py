"""Verify the hosted foundation and access boundaries without logging credentials.

Supply VERIFY_API_URL, VERIFY_WEB_URL, VERIFY_FINANCE_TOKEN,
VERIFY_SUPPLIER_TOKEN, and VERIFY_UNASSIGNED_TOKEN through a secure environment.
Use separate controlled Supabase users; tokens are short-lived access tokens.
This performs one synthetic private-storage probe and deletes its probe object.
"""

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import httpx


def origin(name: str) -> str:
    value = os.environ.get(name, "").strip().rstrip("/")
    parsed = urlsplit(value)
    if not (
        parsed.scheme == "https"
        and parsed.hostname
        and not parsed.username
        and not parsed.password
        and not parsed.query
        and not parsed.fragment
        and not parsed.path
    ):
        raise ValueError(f"{name} must contain a complete HTTPS origin.")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Save a credential-free JSON report.")
    args = parser.parse_args()
    try:
        api, web = origin("VERIFY_API_URL"), origin("VERIFY_WEB_URL")
        tokens = {
            role: os.environ.get(f"VERIFY_{role.upper()}_TOKEN", "").strip()
            for role in ("finance", "supplier", "unassigned")
        }
        if not all(tokens.values()):
            raise ValueError("All three controlled-user access tokens are required.")
        if len(set(tokens.values())) != 3:
            raise ValueError("Use three distinct controlled Supabase users.")
    except ValueError as exc:
        print(str(exc))
        return 2

    checks: list[dict] = []

    def check(name: str, passed: bool) -> None:
        checks.append({"name": name, "passed": bool(passed)})
        print(f"{'PASS' if passed else 'FAIL'} {name}")

    with httpx.Client(
        timeout=httpx.Timeout(60, connect=10), follow_redirects=False, trust_env=False
    ) as client:

        def call(path: str, role: str | None = None, method: str = "GET"):
            headers = {"Accept": "application/json"}
            if role:
                headers["Authorization"] = f"Bearer {tokens[role]}"
            try:
                result = client.request(method, f"{api}{path}", headers=headers)
                body = result.json()
                return result.status_code, body if isinstance(body, dict) else {}
            except (httpx.HTTPError, ValueError):
                return 0, {}

        status, body = call("/api/health")
        check("API liveness and Phase 9 build identity", status == 200 and body.get("phase") == 9)
        status, _ = call("/api/ready")
        check("Hosted dependency readiness", status == 200)
        status, body = call("/api/setup")
        check(
            "Required service configuration",
            status == 200
            and all(
                body.get(field) is True
                for field in ("auth_configured", "database_configured", "storage_configured")
            ),
        )
        check(
            "Payment and investigation code capabilities enabled",
            body.get("capabilities")
            == {
                "payments": True,
                "investigations": True,
            },
        )
        try:
            page = client.get(web)
            check("Hosted frontend responds", page.status_code == 200 and "PayVigil" in page.text)
        except httpx.HTTPError:
            check("Hosted frontend responds", False)

        status, _ = call("/api/me")
        check("Unauthenticated access denied", status == 401)
        status, _ = call("/api/me", "unassigned")
        check("User without application membership denied", status == 403)

        status, finance = call("/api/me", "finance")
        check(
            "Finance identity and trusted role",
            status == 200
            and finance.get("role")
            in {
                "finance_admin",
                "finance_reviewer",
            },
        )
        status, supplier = call("/api/me", "supplier")
        check(
            "Supplier identity and trusted role",
            status == 200 and supplier.get("role") == "supplier",
        )
        check(
            "Distinct authenticated identities",
            bool(finance.get("user_id"))
            and bool(supplier.get("user_id"))
            and finance.get("user_id") != supplier.get("user_id"),
        )
        status, integrations = call("/api/integrations", "finance")
        rows = integrations.get("integrations", [])
        expected = {"openai", "n8n", "breeth", "elevenlabs", "dodo"}
        check(
            "Required provider configuration is present",
            status == 200
            and {row.get("id") for row in rows} == expected
            and all(row.get("configured") is True for row in rows),
        )
        status, _ = call("/api/integrations", "supplier")
        check("Supplier cannot inspect finance integrations", status == 403)
        status, billing = call("/api/billing", "finance")
        check("Billing is explicitly test mode", status == 200 and billing.get("mode") == "test")
        status, _ = call("/api/payments", "supplier")
        check("Supplier cannot list finance payments", status == 403)
        status, _ = call("/api/billing", "supplier")
        check("Supplier cannot access subscription billing", status == 403)
        status, _ = call("/api/supplier/inbox", "supplier")
        check("Assigned supplier inbox is available", status == 200)

        status, workspace = call("/api/workspace", "finance")
        check(
            "Finance workspace bound to membership",
            status == 200
            and bool(finance.get("tenant"))
            and workspace.get("tenant") == finance.get("tenant"),
        )
        status, workspace = call(f"/api/workspace?tenant_id={uuid4()}", "finance")
        check(
            "Browser cannot select another tenant",
            status == 200
            and bool(finance.get("tenant"))
            and workspace.get("tenant") == finance.get("tenant"),
        )
        status, portal = call("/api/supplier/portal", "supplier")
        check(
            "Supplier portal bound to membership",
            status == 200
            and bool(supplier.get("tenant"))
            and portal.get("tenant") == supplier.get("tenant"),
        )
        status, _ = call("/api/workspace", "supplier")
        check("Supplier cannot access finance workspace", status == 403)
        status, _ = call("/api/supplier/portal", "finance")
        check("Finance cannot impersonate supplier", status == 403)
        status, _ = call("/api/storage/check", "supplier", "POST")
        check("Supplier cannot run privileged storage checks", status == 403)
        status, storage = call("/api/storage/check", "finance", "POST")
        required = (
            "bucket_private",
            "upload",
            "authenticated_read",
            "anonymous_read_denied",
            "deleted",
        )
        check(
            "Private storage probe and cleanup",
            status == 200
            and storage.get("status") == "verified"
            and all(storage.get("checks", {}).get(field) is True for field in required),
        )

    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "phase": 9,
        "scope": "Hosted foundation and authorization only; no live sponsor call or transfer",
        "api_url": api,
        "web_url": web,
        "checks": checks,
        "passed": all(item["passed"] for item in checks),
        "remaining_manual_checks": [
            "Deployed frontend sign-in, sign-out and responsive layout",
            "Render deployed commit, environment scope and secret handling",
            "Supabase authenticated-user storage policies and backup settings",
            "OpenAI cited investigation with adversarial evidence and human review",
            "n8n controlled delivery/callback and separate supplier attestation",
            "Breeth redacted write and retrieval in the correct tenant scope",
            "ElevenLabs stock-voice audio playback",
            "Dodo test checkout, signed webhook, reconciliation and report entitlement",
            "Sandbox worker success, decline and lost-response independent readback",
            "Cross-tenant evidence and report access using separate controlled tenants",
        ],
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
