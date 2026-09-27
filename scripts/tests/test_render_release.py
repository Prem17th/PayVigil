import importlib.util
import io
import json
import multiprocessing
import queue
import stat
from argparse import Namespace
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import httpx
import pytest

SPEC = importlib.util.spec_from_file_location(
    "release", Path(__file__).parents[1] / "render_release.py"
)
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


@pytest.fixture
def config():
    return release.settings(
        {
            "RENDER_OWNER_ID": "tea-synthetic",
            "RENDER_REPO_URL": "https://github.com/example/synthetic",
            "RENDER_BRANCH": "main",
        }
    )


def test_offline_plan_never_initializes_client(monkeypatch, capsys):
    monkeypatch.setattr(release, "Render", lambda *_: pytest.fail("Offline plan attempted network"))
    monkeypatch.setenv("OPENAI_API_KEY", "do-not-print-this-secret")
    assert release.main(["plan"]) == 0
    output = capsys.readouterr().out
    assert "do-not-print-this-secret" not in output
    assert json.loads(output)["order"] == ["sandbox", "api", "web", "worker"]


@pytest.mark.parametrize(
    "value",
    [
        "http://example.org",
        "https://user:secret@example.org",
        "https://example.org/x",
        "https://example.org?key=secret",
        "//example.org",
    ],
)
def test_provider_origin_guard(value):
    with pytest.raises(release.ReleaseError):
        release.https_origin(value)


def test_frontend_receives_only_public_values():
    state = {"services": {"api": {"url": "https://api.example.org"}}}
    values = release.service_env(
        "web",
        {
            "SUPABASE_URL": "https://project.supabase.co",
            "SUPABASE_PUBLISHABLE_KEY": "sb_publishable_synthetic",
            "SUPABASE_SECRET_KEY": "sensitive",
            "DATABASE_URL": "sensitive",
        },
        state,
    )
    assert "sensitive" not in values.values()
    assert set(values) == {
        "NODE_VERSION",
        "VITE_LOCAL_SANDBOX",
        "VITE_API_BASE_URL",
        "VITE_SUPABASE_URL",
        "VITE_SUPABASE_PUBLISHABLE_KEY",
    }
    assert values["VITE_LOCAL_SANDBOX"] == "false"


def test_service_specs_keep_migration_secrets_out_of_runtime(config):
    specs = release.specs(config)
    assert all(spec["autoDeploy"] == "no" for spec in specs.values())
    assert specs["api"]["serviceDetails"]["preDeployCommand"] == "alembic upgrade head"
    assert (
        "env -u MIGRATION_DATABASE_URL"
        in specs["api"]["serviceDetails"]["envSpecificDetails"]["startCommand"]
    )
    assert specs["worker"]["type"] == "background_worker"
    assert specs["web"]["serviceDetails"]["routes"][0]["type"] == "rewrite"


def test_worker_has_no_api_or_migration_credentials():
    state = {"services": {"sandbox": {"url": "https://sandbox.example.org"}}}
    values = release.service_env(
        "worker",
        {
            "WORKER_DATABASE_URL": "worker-value",
            "SANDBOX_API_KEY": "synthetic-secret",
            "MIGRATION_DATABASE_URL": "forbidden",
            "OPENAI_API_KEY": "forbidden",
        },
        state,
    )
    assert "forbidden" not in values.values()
    assert values["PAYMENTS_SANDBOX_API_KEY"] == "synthetic-secret"


def test_secure_env_file_rejects_group_readable(tmp_path):
    path = tmp_path / ".env.release"
    path.write_text("SYNTHETIC=value\n")
    path.chmod(0o644)
    with pytest.raises(release.ReleaseError):
        release.secure_file(path)
    path.chmod(0o600)
    assert release.secure_file(path) == path.resolve()


def test_api_errors_never_print_provider_secret_body():
    def mock(request):
        assert str(request.url) == "https://api.render.com/v1/services"
        return httpx.Response(400, json={"secret": "must-not-leak"})

    api = release.Render("synthetic-token", transport=httpx.MockTransport(mock))
    try:
        with pytest.raises(release.ReleaseError) as error:
            api.call("POST", "/services", json={})
        assert "must-not-leak" not in str(error.value)
    finally:
        api.close()


def test_redirect_does_not_forward_bearer():
    calls = []

    def mock(request):
        calls.append(str(request.url))
        return httpx.Response(302, headers={"Location": "https://untrusted.example"})

    api = release.Render("synthetic-token", transport=httpx.MockTransport(mock))
    try:
        with pytest.raises(release.ReleaseError):
            api.call("GET", "/services")
        assert calls == ["https://api.render.com/v1/services"]
    finally:
        api.close()


def test_uncertain_create_is_journalled_and_never_repeated(tmp_path, config):
    state = {"services": {}, "operations": {}}
    args = Namespace(command="create", service="sandbox", state=tmp_path / "state.json")
    calls = []

    def mock(request):
        calls.append(request)
        payload = json.loads(request.content)
        assert payload["envVars"] == []
        assert payload["serviceDetails"]["envSpecificDetails"] == {
            "buildCommand": "true",
            "startCommand": "sleep 86400",
        }
        assert payload["serviceDetails"]["preDeployCommand"] == "true"
        raise httpx.ReadTimeout("synthetic timeout")

    api = release.Render("synthetic-token", transport=httpx.MockTransport(mock))
    env = {name: "generated-test-value" for name in release.SECRET_ENV["sandbox"]}
    try:
        with pytest.raises(release.ReleaseError):
            release.execute(args, env, state, api, config)
        saved = json.loads(args.state.read_text())
        assert saved["operations"]["create:sandbox"] == "requested_outcome_unknown"
        assert "generated-test-value" not in args.state.read_text()
        with pytest.raises(release.ReleaseError):
            release.execute(args, env, saved, api, config)
        assert len(calls) == 1
    finally:
        api.close()


@pytest.mark.parametrize("key", ["sb_secret_synthetic", "unknown-key", "eyJx.e30.signature"])
def test_frontend_key_rejected_before_transmission(key):
    with pytest.raises(release.ReleaseError):
        release.service_env(
            "web",
            {"SUPABASE_URL": "https://project.supabase.co", "SUPABASE_PUBLISHABLE_KEY": key},
            {"services": {"api": {"url": "https://api.example.org"}}},
        )


def test_changed_build_commands_rejected(config):
    spec = release.specs(config)["api"]
    actual = json.loads(json.dumps(spec))
    actual["serviceDetails"]["envSpecificDetails"]["startCommand"] = "unreviewed command"
    with pytest.raises(release.ReleaseError):
        release.verify_runtime(actual, spec)


def test_remote_secret_drift_rejected_without_output():
    api = release.Render(
        "synthetic",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json=[
                    {"envVar": {"key": "SYNTHETIC", "value": "secret-drift"}, "cursor": "cursor"}
                ],
            )
        ),
    )
    try:
        with pytest.raises(release.ReleaseError) as error:
            release.verify_environment(api, "srv-synthetic", {"SYNTHETIC": "expected-value"})
        assert "secret-drift" not in str(error.value)
    finally:
        api.close()


def test_live_deploy_without_reviewed_expected_commit_fails(tmp_path, config):
    spec = release.specs(config)["api"]
    remote = {
        **spec,
        "id": "srv-synthetic",
        "serviceDetails": {**spec["serviceDetails"], "url": "https://api.example.org"},
    }

    def mock(request):
        if "/deploys/" in request.url.path:
            return httpx.Response(200, json={"status": "live", "commit": {"id": "b" * 40}})
        return httpx.Response(200, json=remote)

    api = release.Render("synthetic", transport=httpx.MockTransport(mock))
    try:
        args = Namespace(
            command="status",
            service="api",
            state=tmp_path / "state.json",
            deploy_id="dep-synthetic",
        )
        with pytest.raises(release.ReleaseError):
            release.execute(
                args,
                {},
                {"services": {"api": {"id": "srv-synthetic"}}, "operations": {}},
                api,
                config,
            )
    finally:
        api.close()


def test_configure_deploy_status_preserve_verified_journal(tmp_path, config):
    spec = release.specs(config)["web"]
    remote = {**release.inert_spec(spec), "id": "srv-websynthetic"}
    remote["serviceDetails"]["url"] = "https://web.example.org"
    environment, rules, deployment = {}, {}, {}

    def mock(request):
        path, method = request.url.path, request.method
        body = json.loads(request.content) if request.content else None
        if path.endswith("/env-vars"):
            return httpx.Response(
                200,
                json=[
                    {"envVar": {"key": k, "value": v}, "cursor": "x"}
                    for k, v in environment.items()
                ],
            )
        if "/env-vars/" in path:
            environment[path.rsplit("/", 1)[1]] = body["value"]
            return httpx.Response(200, json={})
        for group, singular in (("headers", "header"), ("routes", "route")):
            if path.endswith("/" + group):
                if method == "PUT":
                    rules[group] = body
                return httpx.Response(200, json=[{singular: row} for row in rules.get(group, [])])
        if path.endswith("/deploys"):
            deployment.update(id="dep-synthetic", status="live", commit={"id": body["commitId"]})
            return httpx.Response(201, json=deployment)
        if "/deploys/" in path:
            return httpx.Response(200, json=deployment)
        if method == "PATCH":
            remote["serviceDetails"].update(body["serviceDetails"])
        return httpx.Response(200, json=remote)

    api = release.Render("synthetic", transport=httpx.MockTransport(mock))
    state = {
        "services": {
            "web": {"id": "srv-websynthetic"},
            "api": {"id": "srv-api", "url": "https://api.example.org"},
        },
        "operations": {},
    }
    env = {
        "SUPABASE_URL": "https://project.supabase.co",
        "SUPABASE_PUBLISHABLE_KEY": "sb_publishable_synthetic",
    }
    args = Namespace(
        command="configure",
        service="web",
        state=tmp_path / "state.json",
        commit="c" * 40,
        deploy_id=None,
    )
    try:
        release.execute(args, env, state, api, config)
        fingerprint = state["services"]["web"]["configuration_sha256"]
        args.command = "deploy"
        release.execute(args, env, state, api, config)
        args.command = "status"
        release.execute(args, env, state, api, config)
        entry = json.loads(args.state.read_text())["services"]["web"]
        assert entry["configuration_sha256"] == fingerprint
        assert entry["commit"] == "c" * 40 and entry["deploy_id"] == "dep-synthetic"
    finally:
        api.close()


def test_adopt_rejects_wrong_workspace(config):
    spec = release.specs(config)["api"]
    remote = {**spec, "ownerId": "tea-other"}
    with pytest.raises(release.ReleaseError):
        release.verify_service(remote, spec)


def test_release_requires_exact_commit_and_complete_secrets(tmp_path, config):
    spec = release.specs(config)["api"]
    remote = {**spec, "id": "srv-synthetic", "serviceDetails": {"url": "https://api.example.org"}}
    calls = []

    def mock(request):
        calls.append(request.method)
        return httpx.Response(200, json=remote)

    api = release.Render("synthetic-token", transport=httpx.MockTransport(mock))
    state = {"services": {"api": {"id": "srv-synthetic"}}, "operations": {}}
    args = Namespace(command="deploy", service="api", state=tmp_path / "state.json", commit="main")
    try:
        with pytest.raises(release.ReleaseError):
            release.execute(args, {}, state, api, config)
        args.commit = "a" * 40
        with pytest.raises(release.ReleaseError):
            release.execute(args, {}, state, api, config)
        assert calls == ["GET", "GET"]
    finally:
        api.close()


def _concurrent_create_process(root, entered, finish, calls, result):
    """Run the real CLI boundary with a local provider and synthetic config."""
    release.ROOT = Path(root)
    release.environment = lambda _: {
        "RENDER_OWNER_ID": "tea-synthetic",
        "RENDER_REPO_URL": "https://github.com/example/synthetic",
        "RENDER_BRANCH": "main",
        "RENDER_API_KEY": "synthetic-not-a-credential",
    }

    class LocalRender:
        def __init__(self, _):
            pass

        def call(self, method, path, **kwargs):
            assert (method, path) == ("POST", "/services")
            calls.put((method, path))
            entered.set()
            if not finish.wait(15):
                raise AssertionError("The test did not release its local provider.")
            remote = {**kwargs["json"], "id": "srv-synthetic"}
            remote["serviceDetails"]["url"] = "https://sandbox.example.org"
            return {"service": remote}

        def close(self):
            pass

    release.Render = LocalRender
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        status = release.main(
            [
                "create",
                "--service",
                "sandbox",
                "--state",
                str(Path(root) / ".local" / "release.json"),
            ]
        )
    result.put((status, out.getvalue(), err.getvalue()))


def test_concurrent_create_processes_send_one_provider_request(tmp_path):
    context = multiprocessing.get_context("spawn")
    entered, finish = context.Event(), context.Event()
    calls, first_result, second_result = context.Queue(), context.Queue(), context.Queue()
    first = context.Process(
        target=_concurrent_create_process,
        args=(str(tmp_path), entered, finish, calls, first_result),
    )
    second = context.Process(
        target=_concurrent_create_process,
        args=(str(tmp_path), entered, finish, calls, second_result),
    )
    started = []
    try:
        first.start()
        started.append(first)
        assert entered.wait(10), "First command did not reach its mocked provider."
        second.start()
        started.append(second)
        second.join(5)
        assert not second.is_alive(), "Concurrent command waited instead of failing promptly."
        assert second.exitcode == 0
        status, out, err = second_result.get(timeout=2)
        assert status == 2 and out == ""
        assert "Another release command is active for this journal" in err
        finish.set()
        first.join(10)
        assert first.exitcode == 0
        status, out, err = first_result.get(timeout=2)
        assert status == 0 and "Provisioned inert sandbox" in out and err == ""
        assert calls.get(timeout=2) == ("POST", "/services")
        with pytest.raises(queue.Empty):
            calls.get_nowait()
        state_path = tmp_path / ".local" / "release.json"
        saved = release.read_state(state_path)
        assert saved["operations"]["create:sandbox"] == "created"
        assert saved["services"]["sandbox"]["id"] == "srv-synthetic"
        assert stat.S_IMODE(state_path.stat().st_mode) == 0o600
        # The persistent lock file is harmless once the owner exits.
        assert state_path.with_name(state_path.name + ".lock").is_file()
        with release.journal_lock(state_path):
            assert release.read_state(state_path) == saved
    finally:
        finish.set()
        for process in started:
            if process.is_alive():
                process.terminate()
            process.join(5)
        for channel in (calls, first_result, second_result):
            channel.close()
            channel.join_thread()


def test_journal_lock_releases_after_failure_and_is_per_journal(tmp_path):
    path = tmp_path / "release.json"
    with pytest.raises(release.ReleaseError, match="synthetic failure"):
        with release.journal_lock(path):
            with release.journal_lock(tmp_path / "another.json"):
                raise release.ReleaseError("synthetic failure")
    with release.journal_lock(path):
        release.save_state(path, {"operations": {"create:sandbox": "requested_outcome_unknown"}})
    assert release.read_state(path)["operations"]["create:sandbox"] == "requested_outcome_unknown"


def test_failed_journal_serialization_preserves_previous_state_and_cleans_temp(
    tmp_path, monkeypatch
):
    path = tmp_path / "release.json"
    release.save_state(path, {"operations": {"create:sandbox": "requested_outcome_unknown"}})
    original = path.read_bytes()

    def fail_mid_write(_, stream, **kwargs):
        stream.write('{"partial":')
        raise TypeError("synthetic serialization failure")

    monkeypatch.setattr(release.json, "dump", fail_mid_write)
    with pytest.raises(TypeError):
        release.save_state(path, {"different": "state"})
    assert path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [path]
