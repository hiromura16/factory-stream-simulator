"""CLIとMCPが、明示した経路と確認ファイルだけを使うことを確認する。"""

import json
import os
import subprocess
import sys
from base64 import b64encode
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest

from cli import FactoryClient, ClientError, app_kind, default_url

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def api():
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def respond(self):
            raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            body = json.loads(raw) if raw else None
            requests.append(
                (
                    self.command,
                    self.path,
                    body,
                    self.headers.get("Authorization"),
                    self.headers.get("X-Operation-Confirmation"),
                )
            )
            status = 200
            if self.path == "/api/info":
                response = {"kind": self.server.kind}
            elif self.path == "/openapi.json":
                response = (
                    {"paths": {"/api/operations/plan": {"post": {}}}}
                    if self.server.has_plan
                    else {"paths": {}}
                )
            elif self.path == "/api/preview":
                response = {"records": [{"row": 1}], "writes": False}
            elif self.path == "/api/presets":
                response = {"presets": [{"id": "demo", "spec": {"name": "sample"}}]}
            elif self.path == "/api/presets/demo/export":
                response = {"name": "sample"}
            elif self.path == "/api/operations/plan":
                self.server.on_plan()
                response = {
                    "confirmation_token": self.server.plan_token,
                    "operation": "begin",
                }
            elif self.path.startswith("/api/operations/other"):
                self.send_response(302)
                self.send_header("Location", "/unregistered-destination")
                self.end_headers()
                return
            elif self.path in {
                "/api/start?profile_revision=2",
                "/api/runs",
                "/api/start",
                "/api/stop",
            }:
                self.server.on_start()
                status = self.server.start_code
                response = {
                    "status": "running",
                    "secret": "test-private",
                    "error_message": "test-private",
                }
            elif self.path == "/api/state":
                response = {
                    "status": "idle",
                    "tick": 2,
                    "spec": {"private": "test-private"},
                }
            else:
                status, response = (
                    422,
                    {
                        "detail": [
                            {
                                "location": "rows",
                                "msg": "行数を確認してください",
                                "input": "test-private",
                            }
                        ]
                    },
                )
            data = json.dumps(response).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        do_GET = do_POST = respond

        def log_message(self, *_args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        server.kind = app_kind()
        server.has_plan = True
        server.plan_token = "test-confirmation"
        server.start_code = 200
        server.on_plan = server.on_start = lambda: None
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield server, f"http://127.0.0.1:{server.server_port}", requests
        finally:
            server.shutdown()
            thread.join(timeout=5)


def run_cli(*arguments, input=None):
    """実際のコマンドを隔離した環境変数で実行する。"""
    env = {
        k: v
        for k, v in os.environ.items()
        if k
        not in {
            "ADMIN_USERNAME",
            "ADMIN_PASSWORD_FILE",
            "APP_PASSWORD_FILE",
            "APP_PORT",
        }
    }
    return subprocess.run(
        [sys.executable, str(ROOT / "cli.py"), *map(str, arguments)],
        input=input,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
        env=env,
    )


def test_cli_plan_and_run(api, tmp_path):
    _, url, requests = api
    token = tmp_path / "confirmation"
    args = ("--url", url, "--confirmation-file", token)
    planned = run_cli("plan", *args)
    assert planned.returncode == 0, planned.stderr
    assert json.loads(planned.stdout) == {
        "operation": "begin",
        "confirmation_saved": True,
    }
    assert token.read_text(encoding="utf-8") == "test-confirmation\n"
    if os.name == "posix":
        assert token.stat().st_mode & 0o777 == 0o600
    kind = app_kind()
    path = "/api/runs" if kind in {"sql", "files", "stream"} else "/api/start"
    assert requests[-1] == (
        "POST",
        "/api/operations/plan",
        {"path": path, "payload": {}, "force_confirmation": True},
        None,
        None,
    )
    executed = run_cli("start", *args)
    assert executed.returncode == 0, executed.stderr
    assert requests[-1] == ("POST", path, {}, None, "test-confirmation")
    assert run_cli("plan", *args).returncode == 2
    assert [r[1] for r in requests].count("/api/operations/plan") == 1


def test_cli_export_and_offline_validation(api):
    _, url, requests = api
    exported = run_cli("export", "--url", url, "--preset-id", "demo")
    assert exported.returncode == 0, exported.stderr
    assert json.loads(exported.stdout) == {"name": "sample"}
    invalid = run_cli("validate", "-", input='{"bad":')
    assert invalid.returncode == 1 and "JSONの構文" in invalid.stderr
    assert len(requests) == 1


def test_target_and_redirect_safety(api, tmp_path, monkeypatch):
    _, url, requests = api
    kind = app_kind()
    monkeypatch.setenv("APP_PORT", "5678")
    assert default_url(kind) == "http://127.0.0.1:5678"
    with pytest.raises(ClientError, match="HTTPS"):
        FactoryClient(kind, "http://192.0.2.5:8080", "admin", tmp_path / "password")
    for bad in (
        "https://user:password@localhost",
        "http://localhost/../unsafe",
        "http://localhost/?url=x",
    ):
        with pytest.raises(ClientError):
            FactoryClient(kind, bad)
    with pytest.raises(ClientError, match="リダイレクト"):
        FactoryClient(kind, url).request("/api/operations/other")
    assert [r[1] for r in requests] == ["/api/operations/other"]


def test_mcp_stdio_and_mutation_boundaries(api, tmp_path):
    server, url, requests = api
    server.kind = "logs"
    password = tmp_path / "password"
    password.write_text("synthetic\n", encoding="utf-8")
    confirmation = tmp_path / "token"
    confirmation.write_text("test-confirmation\n", encoding="utf-8")
    confirmation.chmod(0o600)
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "apps": {
                    "logs": {
                        "url": url,
                        "admin_username": "test",
                        "admin_password_file": password.name,
                        "confirmation_file": confirmation.name,
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    def rpc(i, method, params=None):
        message = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        if i is not None:
            message["id"] = i
        return message

    def call(i, tool, **args):
        return rpc(
            i, "tools/call", {"name": tool, "arguments": {"app": "logs", **args}}
        )

    messages = [
        rpc(1, "initialize", {"protocolVersion": "2025-11-25", "capabilities": {}}),
        rpc(None, "notifications/initialized"),
        rpc(2, "tools/list"),
        call(3, "start", spec={}),
        call(4, "validate_template", spec={}),
        call(5, "get_status"),
        call(6, "stop", execute=False),
        call(7, "start", spec={}, execute=True, profile_revision=2),
        call(8, "start", spec={}, execute=True, url="https://example.org"),
        call(9, "stop", execute=True),
        call(10, "list_presets"),
        call(11, "get_preset", preset_id="demo"),
    ]
    completed = subprocess.run(
        [sys.executable, str(ROOT / "mcp_server.py"), "--config", str(config)],
        input="".join(json.dumps(x) + "\n" for x in messages),
        text=True,
        capture_output=True,
        timeout=25,
        check=True,
    )
    responses = {r["id"]: r for r in map(json.loads, completed.stdout.splitlines())}
    assert sorted(responses) == list(range(1, 12))
    assert responses[1]["result"]["protocolVersion"] == "2025-11-25"
    tools = responses[2]["result"]["tools"]
    assert all(t["inputSchema"]["properties"]["app"]["enum"] == ["logs"] for t in tools)
    assert responses[3]["result"]["structuredContent"]["writes"] is False
    assert responses[4]["result"]["structuredContent"] == {"valid": True}
    assert responses[5]["result"]["structuredContent"] == {"status": "idle", "tick": 2}
    assert responses[6]["result"]["isError"] is True
    assert responses[7]["result"]["structuredContent"] == {"status": "running"}
    assert responses[8]["error"]["code"] == -32602
    assert responses[9]["result"]["isError"] is False
    assert responses[10]["result"]["structuredContent"] == {
        "presets": [{"id": "demo", "name": "sample"}]
    }
    assert responses[11]["result"]["structuredContent"] == {"name": "sample"}
    seen = [(method, path, token) for method, path, _, _, token in requests]
    assert seen == [
        ("POST", "/api/preview", None),
        ("POST", "/api/preview", None),
        ("GET", "/api/state", None),
        ("GET", "/api/info", None),
        ("GET", "/openapi.json", None),
        ("POST", "/api/start?profile_revision=2", "test-confirmation"),
        ("GET", "/api/info", None),
        ("POST", "/api/stop", None),
        ("GET", "/api/presets", None),
        ("GET", "/api/presets", None),
    ]
    assert all(
        r[3] == "Basic " + b64encode(b"test:synthetic").decode() for r in requests
    )
    assert (
        "synthetic" not in completed.stdout and "test-private" not in completed.stdout
    )
    assert "test-confirmation" not in completed.stdout
    assert not confirmation.exists()


def test_mcp_fails_closed_without_confirmation_api(api, tmp_path):
    from mcp_server import StdioServer

    server, url, requests = api
    server.kind = "logs"
    server.has_plan = False
    token = tmp_path / "confirmation"
    token.write_text("test-confirmation\n", encoding="utf-8")
    token.chmod(0o600)
    bridge = StdioServer({"logs": (FactoryClient("logs", url), token)})
    result = bridge.call_tool("start", {"app": "logs", "spec": {}, "execute": True})
    assert result["isError"] is True
    assert [r[1] for r in requests] == ["/api/info", "/openapi.json"]


def test_mcp_confirmed_start_can_be_reissued_at_same_path(api, tmp_path):
    from mcp_server import StdioServer

    server, url, requests = api
    app = app_kind()
    approval = tmp_path / "token"
    bridge = StdioServer({app: (FactoryClient(app, url), approval)})
    args = ("--url", url, "--confirmation-file", approval)
    call = {"app": app, "spec": {}, "execute": True}
    for token in ("test-first", "test-second"):
        server.plan_token = token
        planned = run_cli("plan", *args)
        assert planned.returncode == 0, planned.stderr
        assert token not in planned.stdout + planned.stderr
        assert bridge.call_tool("start", call) == {"status": "running"}
        assert requests[-1][4] == token
        assert not approval.exists()
    request_count = len(requests)
    refused = bridge.call_tool("start", call)
    assert refused["isError"]
    assert len(requests) == request_count


@pytest.mark.parametrize("status", [422, 428])
def test_mcp_rejected_start_keeps_approval_for_operator_to_replace(api, tmp_path, status):
    from mcp_server import StdioServer

    server, url, _ = api
    app = app_kind()
    approval = tmp_path / "token"
    args = ("--url", url, "--confirmation-file", approval)
    bridge = StdioServer({app: (FactoryClient(app, url), approval)})
    call = {"app": app, "spec": {}, "execute": True}
    assert run_cli("plan", *args).returncode == 0

    server.start_code = status
    result = bridge.call_tool("start", call)
    assert result["isError"] and result["structuredContent"]["status"] == status
    assert approval.read_text().strip() == "test-confirmation"

    server.plan_token = "new-confirmation"
    replacement = run_cli("plan", "--replace", *args)
    assert replacement.returncode == 0, replacement.stderr
    assert server.plan_token not in replacement.stdout + replacement.stderr
    assert approval.read_text().strip() == server.plan_token
    if os.name == "posix":
        assert approval.stat().st_mode & 0o777 == 0o600


def test_approval_replaced_during_execution_or_planning_is_preserved(api, tmp_path):
    from mcp_server import StdioServer

    server, url, _ = api
    app = app_kind()
    approval = tmp_path / "token"
    args = ("--url", url, "--confirmation-file", approval)
    assert run_cli("plan", *args).returncode == 0

    def replace_file():
        replacement = tmp_path / "other"
        replacement.write_text("different-approval")
        replacement.chmod(0o600)
        replacement.replace(approval)

    server.on_start = replace_file
    bridge = StdioServer({app: (FactoryClient(app, url), approval)})
    assert bridge.call_tool("start", {"app": app, "spec": {}, "execute": True}) == {
        "status": "running"
    }
    assert approval.read_text() == "different-approval"

    server.on_plan = replace_file
    failed = run_cli("plan", "--replace", *args)
    assert failed.returncode == 2 and "変更されました" in failed.stderr
    assert approval.read_text() == "different-approval"
    assert not list(tmp_path.glob(".confirmation-*"))


def test_mcp_refuses_invalid_file_without_contacting_api(api, tmp_path):
    from mcp_server import StdioServer

    _, url, requests = api
    app = app_kind()
    target = tmp_path / "other"
    target.write_text("test-confirmation")
    target.chmod(0o600)
    approval = tmp_path / "token"
    try:
        approval.symlink_to(target)
    except OSError:
        pytest.skip("symlinks unavailable")
    bridge = StdioServer({app: (FactoryClient(app, url), approval)})
    result = bridge.call_tool("start", {"app": app, "spec": {}, "execute": True})
    assert result["isError"] and not requests
    failed = run_cli("plan", "--replace", "--url", url, "--confirmation-file", approval)
    assert failed.returncode == 2 and not requests
    assert approval.is_symlink()
    assert target.read_text() == "test-confirmation"
