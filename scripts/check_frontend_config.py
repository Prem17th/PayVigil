"""Exercise the real Vite build with generated synthetic environment values.

No provider calls or real credentials. Output stays in ignored .local storage.
"""

import base64
import json
import os
import subprocess
from pathlib import Path
from uuid import uuid4


root = Path(__file__).resolve().parents[1]
base_env = {
    **os.environ,
    "VITE_API_BASE_URL": "https://api.example.invalid",
    "VITE_SUPABASE_URL": "https://identity.example.invalid",
    "VITE_SUPABASE_PUBLISHABLE_KEY": f"sb_publishable_{uuid4().hex}",
}


def encode(value: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")


synthetic_jwt = ".".join(
    (
        encode({"alg": "HS256", "typ": "JWT"}),
        encode({"role": "service_role", "nonce": uuid4().hex}),
        uuid4().hex,
    )
)
cases = [
    ("public HTTPS configuration", {}, True, None),
    (
        "privileged key prefix",
        {"VITE_SUPABASE_PUBLISHABLE_KEY": f"sb_secret_{uuid4().hex}"},
        False,
        "Privileged credentials cannot be bundled",
    ),
    (
        "legacy privileged key role",
        {"VITE_SUPABASE_PUBLISHABLE_KEY": synthetic_jwt},
        False,
        "Privileged credentials cannot be bundled",
    ),
    (
        "unencrypted API origin",
        {"VITE_API_BASE_URL": "http://api.example.invalid"},
        False,
        "VITE_API_BASE_URL must be an HTTPS origin",
    ),
    (
        "credentials in API origin",
        {"VITE_API_BASE_URL": f"https://{uuid4().hex}@api.example.invalid"},
        False,
        "VITE_API_BASE_URL must be an HTTPS origin",
    ),
    (
        "query in provider origin",
        {"VITE_SUPABASE_URL": f"https://identity.example.invalid?token={uuid4().hex}"},
        False,
        "VITE_SUPABASE_URL must be an HTTPS origin",
    ),
]

passed = True
for name, overrides, expect_success, expected_message in cases:
    result = subprocess.run(
        ["node", "node_modules/vite/bin/vite.js", "build", "--outDir", ".local/guard-check"],
        cwd=root / "frontend",
        env={**base_env, **overrides},
        text=True,
        capture_output=True,
        timeout=60,
    )
    output = result.stdout + result.stderr
    ok = (result.returncode == 0) == expect_success
    if expected_message:
        ok = ok and expected_message in output
    # Even rejected synthetic values should not be echoed in build logs.
    ok = ok and not any(value in output for value in overrides.values())
    passed = passed and ok
    print(f"{'PASS' if ok else 'FAIL'} {name}")

raise SystemExit(0 if passed else 1)
