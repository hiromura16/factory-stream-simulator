# モジュール読解: ループバック受信器と一時アウトボックスで配送エラーおよび再送時の状態遷移を試験する。
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from config import ConnectionProfile, RunSpec
from generation import GenerationError
from stream_adapter import fingerprint, handle, retry, summary
from conftest import Context


# 読解 receiver: 空きポートで試験用受信器を起動し、終了時にサーバーとスレッドを片付ける。
@pytest.fixture
def receiver():
    # 読解 receiver.Handler: 受け取った本文を記録し、切替可能な成功・失敗応答で送信側の挙動を検証する。
    class Handler(BaseHTTPRequestHandler):
        seen = []
        fail = True

        # 読解 receiver.Handler.log_message: 試験用サーバーのアクセスログを出力しない。
        def log_message(self, *args):
            pass

        # 読解 receiver.Handler.do_HEAD: 疎通確認に本文なしで成功を返す。
        def do_HEAD(self):
            self.send_response(200)
            self.end_headers()

        # 読解 receiver.Handler.do_PUT: 受信ヘッダーとJSONを保存し、失敗モードなら503、通常なら202を返す。
        def do_PUT(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            self.seen.append((dict(self.headers), json.loads(body)))
            self.send_response(503 if self.fail else 202)
            self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server, Handler
    server.shutdown()
    server.server_close()
    thread.join()


# 読解 test_failed_delivery_persists_and_retry_is_destination_bound: 配送失敗を保存し、違う宛先を排除した上で元宛先への再送と完了状態を検証する。
def test_failed_delivery_persists_and_retry_is_destination_bound(receiver):
    server, handler = receiver
    profile = ConnectionProfile(
        id="http",
        name="HTTP",
        kind="http",
        url=f"http://127.0.0.1:{server.server_port}/events",
        ssl_mode="off",
        http_method="PUT",
        auth_mode="bearer",
        bearer_token="test-token",
        headers={"X-Custom": "test-header"},
    )
    spec = RunSpec(rows=3, batch_size=3, target_rate=0)
    spec.stream.payload_template = {"device": "$row.entity_id", "value": "$row.value"}
    with pytest.raises(Exception):
        handle(spec, Context(), profile, None)
    assert summary()["counts"]["pending"] == 3
    other = profile.model_copy(update={"url": profile.url + "/other"})
    handler.fail = False
    ctx = Context()
    retry(spec, ctx, other, None)
    assert not ctx.stats
    ctx = Context()
    retry(spec, ctx, profile, None)
    assert ctx.stats["delivered"] == 3
    assert summary()["counts"]["delivered"] == 3
    headers, payload = handler.seen[-1]
    assert (
        headers["Authorization"] == "Bearer test-token"
        and headers["X-Custom"] == "test-header"
    )
    assert "device" in payload[0] and payload[0]["_source"]["record_key"]
    ctx = Context()
    handle(spec, ctx, profile, None)
    assert ctx.stats.get("enqueued") == 0 and ctx.stats.get("delivered", 0) == 0


# 読解 test_same_identity_cannot_change_payload_and_capture_retains_pending: 記録専用の未配送状態を確かめ、同一識別子に異なる内容を上書きできないことを検証する。
def test_same_identity_cannot_change_payload_and_capture_retains_pending():
    p = ConnectionProfile(id="capture", name="capture", kind="capture")
    spec = RunSpec(rows=5, target_rate=0, batch_size=2)
    handle(spec, Context(), p, None)
    assert summary()["counts"]["pending"] == 5
    spec.fields[5].mean = 999
    with pytest.raises(GenerationError):
        handle(spec, Context(), p, None)
    with pytest.raises(GenerationError):
        retry(spec, Context(), p, None)


# 読解 test_target_fingerprint_changes_with_destination_and_method: HTTPメソッド変更は宛先識別を変え、パスワード変更だけなら識別を変えないことを確かめる。
def test_target_fingerprint_changes_with_destination_and_method():
    p = ConnectionProfile(
        id="p", name="p", kind="http", url="https://example.test/events"
    )
    assert fingerprint(p) != fingerprint(p.model_copy(update={"http_method": "PUT"}))
    assert fingerprint(p) == fingerprint(p.model_copy(update={"password": "changed"}))


# 読解 test_preview_and_delivery_payload_metadata_cannot_overwrite_user_fields: 本文とメタデータの同名キーを検出し、包み込み無効時には利用者の値を保持することを検証する。
def test_preview_and_delivery_payload_metadata_cannot_overwrite_user_fields():
    from generation import generate_record, stream_payload

    spec = RunSpec()
    row = generate_record(spec, 0)
    payload = stream_payload(spec, row, 0)
    assert payload["_source"]["record_key"] == row["id"]
    spec.stream.payload_template = {"_source": "would-be-overwritten"}
    with pytest.raises(GenerationError, match="重複"):
        stream_payload(spec, row, 0)
    spec.stream.envelope = False
    assert stream_payload(spec, row, 0) == {"_source": "would-be-overwritten"}


# 読解 test_ack_loss_retains_pending_and_transient_failure_retries: 送信後の確認失敗を未配送のまま残し、同じ本文の再試行と一時的障害後の回復を確かめる。
def test_ack_loss_retains_pending_and_transient_failure_retries(receiver):
    from config import FaultOptions
    from factorylib import Runtime

    server, handler = receiver
    handler.fail = False
    p = ConnectionProfile(
        id="http",
        name="HTTP",
        kind="http",
        url=f"http://127.0.0.1:{server.server_port}/events",
        ssl_mode="off",
        http_method="PUT",
    )
    spec = RunSpec(
        rows=3,
        batch_size=3,
        target_rate=0,
        faults=FaultOptions(enabled=True, stage="after_write", action="fail"),
    )
    # コールバック: テスト専用プロファイルを閉じ込め、Runtimeが渡すspec/contextを実アダプターへ中継する。
    runtime = Runtime("stream", lambda s, c: handle(s, c, p, None), 100000000)
    job = runtime.start(spec)
    runtime.thread.join(timeout=5)
    assert (
        runtime.get(job["id"])["status"] == "failed"
        and summary()["counts"]["pending"] == 3
        and len(handler.seen) == 1
    )
    retry_spec = RunSpec(rows=3, batch_size=3, target_rate=0)
    retry(retry_spec, Context(), p, None)
    assert summary()["counts"]["delivered"] == 3 and len(handler.seen) == 2
    assert handler.seen[0][1] == handler.seen[1][1]
    spec.run_key = "transient-retry"
    spec.faults = FaultOptions(enabled=True, stage="before_batch", action="fail")
    spec.stream.delivery_attempts = 3
    spec.stream.retry_backoff_ms = 0
    job = runtime.start(spec)
    runtime.thread.join(timeout=5)
    result = runtime.get(job["id"])
    assert result["status"] == "completed" and result["stats"]["delivered"] == 3
