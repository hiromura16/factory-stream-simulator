"""Exercise write confirmation against actual HTTP routes without an external destination."""

import importlib

from fastapi.testclient import TestClient

from test_app_help import KIND, make_app as make_app


def test_risky_operation_requires_exact_one_use_confirmation(make_app, monkeypatch):
    app = make_app()
    invoked = []
    path = "/api/start"
    profile_path = "/api/profiles"
    selected = "operation-test"
    if KIND in {"files", "sql", "stream"}:
        path = "/api/table/prepare" if KIND == "sql" else "/api/runs"
        profile_path = "/api/connections"
        payload = {"connection_id": selected}
        if KIND == "sql":
            profile = {"id": selected, "name": "Test SQLite", "kind": "sqlite", "database": "confirm-test.db"}
            adapter = importlib.import_module("database")
            def execute(connection, spec):
                invoked.append(spec.sql.table)
                return {"created": True}
            monkeypatch.setattr(adapter, "prepare_table", execute)
        else:
            profile = ({"id": selected, "name": "S3 test", "kind": "s3", "bucket": "example-bucket"} if KIND == "files"
                       else {"id": selected, "name": "HTTP test", "kind": "http", "url": "https://example.invalid/receiver"})
            def execute(spec):
                invoked.append(spec.connection_revision)
                return {"id": "operation-test"}
            monkeypatch.setattr(app.state.runtime, "start", execute)
    else:
        payload = {"profile_id": selected, "max_ticks": 1}
        profile = {"id": selected, "name": "Test source"}
        if KIND == "logs":
            profile.update(output="udp", host="example.invalid", port=514)
        if KIND == "identification":
            profile.update(output="http", url="https://example.invalid/receiver")
        def execute(spec, revision=None):
            invoked.append(revision)
            return {"status": "running"}
        monkeypatch.setattr(app.state.controller, "start", execute)

    with TestClient(app) as client:
        saved = client.post(profile_path, json=profile)
        assert saved.status_code < 300, saved.text
        rejected = client.post(path, json=payload)
        assert rejected.status_code == 428, rejected.text
        assert invoked == []

        planned = client.post("/api/operations/plan", json={"path": path, "payload": payload})
        assert planned.status_code == 200, planned.text
        answer = planned.json()
        assert answer["confirmation_required"]
        assert answer["summary"]["destination_id"] == selected
        assert invoked == []
        headers = {"X-Operation-Confirmation": answer["confirmation_token"]}
        extra = {"rows": 2} if "connection_id" in payload else {"max_ticks": 2}
        changed = client.post(path, json={**payload, **extra}, headers=headers)
        assert changed.status_code == 428, changed.text
        assert invoked == []

        success = client.post(path, json=payload, headers=headers)
        assert success.status_code in {200, 202}, success.text
        assert len(invoked) == 1
        assert client.post(path, json=payload, headers=headers).status_code == 428
        assert len(invoked) == 1

        older = client.post("/api/operations/plan", json={"path": path, "payload": payload}).json()
        new_profile = {**profile, "name": "Updated destination"}
        assert client.post(profile_path, json=new_profile).status_code < 300
        stale = client.post(path, json=payload, headers={"X-Operation-Confirmation": older["confirmation_token"]})
        assert stale.status_code == 428, stale.text
        assert len(invoked) == 1

        api = client.get("/openapi.json").json()
        assert "428" in api["paths"][path]["post"]["responses"]
        assert all(
            api["components"]["schemas"]["FieldRule"]["properties"][key]["description"]
            for key in ("name", "data_type", "generator", "start")
        )


def confirmed_post(client, path, *, json, headers=None):
    '''Execute a test operation after approving the same settings.'''
    from urllib.parse import parse_qs, urlsplit

    response = client.post(path, json=json, headers=headers)
    if response.status_code != 428:
        return response
    parsed = urlsplit(path)
    plan = {"path": parsed.path, "payload": json}
    revisions = parse_qs(parsed.query).get("profile_revision")
    if revisions:
        plan["profile_revision"] = int(revisions[0])
    approval = client.post("/api/operations/plan", json=plan)
    assert approval.status_code == 200, approval.text
    token = approval.json()["confirmation_token"]
    return client.post(path, json=json, headers={**(headers or {}), "X-Operation-Confirmation": token})
