"""外部ブローカーを使わず、プレビューと合成MQTT送信の一致を確かめる。"""

import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

import stream_adapter
from config import RunSpec
from factorylib import create_app
from helptext import annotated_schemas


def test_mqtt_preview_matches_simulated_delivery_and_does_not_send(monkeypatch):
    """プレビュー時は未送信、実行時は同じ本文・トピックが出る。"""
    sent = []

    class FakeSender:
        """実ブローカーに通信せず、送信アダプターが受け取ったメッセージを記録する。"""

        def __init__(self, profile):
            """明示選択したMQTTプロファイルだけが使われる。"""
            assert profile.id == "synthetic"

        def send(self, entries):
            """配送前に固定された本文を隔離したリストへ保存する。"""
            sent.extend(entries)

        def close(self):
            """ネットワークハンドルは作らないので閉じる処理は不要。"""

    monkeypatch.setattr(stream_adapter, "Sender", FakeSender)
    app = create_app("stream", "Test", stream_adapter)
    with TestClient(app) as client:
        saved = client.post(
            "/api/connections",
            json={
                "id": "synthetic",
                "name": "合成MQTT",
                "kind": "mqtt",
                "host": "127.0.0.1",
                "topic": "synthetic/events",
                "ssl_mode": "off",
            },
        )
        assert saved.status_code == 200, saved.text
        spec = RunSpec(
            connection_id="synthetic",
            run_key="synthetic-preview",
            rows=2,
            target_rate=0,
            parameters={"label": "温度"},
            fields=[{"name": "label", "generator": "constant", "value": "$label"}],
            stream={"message_size_bytes": 256, "duplicate_rate": 1},
        ).model_dump(mode="json")

        response = client.post("/api/preview", json=spec)
        assert response.status_code == 200, response.text
        preview = response.json()
        assert preview["writes"] is False and not sent
        assert client.get("/api/runs").json()["runs"] == []
        messages = preview["stream_messages"]
        assert len(messages) == 2
        assert all(item["bytes"] == 256 and item["duplicate"] for item in messages)
        assert json.loads(messages[0]["payload"])["label"] == "温度"

        accepted = client.post("/api/runs", json=spec)
        assert accepted.status_code == 202, accepted.text
        run_id = accepted.json()["id"]
        for _ in range(100):
            job = client.get(f"/api/runs/{run_id}").json()
            if job["status"] not in {"queued", "running"}:
                break
            time.sleep(0.01)
        assert job["status"] == "completed", job
        assert [(item["topic"], item["payload"]) for item in sent] == [
            (msg["topic"], msg["payload"]) for msg in messages for _ in range(2)
        ]
        assert len({item["record_key"] for item in sent}) == 4
        assert json.loads(sent[0]["payload"]) == json.loads(sent[1]["payload"])


def test_stream_schema_keeps_opt_in_defaults():
    """従来のプリセットはサイズ・重複を指定しない場合と同じ。"""
    spec = RunSpec.model_validate_json(Path("presets/01-quickstart.json").read_text())
    assert spec.stream.duplicate_rate == 0
    assert spec.stream.message_size_bytes == 0
    schema = json.loads(Path("contracts/preset.schema.json").read_text())
    assert (
        schema["$defs"]["StreamOptions"]
        == annotated_schemas()["run"]["$defs"]["StreamOptions"]
    )


def test_malformed_mqtt_topic_never_looks_ready(monkeypatch):
    """送信不能なワイルドカードを、接続なしの確認でも拒否する。"""

    def unexpected_send(_profile):
        """プレビューは送信クライアントを構築しない。"""
        raise AssertionError("プレビューが送信しようとしました")

    monkeypatch.setattr(stream_adapter, "Sender", unexpected_send)
    app = create_app("stream", "Test", stream_adapter)
    with TestClient(app) as client:
        stored = client.post(
            "/api/connections",
            json={
                "id": "synthetic",
                "name": "合成MQTT",
                "kind": "mqtt",
                "host": "127.0.0.1",
                "topic": "synthetic/events",
                "ssl_mode": "off",
            },
        )
        assert stored.status_code == 200
        spec = RunSpec(connection_id="synthetic", stream={"topic_template": "bad/+"})
        response = client.post("/api/preview", json=spec.model_dump(mode="json"))
        assert response.status_code == 422
        assert client.get("/api/runs").json()["runs"] == []


def test_preview_then_same_id_edit_requires_review_and_does_not_redirect(monkeypatch):
    """同じ接続IDでも接続先が変わった実行は受付前に拒否する。"""
    sent_profiles = []

    class FakeSender:
        """実ブローカーに接続せず、確定した接続先を観測する。"""

        def __init__(self, profile):
            """送信された版のホストとトピックだけを観測する。"""
            sent_profiles.append((profile.host, profile.topic))

        def send(self, _entries):
            """MQTT通信の代わりに何もしない。"""

        def close(self):
            """通信ハンドルは作らない。"""

    monkeypatch.setattr(stream_adapter, "Sender", FakeSender)
    app = create_app("stream", "Test", stream_adapter)
    with TestClient(app) as client:
        profile = {
            "id": "synthetic",
            "name": "合成MQTT",
            "kind": "mqtt",
            "host": "127.0.0.1",
            "topic": "synthetic/old",
            "ssl_mode": "off",
        }
        assert client.post("/api/connections", json=profile).json()["revision"] == 1
        spec = RunSpec(
            connection_id="synthetic", connection_revision=1, rows=1, target_rate=0
        ).model_dump(mode="json")
        headers = {"X-Expected-Connection-Revision": "1"}
        preview = client.post("/api/preview", json=spec, headers=headers).json()
        assert preview["stream_messages"][0]["topic"] == "synthetic/old"
        assert preview["connection_revision"] == 1

        updated = {**profile, "host": "127.0.0.2", "topic": "synthetic/new"}
        assert client.post("/api/connections", json=updated).json()["revision"] == 2
        for path in ["/api/runs", "/api/preview"]:
            assert client.post(path, json=spec, headers=headers).status_code == 409
        assert not sent_profiles and client.get("/api/runs").json()["runs"] == []

        # 明示的な再プレビューが新しい版を表示した後にだけ新しい版で開始する。
        current = {**spec, "connection_revision": 2, "run_key": "reviewed-current"}
        current_headers = {"X-Expected-Connection-Revision": "2"}
        response = client.post("/api/preview", json=current, headers=current_headers)
        assert response.status_code == 200
        assert response.json()["stream_messages"][0]["topic"] == "synthetic/new"
        assert response.json()["connection_revision"] == 2
        assert not sent_profiles

        def assert_completed(response, revision):
            """同じ接続先の版でジョブが完了したことをAPIで確認する。"""
            assert response.status_code == 202, response.text
            run_id = response.json()["id"]
            for _ in range(100):
                job = client.get(f"/api/runs/{run_id}").json()
                if job["status"] not in {"queued", "running"}:
                    break
                time.sleep(0.01)
            assert job["status"] == "completed", job
            assert job["spec"]["connection_revision"] == revision

        assert_completed(
            client.post("/api/runs", json=current, headers=current_headers), 2
        )
        assert sent_profiles == [("127.0.0.2", "synthetic/new")]
        # CLI/APIは従来どおり、ヘッダーなしの歴史的な版を明示利用できる。
        assert_completed(client.post("/api/runs", json=spec), 1)
        assert sent_profiles[-1] == ("127.0.0.1", "synthetic/old")
