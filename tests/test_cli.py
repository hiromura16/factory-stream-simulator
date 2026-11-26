"""Exercise the CLI against a local HTTP server with synthetic credentials."""

import json
import os
import subprocess
import sys
from base64 import b64encode
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest


@pytest.mark.parametrize("mode", ["none", "admin", "legacy", "incomplete", "redirect"])
def test_cli_authentication(tmp_path, mode):
    requests = []

    class ApiHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append((self.path, self.headers.get("Authorization")))
            if mode == "redirect" and self.path == "/api/info":
                self.send_response(302)
                self.send_header("Location", "/other-path")
                self.end_headers()
                return
            body = json.dumps({"kind": "test"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"ADMIN_USERNAME", "ADMIN_PASSWORD_FILE", "APP_PASSWORD_FILE"}
    }
    env["NO_PROXY"] = env["no_proxy"] = "127.0.0.1"
    password_file = tmp_path / "test-password"
    password_file.write_text("synthetic-password\n", encoding="utf-8")
    username = None
    if mode in {"admin", "redirect"}:
        username = env["ADMIN_USERNAME"] = "sample-admin"
        env["ADMIN_PASSWORD_FILE"] = str(password_file)
        env["APP_PASSWORD_FILE"] = str(tmp_path / "unused-legacy-path")
    elif mode == "legacy":
        username = "operator"
        env["APP_PASSWORD_FILE"] = str(password_file)
    elif mode == "incomplete":
        env["ADMIN_USERNAME"] = "sample-admin"

    with ThreadingHTTPServer(("127.0.0.1", 0), ApiHandler) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            script = Path(__file__).resolve().parents[1] / "cli.py"
            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "info",
                    "--url",
                    f"http://127.0.0.1:{server.server_port}",
                ],
                env=env,
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        finally:
            server.shutdown()
            thread.join(timeout=5)

    if mode == "incomplete":
        assert result.returncode == 2 and "ADMIN_PASSWORD_FILE" in result.stderr
        assert requests == []
        return
    if mode == "redirect":
        assert result.returncode == 1 and "リダイレクト" in result.stderr
        assert [path for path, _ in requests] == ["/api/info"]
        return
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"kind": "test"}
    expected = (
        f"Basic {b64encode(f'{username}:synthetic-password'.encode()).decode()}"
        if username
        else None
    )
    expected_requests = [("/api/info", expected)]
    assert requests == expected_requests
