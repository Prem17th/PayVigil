"""Exercise the running, explicitly synthetic local stack. Never accepts remote URLs."""

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1]
API = "http://127.0.0.1:8000"
IDENTITY = "http://127.0.0.1:54330"


def verify() -> dict:
    checks = []

    def check(name, condition):
        checks.append({"name": name, "passed": bool(condition)})
        print(f"{'PASS' if condition else 'FAIL'} {name}", flush=True)
        if not condition:
            raise AssertionError(name)

    with httpx.Client(timeout=15, trust_env=False) as client:
        sessions = {
            role: client.get(f"{IDENTITY}/local-demo/session", params={"actor": role}).json()
            for role in ("finance", "supplier", "outsider", "unassigned")
        }

        def call(path, role="finance", method="GET", body=None, key=None):
            headers = {"Authorization": "Bearer " + sessions[role]["access_token"]} if role else {}
            if key:
                headers["Idempotency-Key"] = key
            return client.request(method, API + path, headers=headers, json=body)

        check(
            "Synthetic identity is explicit",
            client.get(IDENTITY + "/auth/v1/health").json().get("simulated") is True,
        )
        check(
            "Ready with local isolated database and private storage",
            call("/api/ready").status_code == 200,
        )
        check(
            "Unauthenticated payment access denied",
            call("/api/payments", role=None).status_code == 401,
        )
        check(
            "Unassigned identity denied",
            call("/api/payments", role="unassigned").status_code == 403,
        )
        check(
            "Supplier cannot list finance payments",
            call("/api/payments", role="supplier").status_code == 403,
        )
        supplier = call("/api/suppliers").json()["suppliers"][0]
        sid = supplier["id"]
        version = supplier["current_beneficiary"]["id"]
        check(
            "Outsider tenant has no supplier records",
            call("/api/suppliers", role="outsider").json()["suppliers"] == [],
        )
        check(
            "Supplier attestation",
            call(
                f"/api/suppliers/{sid}/confirmations",
                role="supplier",
                method="POST",
                body={"beneficiary_version_id": version},
            ).status_code
            == 200,
        )
        check(
            "Separate finance acceptance",
            call(
                f"/api/suppliers/{sid}/acceptances",
                method="POST",
                body={"beneficiary_version_id": version},
            ).status_code
            == 200,
        )
        check(
            "Private storage upload/read/deny/delete",
            call("/api/storage/check", method="POST").status_code == 200,
        )
        for simulation in ("success", "decline", "lost_response"):
            invoice = "SYN-VERIFY-" + uuid4().hex[:10]
            body = {
                "supplier_id": sid,
                "invoice_reference": invoice,
                "amount_minor": 123456,
                "currency": "INR",
                "simulation": simulation,
            }
            response = call("/api/payments", method="POST", body=body)
            check(f"{simulation}: intent created", response.status_code == 201)
            payment = response.json()
            pid = payment["id"]

            def decision(p):
                return {
                    "revision_id": p["current_revision"]["id"],
                    "digest": p["current_revision"]["digest"],
                }

            check(
                f"{simulation}: outsider cannot read payment",
                call(f"/api/payments/{pid}", role="outsider").status_code == 404,
            )
            check(
                f"{simulation}: cannot queue without approval",
                call(
                    f"/api/payments/{pid}/queue",
                    method="POST",
                    body=decision(payment),
                    key=uuid4().hex,
                ).status_code
                == 409,
            )
            old = decision(payment)
            check(
                f"{simulation}: exact approval",
                call(f"/api/payments/{pid}/approvals", method="POST", body=old).status_code == 200,
            )
            payment = call(
                f"/api/payments/{pid}/revisions",
                method="POST",
                body={
                    "expected_revision_id": old["revision_id"],
                    "amount_minor": 123457,
                    "simulation": simulation,
                },
            ).json()
            check(
                f"{simulation}: old approval invalidated",
                call(
                    f"/api/payments/{pid}/queue", method="POST", body=old, key=uuid4().hex
                ).status_code
                == 409,
            )
            current = decision(payment)
            check(f"{simulation}: fresh approval required", payment["approval"] is None)
            call(f"/api/payments/{pid}/approvals", method="POST", body=current).raise_for_status()
            request_key = uuid4().hex
            with ThreadPoolExecutor(max_workers=6) as pool:
                responses = list(
                    pool.map(
                        lambda _: call(
                            f"/api/payments/{pid}/queue",
                            method="POST",
                            body=current,
                            key=request_key,
                        ),
                        range(6),
                    )
                )
            check(
                f"{simulation}: concurrent queue requests converge",
                all(r.status_code == 200 for r in responses)
                and len({r.json()["execution"]["id"] for r in responses}) == 1,
            )
            execution = responses[0].json()["execution"]["id"]
            seen = set()
            deadline = time.monotonic() + 40
            checked_unknown = False
            while time.monotonic() < deadline:
                payment = call(f"/api/payments/{pid}").json()
                seen.add(payment["state"])
                if payment["state"] == "UNKNOWN" and not checked_unknown:
                    check(
                        "UNKNOWN blocks material revision",
                        call(
                            f"/api/payments/{pid}/revisions",
                            method="POST",
                            body={
                                "expected_revision_id": current["revision_id"],
                                "amount_minor": 123458,
                                "simulation": simulation,
                            },
                        ).status_code
                        == 409,
                    )
                    check(
                        "UNKNOWN prevents duplicate invoice replacement",
                        call("/api/payments", method="POST", body=body).status_code == 409,
                    )
                    check(
                        "UNKNOWN blocks beneficiary change",
                        call(
                            f"/api/suppliers/{sid}/beneficiaries",
                            method="POST",
                            body={
                                "expected_version_id": version,
                                "beneficiary_name": "Kaveri Packaging",
                                "sandbox_account_id": "SIM-BLOCKED-999",
                            },
                        ).status_code
                        == 409,
                    )
                    checked_unknown = True
                if payment["state"] in {"SUCCEEDED", "FAILED"}:
                    break
                time.sleep(0.5)
            check(
                f"{simulation}: terminal result independently verified",
                payment["state"] == ("FAILED" if simulation == "decline" else "SUCCEEDED")
                and payment["execution"]["id"] == execution
                and bool(payment["execution"]["transfer_id"]),
            )
            if simulation == "lost_response":
                check(
                    "Lost response visibly entered UNKNOWN before reconciliation", "UNKNOWN" in seen
                )
            replay = call(
                f"/api/payments/{pid}/queue", method="POST", body=current, key=request_key
            )
            check(
                f"{simulation}: terminal replay retains original execution",
                replay.status_code == 200 and replay.json()["execution"]["id"] == execution,
            )
        return {
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "environment": "local synthetic simulators",
            "live_providers_verified": False,
            "checks": checks,
            "passed": True,
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/local-workflow.json")
    args = parser.parse_args()
    try:
        report = verify()
    except (AssertionError, httpx.HTTPError, ValueError, KeyError):
        raise SystemExit(
            "Local workflow verification failed; no provider credentials were logged."
        ) from None
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
