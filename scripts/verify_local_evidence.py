"""Check the running synthetic stack's evidence and unconfigured-provider boundaries."""

import base64
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1]
API = "http://127.0.0.1:8000"
IDENTITY = "http://127.0.0.1:54330"


def verify(checks):
    def check(name, condition):
        checks.append({"name": name, "passed": bool(condition)})
        print(f"{'PASS' if condition else 'FAIL'} {name}", flush=True)
        if not condition:
            raise AssertionError(name)

    with httpx.Client(timeout=20, trust_env=False) as client:
        check(
            "Synthetic identity fixture is explicit",
            client.get(IDENTITY + "/auth/v1/health").json().get("simulated") is True,
        )
        tokens = {
            role: client.get(IDENTITY + "/local-demo/session", params={"actor": role}).json()[
                "access_token"
            ]
            for role in ("finance", "supplier", "outsider")
        }

        def call(path, *, role="finance", method="GET", body=None):
            return client.request(
                method, API + path, headers={"Authorization": "Bearer " + tokens[role]}, json=body
            )

        check(
            "Phase 9 API and latest schema ready",
            call("/api/health").json().get("phase") == 9 and call("/api/ready").status_code == 200,
        )
        rows = call("/api/integrations").json()["integrations"]
        check(
            "No real provider is configured or claimed verified",
            len(rows) == 5 and all(not r["configured"] and not r["live_verified"] for r in rows),
        )
        supplier = call("/api/suppliers").json()["suppliers"][0]
        payment = call(
            "/api/payments",
            method="POST",
            body={
                "supplier_id": supplier["id"],
                "invoice_reference": "SYN-EVIDENCE-" + uuid4().hex[:10],
                "amount_minor": 12500000,
                "currency": "INR",
                "simulation": "success",
            },
        ).json()
        pid, revision = payment["id"], payment["current_revision"]
        raw = (ROOT / "fixtures/evidence/04-injected-instructions.txt").read_bytes()
        body = {
            "revision_id": revision["id"],
            "filename": "synthetic-injection.txt",
            "media_type": "text/plain",
            "content_base64": base64.b64encode(raw).decode(),
        }
        response = call(f"/api/payments/{pid}/evidence", method="POST", body=body)
        check("Private synthetic evidence uploaded and read back", response.status_code == 200)
        doc = response.json()
        check(
            "Document preserves hash and source text",
            doc["sha256"] == hashlib.sha256(raw).hexdigest()
            and doc["extracted_text"].strip() == raw.decode().strip(),
        )
        check(
            "Untrusted document does not change financial fields",
            call(f"/api/payments/{pid}").json()["current_revision"] == revision,
        )
        check(
            "Repeated upload returns one durable document",
            call(f"/api/payments/{pid}/evidence", method="POST", body=body).json()["id"]
            == doc["id"],
        )
        check(
            "Original download matches exact bytes",
            call(f"/api/evidence/{doc['id']}/content").content == raw,
        )
        check(
            "Other tenant cannot list evidence",
            call(f"/api/payments/{pid}/evidence", role="outsider").status_code == 404,
        )
        check(
            "Other tenant cannot download original",
            call(f"/api/evidence/{doc['id']}/content", role="outsider").status_code == 404,
        )
        check(
            "Supplier cannot read finance evidence",
            call(f"/api/payments/{pid}/evidence", role="supplier").status_code == 403,
        )
        check(
            "Current evidence blocks approval without reviewed investigation",
            call(
                f"/api/payments/{pid}/approvals",
                method="POST",
                body={"revision_id": revision["id"], "digest": revision["digest"]},
            ).status_code
            == 409,
        )
        response = call(
            f"/api/payments/{pid}/investigations",
            method="POST",
            body={"revision_id": revision["id"]},
        )
        check(
            "Missing OpenAI credentials fail clearly",
            response.status_code == 503
            and response.json()["error"]["code"] == "openai_not_configured",
        )
        check(
            "No fabricated investigation appears",
            call(f"/api/payments/{pid}/investigations").json()["investigations"] == [],
        )
        check(
            "Missing Breeth configuration fails clearly",
            call(f"/api/payments/{pid}/memory").status_code == 503,
        )
        changed = call(
            f"/api/payments/{pid}/revisions",
            method="POST",
            body={
                "expected_revision_id": revision["id"],
                "amount_minor": 12500001,
                "simulation": "success",
            },
        ).json()
        fresh = changed["current_revision"]
        check(
            "Revision change cannot bypass earlier evidence",
            call(
                f"/api/payments/{pid}/approvals",
                method="POST",
                body={"revision_id": fresh["id"], "digest": fresh["digest"]},
            ).status_code
            == 409,
        )
        check(
            "Upload against stale revision rejected",
            call(f"/api/payments/{pid}/evidence", method="POST", body=body).status_code == 409,
        )
        check(
            "Unsupported image format rejected",
            call(
                f"/api/payments/{pid}/evidence",
                method="POST",
                body={**body, "revision_id": fresh["id"], "media_type": "image/png"},
            ).status_code
            == 422,
        )
        check(
            "Path-like filename rejected",
            call(
                f"/api/payments/{pid}/evidence",
                method="POST",
                body={**body, "revision_id": fresh["id"], "filename": "../outside.txt"},
            ).status_code
            == 422,
        )
        billing = call("/api/billing").json()
        check(
            "Unconfigured billing has no entitlement and stays test mode",
            billing["mode"] == "test" and not billing["configured"] and not billing["entitled"],
        )
        check(
            "Unconfigured checkout cannot create a fake success",
            call("/api/billing/checkout", method="POST", body={}).status_code == 503,
        )
        check(
            "Premium report is denied without verified entitlement",
            call(f"/api/payments/{pid}/report").status_code in {402, 403},
        )
        check(
            "Other tenant cannot read premium report",
            call(f"/api/payments/{pid}/report", role="outsider").status_code in {402, 403, 404},
        )
        check(
            "Supplier cannot access billing",
            call("/api/billing", role="supplier").status_code == 403,
        )
        check(
            "Supplier cannot inspect integrations",
            call("/api/integrations", role="supplier").status_code == 403,
        )
        check(
            "Assigned supplier inbox responds",
            call("/api/supplier/inbox", role="supplier").status_code == 200,
        )
        check(
            "Unconfigured n8n cannot fabricate delivery",
            call(
                f"/api/suppliers/{supplier['id']}/deliveries",
                method="POST",
                body={"beneficiary_version_id": supplier["current_beneficiary"]["id"]},
            ).status_code
            == 503,
        )
        for path in ("/api/integrations/n8n/callback", "/api/integrations/dodo/webhook"):
            check(
                path + " rejects unauthenticated callback",
                client.post(API + path, json={}).status_code in {401, 403, 503},
            )
        return pid


if __name__ == "__main__":
    checks = []
    report = {"environment": "local synthetic stack; no external provider calls", "passed": False}
    try:
        report["payment_id"] = verify(checks)
        report["passed"] = True
    finally:
        report.update(checked_at=datetime.now(timezone.utc).isoformat(), checks=checks)
        path = ROOT / "artifacts/local-evidence.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(report, indent=2) + "\n")
