"""プリセット編集の公開APIと既存一覧の互換性を検証する。"""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
import runpy

import pytest
from fastapi.testclient import TestClient

EDITOR = "/api/preset-editor"
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def client(monkeypatch, tmp_path):
    """テスト用データでアプリを起動し、公開やバックグラウンド実行を開始しない。"""
    for key in (
        "ADMIN_USERNAME", "ADMIN_PASSWORD_FILE", "AUTO_START", "PROFILE_KEY_FILE",
        "SQL_HOST", "MQTT_HOST", "FILE_ALLOWED_ROOTS", "SQLITE_ROOT",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("LANDING_DIR", str(tmp_path / "landing"))
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("MIN_AVAILABLE_GIB", "0")
    app = runpy.run_path(str(ROOT / "app.py"))["app"]
    with TestClient(app) as session:
        yield session


def get(client, path):
    result = client.get(path)
    assert result.status_code == 200, result.text
    return result.json()


@pytest.fixture
def bundled(client):
    presets = get(client, EDITOR)["presets"]
    assert presets
    assert all(item["source"] == "bundled" and "spec" not in item for item in presets)
    return get(client, f"{EDITOR}/{presets[0]['id']}")


def match(item):
    return {"If-Match": f'"{item["revision"]}"'}


def draft(item, name):
    return {"spec": {**item["spec"], "name": name}, "tags": ["検証", "取り込み"]}


def create(client, item, identity="editor-test"):
    result = client.post(EDITOR, json={"id": identity, **draft(item, "保存例")})
    assert result.status_code == 201, result.text
    return result.json()


def test_save_as_rename_and_legacy_read(client, bundled):
    item = create(client, bundled)
    assert item["source"] == "user" and item["tags"] == ["検証", "取り込み"]
    path = f"{EDITOR}/{item['id']}"
    assert get(client, path) == item
    duplicate = client.post(EDITOR, json={"id": item["id"], **draft(item, "置換禁止")})
    assert duplicate.status_code == 409
    assert get(client, path) == item
    payload = draft(item, "新しい表示名")
    assert client.put(path, json=payload).status_code == 428
    updated = client.put(path, json=payload, headers=match(item))
    assert updated.status_code == 200, updated.text
    renamed = updated.json()
    assert renamed["id"] == item["id"]
    assert renamed["name"] == renamed["spec"]["name"] == "新しい表示名"
    assert renamed["revision"] != item["revision"]
    assert client.put(path, json=payload, headers=match(item)).status_code == 412
    assert get(client, path) == renamed
    legacy = get(client, "/api/presets")["presets"]
    assert next(entry for entry in legacy if entry["id"] == item["id"])["spec"]["name"] == renamed["name"]
    assert get(client, f"{EDITOR}/{bundled['id']}") == bundled


def test_bundled_preset_is_protected(client, bundled):
    identity = bundled["id"]
    path = f"{EDITOR}/{identity}"
    payload = draft(bundled, "上書き禁止")
    assert client.post(EDITOR, json={"id": identity, **payload}).status_code == 403
    assert client.put(path, json=payload, headers=match(bundled)).status_code == 403
    assert client.delete(path, headers=match(bundled)).status_code == 403
    assert client.post(f"/api/presets/{identity}", json=payload["spec"]).status_code == 403
    assert get(client, path) == bundled


def test_delete_requires_current_revision_and_only_removes_selected_preset(client, bundled):
    original = create(client, bundled)
    other = create(client, bundled, "editor-other")
    path = f"{EDITOR}/{original['id']}"
    update = client.put(path, json=draft(original, "新しい版"), headers=match(original))
    assert update.status_code == 200, update.text
    current = update.json()
    legacy_paths = ("/api/connections", "/api/runs") if (ROOT / "factorylib.py").exists() else ("/api/profiles", "/api/state")
    before = {path: get(client, path) for path in legacy_paths}
    assert client.delete(path).status_code == 428
    assert client.delete(path, headers=match(original)).status_code == 412
    assert client.delete(path, headers={**match(current), "Origin": "https://another.invalid"}).status_code == 403
    assert get(client, path) == current
    deleted = client.delete(path, headers=match(current))
    assert deleted.status_code == 200, deleted.text
    assert deleted.json() == {"id": original["id"], "deleted": True}
    assert client.get(path).status_code == 404
    assert get(client, f"{EDITOR}/{other['id']}") == other
    assert get(client, f"{EDITOR}/{bundled['id']}") == bundled
    assert original["id"] not in {entry["id"] for entry in get(client, "/api/presets")["presets"]}
    assert before == {path: get(client, path) for path in legacy_paths}


def test_concurrent_updates_on_same_revision_allow_one_write(client, bundled):
    item = create(client, bundled)
    path = f"{EDITOR}/{item['id']}"

    def change(name):
        return client.put(path, json=draft(item, name), headers=match(item))

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(change, ("変更その1", "変更その2")))
    assert sorted(response.status_code for response in responses) == [200, 412]
    saved = next(response.json() for response in responses if response.status_code == 200)
    assert get(client, path) == saved


def test_validation_and_preview_do_not_save_or_run(client, bundled):
    before = get(client, EDITOR)
    validation = client.post(f"{EDITOR}/validate", json=draft(bundled, "編集中"))
    assert validation.status_code == 200, validation.text
    result = client.post("/api/preview", json=validation.json()["spec"])
    assert result.status_code == 200, result.text
    assert result.json()["writes"] is False
    assert get(client, EDITOR) == before
    if (ROOT / "factorylib.py").exists():
        assert not get(client, "/api/runs")["runs"]
    else:
        assert get(client, "/api/state")["status"] != "running"


@pytest.mark.parametrize("key", ["password", "access_key", "db_access_token"])
def test_reject_secret_bearing_documents_without_echoing_values(client, bundled, key):
    preset = deepcopy(bundled["spec"])
    parameters = preset.get("generator", preset).setdefault("parameters", {})
    marker = "fixture-secret-value-should-not-return"
    parameters["unsafe_test_case"] = [{key: marker}]
    payload = {"spec": preset}
    for path, body in (
        (f"{EDITOR}/validate", payload),
        (EDITOR, {"id": "must-not-save", **payload}),
        ("/api/presets/must-not-save", preset),
    ):
        result = client.post(path, json=body)
        assert result.status_code == 422, result.text
        assert marker not in result.text
    assert client.get(f"{EDITOR}/must-not-save").status_code == 404
