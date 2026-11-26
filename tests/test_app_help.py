"""公開ヘルプとAPIが同期し、管理認証・検証の応答が安全なことを確認する。"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
KIND = json.loads((ROOT / "docs/help-site.json").read_text())["kind"]
JOB = KIND in {"files", "sql", "stream"}
METHODS = {"get", "post", "patch", "put", "delete"}


@pytest.fixture
def make_app(monkeypatch, tmp_path):
    """実行領域と認証をテストから明示的に設定する。"""
    for key in ("ADMIN_USERNAME", "ADMIN_PASSWORD_FILE"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("LANDING_DIR", str(tmp_path / "landing"))
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))

    def create():
        if not JOB:
            from studio import create_app

            return create_app(KIND)
        from factorylib import create_app

        if KIND == "files":
            import file_adapter as adapter
        elif KIND == "sql":
            import database as adapter
        else:
            import stream_adapter as adapter
        return create_app(KIND, "ヘルプ検証", adapter)

    return create


def test_local_help_swagger_and_examples(make_app):
    with TestClient(make_app()) as client:
        home = client.get("/")
        assert home.status_code == 200
        assert 'href="/help/"' in home.text
        for path in (
            "",
            "presets.html",
            "settings.html",
            "templates.html",
            "api.html",
            "glossary.html",
            "install.html",
            "ai.html",
            "catalog.html",
        ):
            response = client.get("/help/" + path)
            assert response.status_code == 200
            assert '<html lang="ja">' in response.text
        assert (
            client.get("/help/images/operation-guide.png").headers["content-type"]
            == "image/png"
        )
        document = client.get("/docs").text
        assert "/static/swagger/swagger-ui-bundle.js" in document
        assert "https://" not in document
        assert client.get("/static/swagger/swagger-ui-bundle.js").status_code == 200
        schema = client.get("/openapi.json").json()
        operations = [
            operation
            for methods in schema["paths"].values()
            for method, operation in methods.items()
            if method in METHODS
        ]
        assert all(
            op["description"] and op["summary"] and op["tags"] for op in operations
        )
        assert len({op["operationId"] for op in operations}) == len(operations)
        assert "/help" not in schema["paths"]
        starter = schema["paths"]["/api/preview"]["post"]["requestBody"]["content"][
            "application/json"
        ]["examples"]["beginner"]["value"]
        example = client.get(f"/help/examples/{KIND}-beginner.json").json()
        assert starter == example
        response = client.post("/api/preview", json=example)
        assert response.status_code == 200, response.text
        preview = response.json()
        assert preview["records"] and preview["writes"] is False
        assert len(json.dumps(preview["compact_spec"])) < len(
            json.dumps(preview["validated_spec"])
        )
        compact_preview = client.post(
            "/api/preview", json=preview["compact_spec"]
        ).json()
        assert compact_preview["validated_spec"] == preview["validated_spec"]


def test_management_auth_and_separate_source_scope(make_app, monkeypatch, tmp_path):
    secret = tmp_path / "management-password"
    secret.write_text("synthetic-test-password\n")
    monkeypatch.setenv("ADMIN_USERNAME", "operator")
    monkeypatch.setenv("ADMIN_PASSWORD_FILE", str(secret))
    with TestClient(make_app()) as client:
        assert client.get("/healthz").status_code == 200
        for path in ("/", "/docs", "/help/", "/openapi.json", "/api/info", "/metrics"):
            response = client.get(path)
            assert response.status_code == 401
            assert response.headers["WWW-Authenticate"].startswith("Basic ")
        assert client.post("/api/preview", json={}).status_code == 401
        assert client.post("/api/connection-files", json={}).status_code == 401
        assert client.get("/api/info", auth=("operator", "wrong")).status_code == 401
        auth = ("operator", "synthetic-test-password")
        assert client.get("/help/", auth=auth).status_code == 200
        schema = client.get("/openapi.json", auth=auth).json()
        assert schema["paths"]["/api/preview"]["post"]["security"] == [
            {"ManagementBasic": []}
        ]
        if JOB:
            assert client.get("/api/source").status_code == 401
        else:
            assert client.get("/source/events").status_code == 200
            assert "ManagementBasic" not in str(
                schema["paths"]["/source/events"]["get"]["security"]
            )


def test_validation_and_unexpected_response_do_not_echo_values(make_app):
    app = make_app()

    @app.get("/unstable-test")
    def error():
        raise RuntimeError("synthetic-value-must-not-be-exposed")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/api/preview",
            content='{"trailing":}',
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422
        assert response.json()["detail"][0]["location"] == "JSON構文"
        fields = {
            "fields": [
                {"name": "example", "min": "synthetic-value-must-not-be-exposed"}
            ]
        }
        response = client.post(
            "/api/preview", json=fields if JOB else {"generator": fields}
        )
        assert response.status_code == 422
        first = response.json()["detail"][0]
        assert "1番目" in first["location"] and "example" in first["location"]
        assert "minimum" in first["msg"]
        assert "synthetic-value-must-not-be-exposed" not in response.text
        unexpected = client.get("/unstable-test")
        assert unexpected.status_code == 500
        assert "サーバー内部" in unexpected.json()["detail"]
        assert "synthetic-value-must-not-be-exposed" not in unexpected.text
