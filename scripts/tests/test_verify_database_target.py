"""Hosted database preflight guards; all environment and DB access is mocked."""

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import make_url


SYNTHETIC_URL = "postgresql://synthetic_owner:synthetic-password@db.example.invalid/expected_app"


@pytest.fixture
def preflight(monkeypatch):
    scripts = Path(__file__).parents[1]
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location(
        "database_preflight_under_test", scripts / "verify_database_target.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Replace module references rather than reading or mutating the host environment.
    module.os = SimpleNamespace(environ={})
    module.certifi = SimpleNamespace(where=lambda: "/synthetic/certifi-ca.pem")
    module.psycopg = SimpleNamespace(
        connect=lambda *a, **kw: pytest.fail("Unmocked connection attempted")
    )
    module.environment = lambda _path: pytest.fail("Real environment loader must not be called")
    return module


class Result:
    def __init__(self, values):
        self.values = values

    def fetchone(self):
        return self.values

    def __iter__(self):
        return iter(self.values)


class Connection:
    def __init__(self, database="expected_app", encrypted=True):
        self.database = database
        self.encrypted = encrypted
        self.queries = []
        self.entered = False
        self.exited = False

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, *_):
        self.exited = True

    def execute(self, query):
        self.queries.append(query)
        if query.startswith("SELECT current_database()"):
            return Result((self.database, "synthetic_owner", "18.6"))
        if query.startswith("SELECT rolsuper"):
            return Result((False, False, True, False, False))
        if query.startswith("SELECT ssl,version"):
            return Result((self.encrypted, "TLSv1.3" if self.encrypted else None))
        if query.startswith("SELECT schemaname,count(*)"):
            return Result([("beforetransfer", 3)])
        pytest.fail("Unexpected SQL in read-only preflight")


def invoke(
    module, monkeypatch, tmp_path, env, *, connection=None, error=None, expected="expected_app"
):
    output = tmp_path / "nested" / "preflight.json"
    sentinel = tmp_path / "synthetic-unused.env"
    calls = []
    loaded = []
    connection = connection or Connection()

    def environment(path):
        loaded.append(path)
        assert path == sentinel
        return dict(env)

    def connect(dsn, **kwargs):
        calls.append((dsn, kwargs))
        if error is not None:
            raise error
        return connection

    monkeypatch.setattr(module, "environment", environment)
    monkeypatch.setattr(module.psycopg, "connect", connect)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "verify_database_target.py",
            "--env-file",
            str(sentinel),
            "--expected-database",
            expected,
            "--output",
            str(output),
        ],
    )
    result = module.main()
    return result, json.loads(output.read_text()), calls, connection, loaded


@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql://synthetic_owner:synthetic-password@db.example.invalid/wrong_database",
        "postgresql:///expected_app",
        "sqlite:///expected_app",
        "",
    ],
)
def test_rejects_wrong_database_missing_host_and_non_postgresql_before_connect(
    preflight, monkeypatch, tmp_path, dsn
):
    code, report, calls, _, loaded = invoke(
        preflight, monkeypatch, tmp_path, {"MIGRATION_DATABASE_URL": dsn}
    )
    assert code == 1 and report["passed"] is False
    assert not calls and len(loaded) == 1
    assert "identity" not in report
    assert "synthetic-password" not in json.dumps(report)


@pytest.mark.parametrize("sslmode", ["disable", "allow", "prefer", "require", "verify-ca"])
def test_rejects_weaker_tls_modes_before_connect(preflight, monkeypatch, tmp_path, sslmode):
    code, report, calls, _, _ = invoke(
        preflight,
        monkeypatch,
        tmp_path,
        {"MIGRATION_DATABASE_URL": SYNTHETIC_URL + "?sslmode=" + sslmode},
    )
    assert code == 1 and report["error_type"] == "ReleaseError"
    assert not calls


@pytest.mark.parametrize(
    "override",
    [
        "host=other.example.invalid",
        "hostaddr=192.0.2.10",
        "dbname=other_database",
        "user=other_user",
        "password=other-password",
        "service=other_service",
        "options=-c+default_transaction_read_only%3Doff",
        "target_session_attrs=read-write",
    ],
)
def test_rejects_connection_routing_and_session_query_overrides(
    preflight, monkeypatch, tmp_path, override
):
    code, report, calls, _, _ = invoke(
        preflight,
        monkeypatch,
        tmp_path,
        {"MIGRATION_DATABASE_URL": SYNTHETIC_URL + "?sslmode=verify-full&" + override},
    )
    assert code == 1 and report["error_type"] == "ReleaseError"
    assert not calls
    assert "other-password" not in json.dumps(report)


@pytest.mark.parametrize("driver", ["postgresql", "postgresql+psycopg", "postgres"])
def test_connect_is_read_only_bounded_verified_and_clears_libpq_environment(
    preflight, monkeypatch, tmp_path, capsys, driver
):
    preflight.os.environ = {
        "PGHOST": "wrong.example.invalid",
        "PGSERVICE": "hidden-routing",
        "PGOPTIONS": "-c default_transaction_read_only=off",
        "PGSSLMODE": "disable",
        "PGDATABASE": "wrong_database",
        "PGPASSWORD": "environment-password",
        "UNRELATED": "preserved",
    }
    dsn = (
        SYNTHETIC_URL.replace("postgresql:", driver + ":")
        + "?connect_timeout=999&sslmode=verify-full"
    )
    code, report, calls, connection, _ = invoke(
        preflight, monkeypatch, tmp_path, {"MIGRATION_DATABASE_URL": dsn}
    )
    assert code == 0 and report["passed"] is True and len(calls) == 1
    actual = make_url(calls[0][0])
    assert actual.drivername == "postgresql" and actual.database == "expected_app"
    assert actual.host == "db.example.invalid" and actual.password == "synthetic-password"
    assert actual.query == {"sslmode": "verify-full", "sslrootcert": "/synthetic/certifi-ca.pem"}
    assert calls[0][1] == {
        "connect_timeout": 8,
        "options": "-c default_transaction_read_only=on -c statement_timeout=8000",
    }
    assert preflight.os.environ == {"UNRELATED": "preserved"}
    assert connection.entered and connection.exited
    assert len(connection.queries) == 4 and all(
        query.startswith("SELECT ") for query in connection.queries
    )
    assert report["role"]["create_role"] is True and report["role"]["bypass_rls"] is False
    assert report["tls"] == {"encrypted": True, "protocol": "TLSv1.3"}
    printed = capsys.readouterr().out
    for sensitive in (
        "synthetic-password",
        "environment-password",
        "postgresql://",
        "wrong.example.invalid",
    ):
        assert sensitive not in printed and sensitive not in json.dumps(report)


@pytest.mark.parametrize(
    "url_roots,environment_roots,expected_roots",
    [
        (None, None, "/synthetic/certifi-ca.pem"),
        (None, "system", "/synthetic/certifi-ca.pem"),
        ("system", "/synthetic/ignored-ca.pem", "/synthetic/certifi-ca.pem"),
        (None, "/synthetic/provider-ca.pem", "/synthetic/provider-ca.pem"),
        ("/synthetic/url-ca.pem", "/synthetic/environment-ca.pem", "/synthetic/url-ca.pem"),
    ],
)
def test_certifi_system_substitution_and_explicit_certificate_precedence(
    preflight, monkeypatch, tmp_path, url_roots, environment_roots, expected_roots
):
    url = make_url(SYNTHETIC_URL)
    if url_roots is not None:
        url = url.set(query={"sslrootcert": url_roots})
    env = {"MIGRATION_DATABASE_URL": url.render_as_string(hide_password=False)}
    if environment_roots is not None:
        env["PGSSLROOTCERT"] = environment_roots
    code, _, calls, _, _ = invoke(preflight, monkeypatch, tmp_path, env)
    assert code == 0
    assert make_url(calls[0][0]).query["sslrootcert"] == expected_roots


@pytest.mark.parametrize(
    "connection", [Connection(database="unexpected_actual_database"), Connection(encrypted=False)]
)
def test_readback_must_match_expected_database_and_actual_tls(
    preflight, monkeypatch, tmp_path, connection
):
    code, report, calls, _, _ = invoke(
        preflight,
        monkeypatch,
        tmp_path,
        {"MIGRATION_DATABASE_URL": SYNTHETIC_URL},
        connection=connection,
    )
    assert code == 1 and report["passed"] is False and len(calls) == 1
    assert connection.exited


def test_connection_failure_report_redacts_raw_error_and_dsn(
    preflight, monkeypatch, tmp_path, capsys
):
    raw = "Cannot connect to " + SYNTHETIC_URL + " using password leaked-provider-password"
    code, report, calls, _, _ = invoke(
        preflight,
        monkeypatch,
        tmp_path,
        {"MIGRATION_DATABASE_URL": SYNTHETIC_URL},
        error=RuntimeError(raw),
    )
    assert code == 1 and len(calls) == 1
    assert report["error_type"] == "RuntimeError" and "error" not in report
    printed = capsys.readouterr().out
    for sensitive in (
        SYNTHETIC_URL,
        "synthetic-password",
        "leaked-provider-password",
        "Cannot connect",
    ):
        assert sensitive not in printed and sensitive not in json.dumps(report)


def test_query_failure_is_redacted_and_connection_context_closes(
    preflight, monkeypatch, tmp_path, capsys
):
    connection = Connection()

    def failed_query(_):
        raise RuntimeError("SQL failed with secret " + SYNTHETIC_URL)

    connection.execute = failed_query
    code, report, _, _, _ = invoke(
        preflight,
        monkeypatch,
        tmp_path,
        {"MIGRATION_DATABASE_URL": SYNTHETIC_URL},
        connection=connection,
    )
    assert code == 1 and report["error_type"] == "RuntimeError"
    assert connection.entered and connection.exited
    assert SYNTHETIC_URL not in capsys.readouterr().out


def test_blank_tls_parameter_still_connects_only_with_verify_full(preflight, monkeypatch, tmp_path):
    # SQLAlchemy drops a blank URL parameter; the preflight then forces its safe default.
    code, _, calls, _, _ = invoke(
        preflight, monkeypatch, tmp_path, {"MIGRATION_DATABASE_URL": SYNTHETIC_URL + "?sslmode="}
    )
    assert code == 0
    assert make_url(calls[0][0]).query["sslmode"] == "verify-full"


def test_duplicate_tls_parameters_cannot_override_verified_tls(preflight, monkeypatch, tmp_path):
    code, report, calls, _, _ = invoke(
        preflight,
        monkeypatch,
        tmp_path,
        {"MIGRATION_DATABASE_URL": SYNTHETIC_URL + "?sslmode=verify-full&sslmode=disable"},
    )
    assert code == 1 and report["error_type"] == "ReleaseError"
    assert not calls
