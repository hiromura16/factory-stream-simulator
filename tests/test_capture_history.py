"""ローカル記録のHTTP閲覧で外部配送の本文を公開しないことを検証する。"""

import json

import stream_adapter
from config import ConnectionProfile
from factorylib import create_app
from fastapi.testclient import TestClient


def test_capture_pagination_and_download_only_include_archived_capture_versions():
    app = create_app("stream", "capture test", stream_adapter)
    store = app.state.config_store
    local = ConnectionProfile(
        id="mixed", name="記録", kind="capture", topic="local/events"
    )
    external = ConnectionProfile(
        id="mixed", name="外部", kind="http", url="https://example.test/receive"
    )
    store.save_profile(local)
    stream_adapter.enqueue(
        local,
        [
            {
                "record_key": "record-a",
                "payload": '{"event":"温度"}  ',
                "topic": "local/events",
                "body_mode": "bare",
            }
        ],
    )
    store.save_profile(external)
    stream_adapter.enqueue(
        external,
        [
            {
                "record_key": "external-secret-example",
                "payload": '{"private":"external"}',
                "topic": "outside",
                "body_mode": "bare",
            }
        ],
    )
    stream_adapter.enqueue(
        local,
        [
            {
                "record_key": "record-b",
                "payload": '{"event":"警報"}',
                "topic": "local/events",
                "body_mode": "bare",
            }
        ],
    )
    with TestClient(app) as client:
        first = client.get("/api/outbox/capture", params={"limit": 1}).json()
        assert first["events"][0]["record_key"] == "record-b"
        assert "payload" not in first["events"][0]
        assert "target" not in first["events"][0]
        upper = first["next_before"]
        second = client.get(
            "/api/outbox/capture", params={"limit": 1, "before": upper}
        ).json()
        item = second["events"][0]
        assert item["record_key"] == "record-a" and second["next_before"] is None
        record = client.get(f"/api/outbox/capture/{item['id']}").json()
        assert record["payload"] == '{"event":"温度"}  '
        assert record["bytes"] == len(record["payload"].encode("utf-8"))
        assert client.get(f"/api/outbox/capture/{item['id'] + 1}").status_code == 404

        download = client.get("/api/outbox/capture/download")
        assert download.headers["content-type"] == "application/x-ndjson"
        assert (
            download.headers["content-disposition"]
            == 'attachment; filename="stream-capture.jsonl"'
        )
        assert download.text.endswith("\n")
        records = [json.loads(line) for line in download.text.splitlines()]
        assert [row["record_key"] for row in records] == ["record-b", "record-a"]
        assert records[-1]["payload"] == record["payload"]
        assert "external" not in download.text
        assert (
            client.get("/api/outbox/capture", params={"before": str(2**63)}).status_code
            == 422
        )
        assert (
            client.get("/api/outbox/capture", params={"limit": 101}).status_code == 422
        )
        assert client.get(f"/api/outbox/capture/{2**63}").status_code == 422


def test_capture_empty_state():
    with TestClient(create_app("stream", "capture test", stream_adapter)) as client:
        assert client.get("/api/outbox/capture").json() == {
            "events": [],
            "next_before": None,
        }
        assert client.get("/api/outbox/capture/download").content == b""
        assert client.get("/api/outbox/capture/1").status_code == 404
