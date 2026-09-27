"""Plan and release PayVigil through the official Render REST API.

The default `plan` is offline and prints environment-variable NAMES only.
Mutating commands are explicit. Credentials come from the process environment or
an ignored owner-only env file. The journal contains IDs, never credential values.
"""

from __future__ import annotations

import argparse
import base64
import copy
import errno
import fcntl
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote, urlsplit

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
API = "https://api.render.com/v1"
ORDER = ("sandbox", "api", "web", "worker")
SECRET_ENV = {
    "sandbox": ("SANDBOX_DATABASE_URL", "SANDBOX_MIGRATION_DATABASE_URL", "SANDBOX_API_KEY"),
    "api": (
        "DATABASE_URL",
        "MIGRATION_DATABASE_URL",
        "SUPABASE_URL",
        "SUPABASE_PUBLISHABLE_KEY",
        "SUPABASE_SECRET_KEY",
        "OPENAI_API_KEY",
        "OPENAI_MODEL",
        "BREETH_API_KEY",
        "ELEVENLABS_API_KEY",
        "ELEVENLABS_VOICE_ID",
        "N8N_WEBHOOK_URL",
        "N8N_WEBHOOK_TOKEN",
        "N8N_CALLBACK_SECRET",
        "DODO_API_KEY",
        "DODO_WEBHOOK_SECRET",
        "DODO_PRODUCT_ID",
    ),
    "worker": ("WORKER_DATABASE_URL", "SANDBOX_API_KEY"),
    "web": ("SUPABASE_URL", "SUPABASE_PUBLISHABLE_KEY"),
}


class ReleaseError(Exception):
    pass


def secure_file(path: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_file() or stat.S_IMODE(resolved.stat().st_mode) & 0o077:
        raise ReleaseError(
            "The environment file must exist and be readable only by its owner (chmod 600)."
        )
    if (
        resolved.name != ".env"
        and not resolved.name.startswith(".env.")
        and ".local" not in resolved.parts
    ):
        raise ReleaseError(
            "Use an ignored .env file or a file inside .local for release credentials."
        )
    if resolved.name == ".env.example":
        raise ReleaseError("Do not put credentials in tracked example files.")
    return resolved


def environment(path: Path | None = None) -> dict[str, str]:
    values = (
        {
            key: str(value)
            for key, value in dotenv_values(secure_file(path)).items()
            if value is not None
        }
        if path
        else {}
    )
    return {**values, **os.environ}


def required(env: dict, name: str) -> str:
    value = env.get(name, "").strip()
    if not value:
        raise ReleaseError(f"Missing {name}; configure it securely before this command.")
    return value


def https_origin(value: str) -> str:
    parsed = urlsplit(value)
    if not (
        parsed.scheme == "https"
        and parsed.hostname
        and not parsed.username
        and not parsed.password
        and parsed.path in {"", "/"}
        and not parsed.query
        and not parsed.fragment
    ):
        raise ReleaseError("A provider returned an invalid public HTTPS origin.")
    return value.rstrip("/")


def service_id(value: str) -> str:
    if not re.fullmatch(r"srv-[a-z0-9]+", value):
        raise ReleaseError("Invalid Render service ID.")
    return value


def settings(env: dict) -> dict:
    repo = required(env, "RENDER_REPO_URL")
    parsed = urlsplit(repo)
    if not (
        parsed.scheme == "https"
        and parsed.hostname in {"github.com", "gitlab.com", "bitbucket.org"}
        and not parsed.username
        and not parsed.password
        and not parsed.query
        and not parsed.fragment
        and len(parsed.path.strip("/").split("/")) >= 2
    ):
        raise ReleaseError("RENDER_REPO_URL must be a credential-free HTTPS Git repository URL.")
    owner = required(env, "RENDER_OWNER_ID")
    if not re.fullmatch(r"(?:tea|usr)-[a-z0-9]+", owner):
        raise ReleaseError("Invalid Render workspace ID.")
    prefix = env.get("RENDER_NAME_PREFIX", "payvigil")
    if not re.fullmatch(r"[a-z][a-z0-9-]{2,40}", prefix):
        raise ReleaseError("Invalid service name prefix.")
    plan = env.get("RENDER_COMPUTE_PLAN", "starter")
    if plan not in {"starter", "standard", "0.5c-512mb", "1c-2g"}:
        raise ReleaseError(
            "Select a supported paid compute plan explicitly; review its current Render price."
        )
    return {
        "ownerId": owner,
        "repo": repo,
        "branch": required(env, "RENDER_BRANCH"),
        "prefix": prefix,
        "region": env.get("RENDER_REGION", "singapore"),
        "plan": plan,
    }


def specs(config: dict) -> dict[str, dict]:
    common = {key: config[key] for key in ("ownerId", "repo", "branch")}

    def native(key, kind, root, build, start, pre=None, health=None):
        details = {
            "runtime": "python",
            "region": config["region"],
            "plan": config["plan"],
            "numInstances": 1,
            "envSpecificDetails": {"buildCommand": build, "startCommand": start},
        }
        if pre:
            details["preDeployCommand"] = pre
        if health:
            details["healthCheckPath"] = health
        return {
            **common,
            "type": kind,
            "name": config["prefix"] + "-" + key,
            "rootDir": root,
            "autoDeploy": "no",
            "serviceDetails": details,
        }

    return {
        "sandbox": native(
            "sandbox",
            "web_service",
            "",
            "pip install -r backend/requirements.txt",
            "env -u SANDBOX_MIGRATION_DATABASE_URL uvicorn sandbox_service.app:app --host 0.0.0.0 --port $PORT",
            "python -m sandbox_service.bootstrap",
            "/ready",
        ),
        "api": native(
            "api",
            "web_service",
            "backend",
            "pip install -r requirements.txt",
            "env -u MIGRATION_DATABASE_URL uvicorn app.main:app --host 0.0.0.0 --port $PORT",
            "alembic upgrade head",
            "/api/ready",
        ),
        "worker": native(
            "worker",
            "background_worker",
            "backend",
            "pip install -r requirements.txt",
            "python -m app.payment_worker",
        ),
        "web": {
            **common,
            "type": "static_site",
            "name": config["prefix"] + "-web",
            "rootDir": "frontend",
            "autoDeploy": "no",
            "serviceDetails": {
                "buildCommand": "npm ci && npm run build",
                "publishPath": "dist",
                "headers": [
                    {"path": "/*", "name": name, "value": value}
                    for name, value in (
                        ("X-Content-Type-Options", "nosniff"),
                        ("X-Frame-Options", "DENY"),
                        ("Referrer-Policy", "strict-origin-when-cross-origin"),
                    )
                ],
                "routes": [{"type": "rewrite", "source": "/*", "destination": "/index.html"}],
            },
        },
    }


def public_url(state: dict, key: str) -> str:
    value = state.get("services", {}).get(key, {}).get("url")
    if not value:
        raise ReleaseError(
            f"Create/adopt the {key} service first so its actual public URL is known."
        )
    return https_origin(value)


def service_env(key: str, env: dict, state: dict, *, initial=False) -> dict[str, str]:
    source = {name: required(env, name) for name in SECRET_ENV[key]}
    if key == "web":
        public = source["SUPABASE_PUBLISHABLE_KEY"]
        if public.startswith("sb_secret_"):
            raise ReleaseError("A privileged Supabase key cannot be sent to the frontend service.")
        if public.startswith("eyJ"):
            try:
                part = public.split(".")[1]
                if (
                    json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))).get("role")
                    != "anon"
                ):
                    raise ValueError()
            except (ValueError, IndexError, TypeError):
                raise ReleaseError(
                    "Only a Supabase publishable or legacy anon key belongs in the frontend."
                ) from None
        elif not public.startswith("sb_publishable_"):
            raise ReleaseError("The frontend requires a Supabase publishable key.")
        return {
            "NODE_VERSION": "24.21.0",
            "VITE_LOCAL_SANDBOX": "false",
            "VITE_API_BASE_URL": public_url(state, "api"),
            "VITE_SUPABASE_URL": https_origin(source["SUPABASE_URL"]),
            "VITE_SUPABASE_PUBLISHABLE_KEY": source["SUPABASE_PUBLISHABLE_KEY"],
        }
    values = {"PYTHON_VERSION": "3.13.12", **source}
    if key == "sandbox":
        values.update(
            SANDBOX_APP_ENV="production",
            SANDBOX_PGSSLMODE="verify-full",
            SANDBOX_PGSSLROOTCERT=env.get("SANDBOX_PGSSLROOTCERT", "system"),
        )
    else:
        values.update(
            APP_ENV="production",
            PGSSLMODE="verify-full",
            PGSSLROOTCERT=env.get("PGSSLROOTCERT", "system"),
        )
    if key == "worker":
        values["PAYMENTS_SANDBOX_URL"] = public_url(state, "sandbox")
        values["PAYMENTS_SANDBOX_API_KEY"] = values.pop("SANDBOX_API_KEY")
    if key == "api":
        callback_mode = env.get("N8N_CALLBACK_AUTH_MODE", "header")
        if callback_mode not in {"header", "hmac"}:
            raise ReleaseError("N8N_CALLBACK_AUTH_MODE must be header or hmac.")
        values["N8N_CALLBACK_AUTH_MODE"] = callback_mode
        values["SUPABASE_STORAGE_BUCKET"] = env.get(
            "SUPABASE_STORAGE_BUCKET", "beforetransfer-evidence"
        )
        # The API may be provisioned before the frontend URL is allocated. The
        # configure command wires actual provider-returned origins before release.
        front = (
            "" if initial and "web" not in state.get("services", {}) else public_url(state, "web")
        )
        values["CORS_ORIGINS"] = front
        values["BILLING_FRONTEND_ORIGIN"] = front
    return values


def read_state(path: Path) -> dict:
    if not path.exists():
        return {"services": {}, "operations": {}}
    try:
        return json.loads(path.read_text())
    except (ValueError, OSError):
        raise ReleaseError(
            "The release journal is unreadable; preserve it and inspect locally."
        ) from None


@contextmanager
def journal_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Keep a separate, persistent inode: replacing the journal (or unlinking its
    # lock) must never allow another operator to acquire a different lock.
    lock_path = path.with_name(path.name + ".lock")
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            if error.errno in {errno.EACCES, errno.EAGAIN}:
                raise ReleaseError(
                    "Another release command is active for this journal. Wait for it to finish, then retry; do not remove the lock file."
                ) from None
            raise
        yield
    finally:
        # Closing releases the OS lock, including after failed provider calls.
        os.close(fd)


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    tmp = Path(name)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(state, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


class Render:
    def __init__(self, key: str, *, transport=None):
        self.client = httpx.Client(
            base_url=API,
            headers={"Authorization": "Bearer " + key},
            timeout=httpx.Timeout(35, connect=10),
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )

    def close(self):
        self.client.close()

    def call(self, method: str, path: str, **kwargs):
        try:
            response = self.client.request(method, path, **kwargs)
            if response.status_code not in {200, 201, 202, 204}:
                raise ReleaseError(
                    f"Render returned HTTP {response.status_code}. Provider bodies are omitted to protect secrets."
                )
            return response.json() if response.content else {}
        except (httpx.HTTPError, ValueError):
            raise ReleaseError(
                "Render response could not be verified. Inspect the journal and provider state before retrying a write."
            ) from None


def verify_service(remote: dict, spec: dict) -> None:
    if any(
        remote.get(name) != spec[name] for name in ("name", "type", "repo", "branch", "rootDir")
    ):
        raise ReleaseError(
            "The Render service does not match the selected repository, branch, name, type and root directory."
        )
    owner = remote.get("ownerId") or remote.get("owner", {}).get("id")
    if owner != spec["ownerId"]:
        raise ReleaseError("The Render service belongs to a different workspace.")
    if remote.get("autoDeploy") != "no":
        raise ReleaseError(
            "Disable automatic deploys on this service before using reviewed-commit release commands."
        )


def inert_spec(spec: dict) -> dict:
    """Render create auto-builds branch HEAD: provision without secrets or repo commands."""
    result = copy.deepcopy(spec)
    details = result["serviceDetails"]
    if result["type"] == "static_site":
        details.update(
            buildCommand="mkdir -p beforetransfer-provisioning",
            publishPath="beforetransfer-provisioning",
        )
    else:
        details["envSpecificDetails"] = {"buildCommand": "true", "startCommand": "sleep 86400"}
        details["preDeployCommand"] = "true"
    return result


def verify_runtime(remote: dict, spec: dict) -> None:
    actual, wanted = remote.get("serviceDetails", {}), spec["serviceDetails"]
    if spec["type"] == "static_site":
        names = ("buildCommand", "publishPath")
    else:
        names = ("runtime", "region", "plan", "numInstances", "envSpecificDetails")
        if "healthCheckPath" in wanted:
            names += ("healthCheckPath",)
    for name in names:
        if name == "envSpecificDetails":
            if any(actual.get(name, {}).get(k) != v for k, v in wanted[name].items()):
                raise ReleaseError(
                    "Render build/start commands differ from the reviewed service definition."
                )
        elif actual.get(name) != wanted[name]:
            raise ReleaseError(
                f"Render service setting {name} differs from the reviewed definition."
            )
    if spec["type"] != "static_site":
        pre = actual.get("envSpecificDetails", {}).get(
            "preDeployCommand", actual.get("preDeployCommand", "")
        )
        if pre != wanted.get("preDeployCommand", ""):
            raise ReleaseError(
                "Render migration/pre-deploy command differs from the reviewed definition."
            )


def read_environment(render: Render, sid: str) -> dict:
    values, cursor = {}, None
    for _ in range(20):
        params = {"limit": 100, **({"cursor": cursor} if cursor else {})}
        page = render.call("GET", f"/services/{sid}/env-vars", params=params)
        if not isinstance(page, list):
            raise ReleaseError("Render environment readback is invalid.")
        for item in page:
            entry = item.get("envVar", {})
            if not isinstance(entry.get("key"), str) or not isinstance(entry.get("value"), str):
                raise ReleaseError("Render environment readback is invalid.")
            values[entry["key"]] = entry["value"]
        if len(page) < 100:
            return values
        cursor = page[-1].get("cursor")
        if not cursor:
            break
    raise ReleaseError("Render environment pagination could not be verified.")


def verify_environment(render: Render, sid: str, expected: dict) -> str:
    actual = read_environment(render, sid)
    if actual != expected:
        raise ReleaseError(
            "Remote environment differs from the complete reviewed configuration. Reconfigure and inspect extra keys securely; values omitted."
        )
    return hashlib.sha256(json.dumps(expected, sort_keys=True).encode()).hexdigest()


def verify_static_rules(render: Render, sid: str, spec: dict):
    if spec["type"] != "static_site":
        return
    for group, singular, fields in (
        ("headers", "header", ("path", "name", "value")),
        ("routes", "route", ("type", "source", "destination")),
    ):
        actual = render.call("GET", f"/services/{sid}/{group}", params={"limit": 100})
        rows = [item.get(singular, item) for item in actual]

        def normalize(items):
            return sorted(tuple(item.get(k) for k in fields) for item in items)

        if normalize(rows) != normalize(spec["serviceDetails"][group]):
            raise ReleaseError("Static service headers/routes differ from the reviewed definition.")


def record_service(state: dict, key: str, service: dict) -> None:
    entry = {"id": service_id(service["id"]), "name": service["name"]}
    previous = state["services"].get(key, {})
    if previous.get("id") and previous["id"] != entry["id"]:
        raise ReleaseError(
            "This journal is bound to a different service ID. Use a separate journal for another resource."
        )
    url = service.get("serviceDetails", {}).get("url")
    if url:
        entry["url"] = https_origin(url)
    state["services"][key] = {**previous, **entry}


def execute(args, env: dict, state: dict, render: Render, config: dict):
    all_specs = specs(config)
    if args.command == "validate":
        with (ROOT / "render.yaml").open("rb") as file:
            body = render.call(
                "POST",
                "/blueprints/validate",
                data={"ownerId": config["ownerId"]},
                files={"file": ("render.yaml", file, "application/yaml")},
            )
        # The Blueprint contains references and names only, no secret values.
        print(
            json.dumps(
                {
                    "valid": body.get("valid"),
                    "plan": body.get("plan"),
                    "errors": body.get("errors", []),
                },
                indent=2,
            )
        )
        if body.get("valid") is not True:
            raise ReleaseError("Render Blueprint validation did not pass.")
        return
    key = args.service
    spec = all_specs[key]
    if args.command == "create":
        if key in state["services"]:
            raise ReleaseError(
                "This service is already in the journal. Use configure/deploy/status."
            )
        operation = "create:" + key
        if operation in state["operations"]:
            raise ReleaseError(
                "A previous create may have reached Render. Find that service and adopt its ID; never blindly create a duplicate."
            )
        payload = {**inert_spec(spec), "envVars": []}
        state["operations"][operation] = "requested_outcome_unknown"
        save_state(args.state, state)
        result = render.call("POST", "/services", json=payload)
        remote = result.get("service", {})
        verify_service(remote, spec)
        verify_runtime(remote, inert_spec(spec))
        record_service(state, key, remote)
        state["operations"][operation] = "created"
        if result.get("deployId"):
            state["services"][key]["deploy_id"] = result["deployId"]
        save_state(args.state, state)
        print(
            f"Provisioned inert {key} without credentials or application commands. Configure, then deploy an exact reviewed commit."
        )
        return
    sid = (
        service_id(args.id)
        if args.command == "adopt"
        else service_id(state["services"].get(key, {}).get("id", ""))
    )
    remote = render.call("GET", "/services/" + sid)
    verify_service(remote, spec)
    record_service(state, key, remote)
    save_state(args.state, state)
    if args.command == "adopt":
        # Adoption alone sends no credentials and runs no application commands.
        state["operations"]["create:" + key] = "adopted"
        save_state(args.state, state)
        print(f"Adopted verified {key} service.")
    elif args.command == "configure":
        values = service_env(key, env, state)
        # Change only this reviewed application's commands/settings, then read
        # them back before transmitting any secret. Autodeploy remains disabled.
        details = {
            k: v
            for k, v in spec["serviceDetails"].items()
            if k not in {"region", "numInstances", "headers", "routes"}
        }
        if key == "worker":
            details.setdefault("preDeployCommand", "")
        render.call(
            "PATCH", f"/services/{sid}", json={"autoDeploy": "no", "serviceDetails": details}
        )
        remote = render.call("GET", f"/services/{sid}")
        verify_service(remote, spec)
        verify_runtime(remote, spec)
        if key == "web":
            for group in ("headers", "routes"):
                render.call("PUT", f"/services/{sid}/{group}", json=spec["serviceDetails"][group])
            verify_static_rules(render, sid, spec)
        for name, value in values.items():
            render.call(
                "PUT", f"/services/{sid}/env-vars/{quote(name, safe='')}", json={"value": value}
            )
        state["services"][key]["configuration_sha256"] = verify_environment(render, sid, values)
        save_state(args.state, state)
        print(
            f"Configured {key}: {len(values)} environment variables; values omitted. Redeploy to apply."
        )
    elif args.command == "deploy":
        if not re.fullmatch(r"[a-f0-9]{40}", args.commit or ""):
            raise ReleaseError("Supply the exact reviewed 40-character Git commit with --commit.")
        operation = f"deploy:{key}:{args.commit}"
        if state["operations"].get(operation) == "requested_outcome_unknown":
            raise ReleaseError(
                "Previous deployment outcome is unknown. Inspect Render and adopt its deploy ID with status --deploy-id before retrying."
            )
        # Validate complete configuration without displaying it before releasing.
        verify_runtime(remote, spec)
        verify_static_rules(render, sid, spec)
        values = service_env(key, env, state)
        fingerprint = verify_environment(render, sid, values)
        if fingerprint != state["services"][key].get("configuration_sha256"):
            raise ReleaseError(
                "Run configure successfully before deploying this exact environment."
            )
        state["operations"][operation] = "requested_outcome_unknown"
        state["services"][key]["commit"] = args.commit
        save_state(args.state, state)
        deployed = render.call(
            "POST",
            f"/services/{sid}/deploys",
            json={"commitId": args.commit, "clearCache": "do_not_clear"},
        )
        deploy_id = deployed.get("id", "")
        if not re.fullmatch(r"dep-[a-z0-9]+", deploy_id):
            raise ReleaseError("Render deploy ID could not be verified; inspect remote state.")
        state["services"][key].update(deploy_id=deploy_id, commit=args.commit)
        state["operations"][operation] = "accepted"
        save_state(args.state, state)
        print(
            f"Requested {key} deployment at {args.commit}. Use status; request acceptance is not a successful release."
        )
    elif args.command == "status":
        deploy_id = args.deploy_id or state["services"][key].get("deploy_id", "")
        if not re.fullmatch(r"dep-[a-z0-9]+", deploy_id):
            raise ReleaseError("A valid --deploy-id or journalled deploy is required.")
        deployed = render.call("GET", f"/services/{sid}/deploys/{deploy_id}")
        commit = deployed.get("commit", {}).get("id")
        expected = state["services"][key].get("commit")
        print(
            json.dumps(
                {
                    "service": key,
                    "status": deployed.get("status"),
                    "commit": commit,
                    "expected_commit_matches": bool(expected and commit == expected),
                    "url": state["services"][key].get("url"),
                },
                indent=2,
            )
        )
        if deployed.get("status") != "live" or not expected or expected != commit:
            raise ReleaseError(
                "The selected deployment is not verified live at the expected commit."
            )
        state["services"][key]["deploy_id"] = deploy_id
        if expected:
            state["operations"][f"deploy:{key}:{expected}"] = "verified_live"
        save_state(args.state, state)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=("plan", "validate", "create", "adopt", "configure", "deploy", "status"),
        nargs="?",
        default="plan",
    )
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--state", type=Path, default=ROOT / ".local/render-release.json")
    parser.add_argument("--service", choices=ORDER)
    parser.add_argument("--id", help="Existing service ID to adopt after checking its identity.")
    parser.add_argument("--commit", help="Exact reviewed commit to deploy.")
    parser.add_argument(
        "--deploy-id", help="Read an explicit deployment after an uncertain request."
    )
    args = parser.parse_args(argv)
    render = None
    try:
        env = environment(args.env_file)
        if args.command == "plan":
            print(
                json.dumps(
                    {
                        "mode": "offline plan; no resources changed",
                        "order": ORDER,
                        "services": [
                            {
                                "service": key,
                                "billable_compute": key != "web",
                                "required_env": list(SECRET_ENV[key]),
                                "missing_env": [
                                    name for name in SECRET_ENV[key] if not env.get(name)
                                ],
                            }
                            for key in ORDER
                        ],
                        "remaining": [
                            "Choose workspace, Git repository and branch; review current compute prices",
                            "Verify restricted database roles, separate ledger, and Supabase Auth/Storage",
                            "Add credentials securely; validate Blueprint; create/adopt services",
                            "Configure actual service URLs, Supabase Auth URLs and n8n/Dodo callbacks",
                            "Deploy reviewed commit; run hosted verification and real-provider checks",
                        ],
                    },
                    indent=2,
                )
            )
            return 0
        if args.command != "validate" and not args.service:
            raise ReleaseError("Select one --service explicitly.")
        if args.state.resolve().parent != (ROOT / ".local").resolve():
            raise ReleaseError(
                "Keep the release journal directly inside this workspace's ignored .local directory."
            )
        args.state = args.state.resolve()
        config = settings(env)
        with journal_lock(args.state):
            state = read_state(args.state)
            bound = {k: config[k] for k in ("ownerId", "repo", "branch", "prefix")}
            if state.get("target") and state["target"] != bound:
                raise ReleaseError(
                    "The journal belongs to a different release target. Select a separate .local journal."
                )
            state["target"] = bound
            render = Render(required(env, "RENDER_API_KEY"))
            execute(args, env, state, render, config)
        return 0
    except (ReleaseError, OSError, KeyError, TypeError):
        error = sys.exc_info()[1]
        print(
            str(error)
            if isinstance(error, ReleaseError)
            else "Release configuration or provider response is invalid; sensitive details omitted.",
            file=sys.stderr,
        )
        return 2
    finally:
        if render:
            render.close()


if __name__ == "__main__":
    raise SystemExit(main())
