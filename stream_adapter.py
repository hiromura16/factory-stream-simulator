"""合成イベントを宛先にひも付けて保存し、記録専用モード以外は配送する。"""

from __future__ import annotations

import base64
import hashlib
import json
from itertools import groupby
import os
import sqlite3
import ssl
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import (
    HTTPRedirectHandler,
    HTTPSHandler,
    ProxyHandler,
    Request,
    build_opener,
)

from stream_connections import TRANSPORTS
from connection_security import tls_context
from generation import (
    GenerationError,
    batch_limit,
    generate_record,
    inject_fault,
)

from stream_events import build_events, check_stream_profile, check_stream_topic


@contextmanager
def outbox(*, check_same_thread=True):
    """送信待ち履歴のSQLiteを開き、トランザクション終了後に接続を閉じる。"""
    root = Path(os.environ.get("DATA_DIR", "./data"))
    root.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        root / "outbox.sqlite3", timeout=15, check_same_thread=check_same_thread
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS outbox_v2(profile_id TEXT NOT NULL,target TEXT NOT NULL,record_key TEXT NOT NULL,payload TEXT NOT NULL,topic TEXT NOT NULL,body_mode TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',attempts INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL,delivered_at TEXT,PRIMARY KEY(profile_id,target,record_key))"
    )
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def fingerprint(profile):
    """配送先の主要属性から照合値を作り、別宛先への誤再送を防ぐ。

    秘密値そのものは照合値に含めない。
    """
    target = {
        k: getattr(profile, k)
        for k in [
            "kind",
            "host",
            "port",
            "url",
            "topic",
            "username",
            "auth_mode",
            "api_key_header",
            "http_method",
            "content_type",
            "mqtt_version",
            "client_id",
            "retain",
            "bootstrap_servers",
            "kafka_sasl_mechanism",
            "amqp_virtual_host",
            "amqp_exchange",
            "nats_jetstream",
            "websocket_ack",
        ]
    }
    return hashlib.sha256(json.dumps(target, sort_keys=True).encode()).hexdigest()


class NoRedirect(HTTPRedirectHandler):
    """HTTP転送先へ送信を引き継がないハンドラー。"""
    def redirect_request(self, *args, **kwargs):
        """本文や認証情報を別の宛先へ送らないよう、転送を拒否する。"""
        return None


class Sender:
    """配送方式別のクライアントと送信処理をまとめる。"""
    def __init__(self, profile):
        """配送先に接続する。HTTP転送と環境プロキシは無効にし、MQTTは接続受理を待つ。"""
        self.profile, self.client = profile, None
        self.extra = None
        if profile.kind in TRANSPORTS:
            self.extra = TRANSPORTS[profile.kind](profile)
            return
        context = tls_context(profile)
        if profile.ssl_mode != "verify":
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        if profile.kind == "http":
            if profile.ssl_mode != "off" and profile.url.startswith("http:"):
                raise GenerationError("TLS有効時はHTTPSのURLを指定してください")
            self.opener = build_opener(
                ProxyHandler({}), HTTPSHandler(context=context), NoRedirect()
            )
            self.headers = {
                name: value.get_secret_value()
                for name, value in profile.headers.items()
                if value is not None
            }
            if profile.auth_mode == "basic":
                if not profile.password:
                    raise GenerationError("HTTP Basic認証のパスワードが必要です")
                self.headers["Authorization"] = (
                    "Basic "
                    + base64.b64encode(
                        (
                            profile.username + ":" + profile.password.get_secret_value()
                        ).encode()
                    ).decode()
                )
            elif profile.auth_mode == "bearer":
                if not profile.bearer_token:
                    raise GenerationError("Bearerトークンが必要です")
                self.headers["Authorization"] = (
                    "Bearer " + profile.bearer_token.get_secret_value()
                )
            elif profile.auth_mode == "api_key":
                if not profile.api_key:
                    raise GenerationError("APIキーが必要です")
                self.headers[profile.api_key_header] = (
                    profile.api_key.get_secret_value()
                )
        elif profile.kind == "mqtt":
            import paho.mqtt.client as mqtt

            connected = threading.Event()
            self.accepted = False
            self.client = mqtt.Client(
                mqtt.CallbackAPIVersion.VERSION2,
                client_id=profile.client_id or "source-" + os.urandom(8).hex(),
                protocol=mqtt.MQTTv5 if profile.mqtt_version == "5" else mqtt.MQTTv311,
            )
            self.client.connect_timeout = profile.timeout_seconds

            def on_connect(client, userdata, flags, reason, properties):
                self.accepted = reason == 0
                connected.set()

            self.client.on_connect = on_connect
            if profile.username:
                self.client.username_pw_set(
                    profile.username,
                    profile.password.get_secret_value() if profile.password else None,
                )
            if profile.ssl_mode != "off":
                self.client.tls_set_context(context)
            try:
                self.client.connect(
                    profile.host,
                    profile.port or (1883 if profile.ssl_mode == "off" else 8883),
                    profile.keepalive,
                )
                self.client.loop_start()
                if not connected.wait(profile.timeout_seconds) or not self.accepted:
                    raise ConnectionError("MQTT接続が受け付けられませんでした")
            except Exception:
                self.close()
                raise
        elif profile.kind != "capture":
            raise GenerationError("MQTT／HTTP／ローカル記録の接続先を指定してください")

    def send(self, entries):
        """アウトボックスの項目を送る。HTTPの混在形式は拒否し、MQTTは選んだQoSでの送信完了を待つ。"""
        if self.extra:
            return self.extra.send(entries)
        if not entries:
            return
        if self.profile.kind == "mqtt":
            pending = [
                self.client.publish(
                    entry["topic"],
                    entry["payload"],
                    qos=self.profile.qos,
                    retain=self.profile.retain,
                )
                for entry in entries
            ]
            for ack in pending:
                ack.wait_for_publish(timeout=self.profile.timeout_seconds)
                if not ack.is_published():
                    raise TimeoutError("MQTT送信の完了待ちがタイムアウトしました")
            return
        if self.profile.kind == "capture":
            return
        mode = entries[0]["body_mode"]
        if any(e["body_mode"] != mode for e in entries):
            raise GenerationError("異なるHTTP本文形式は分けて送信してください")
        groups = [[entry] for entry in entries] if mode == "single" else [entries]
        for group in groups:
            payloads = [json.loads(entry["payload"]) for entry in group]
            if mode == "ndjson":
                body = ("\n".join(entry["payload"] for entry in group) + "\n").encode()
                content_type = "application/x-ndjson"
            else:
                body = json.dumps(
                    payloads[0] if mode == "single" else payloads,
                    ensure_ascii=False,
                    allow_nan=False,
                ).encode()
                content_type = "application/json"
            request = Request(
                self.profile.url,
                data=body,
                headers={
                    **self.headers,
                    "Content-Type": self.profile.content_type or content_type,
                },
                method=self.profile.http_method,
            )
            with self.opener.open(
                request, timeout=self.profile.timeout_seconds
            ) as response:
                if response.status not in {200, 201, 202, 204}:
                    raise RuntimeError("HTTP受け付けに失敗しました")
                data = response.read(65536)
                if data:
                    try:
                        ack = json.loads(data)
                    except (ValueError, UnicodeError):
                        ack = {}
                    if isinstance(ack, dict) and (
                        ack.get("failed")
                        or ack.get("errors")
                        or ("accepted" in ack and ack["accepted"] != len(group))
                    ):
                        raise RuntimeError("HTTP受信先から一部失敗が返されました")

    def close(self):
        if self.extra:
            return self.extra.close()
        if self.client:
            self.client.disconnect()
            self.client.loop_stop()


def test_connection(profile):
    """本文を発行せずに疎通を確認する。HTTPでHEADが非対応でも到達は確認できる。"""
    sender = Sender(profile)
    try:
        if sender.extra:
            return sender.extra.test()
        if profile.kind == "http":
            request = Request(profile.url, headers=sender.headers, method="HEAD")
            try:
                with sender.opener.open(
                    request, timeout=profile.timeout_seconds
                ) as response:
                    status = response.status
            except HTTPError as exc:
                if exc.code != 405:
                    raise
                status = 405
            return {
                "status": "reachable",
                "http_status": status,
                "note": "本文は送信していません",
            }
        return {
            "status": "connected" if profile.kind == "mqtt" else "ready",
            "kind": profile.kind,
            "published": False,
        }
    finally:
        sender.close()


def enqueue(profile, entries):
    """宛先とレコード識別子に結び付けて送信待ちを保存する。

    同じ識別子で本文等が異なる場合は拒否する。既配送分は再送候補から除く。
    """
    target = fingerprint(profile)
    with outbox() as conn:
        placeholders = ",".join("?" for _ in entries)
        existing = {
            r["record_key"]: dict(r)
            for r in conn.execute(
                "SELECT * FROM outbox_v2 WHERE profile_id=? AND target=? AND record_key IN ("
                + placeholders
                + ")",
                [profile.id, target, *[e["record_key"] for e in entries]],
            )
        }
        for entry in entries:
            old = existing.get(entry["record_key"])
            if old and any(
                old[k] != entry[k] for k in ["payload", "topic", "body_mode"]
            ):
                raise GenerationError(
                    "同じ実行名とシーケンスに異なるデータがあります。実行名を変更してください"
                )
        at = datetime.now(timezone.utc).isoformat()
        conn.executemany(
            "INSERT OR IGNORE INTO outbox_v2(profile_id,target,record_key,payload,topic,body_mode,created_at) VALUES(?,?,?,?,?,?,?)",
            [
                (
                    profile.id,
                    target,
                    e["record_key"],
                    e["payload"],
                    e["topic"],
                    e["body_mode"],
                    at,
                )
                for e in entries
            ],
        )
    return len(entries) - len(existing), [
        e
        for e in entries
        if existing.get(e["record_key"], {}).get("status") != "delivered"
    ]


def deliver(profile, sender, entries, ctx, batch_number=1):
    """送信を試み、成功した項目を配送済みにする。失敗時は設定範囲で再試行する。

    送信先での受信と履歴更新は別操作であり、exactly-onceの保証ではない。
    """
    target = fingerprint(profile)
    for attempt in range(profile.delivery_attempts):
        ctx.check()
        with outbox() as conn:
            conn.executemany(
                "UPDATE outbox_v2 SET attempts=attempts+1 WHERE profile_id=? AND target=? AND record_key=?",
                [(profile.id, target, e["record_key"]) for e in entries],
            )
        try:
            inject_fault(ctx.spec, ctx, "before_batch", batch_number) if hasattr(
                ctx, "spec"
            ) else None
            sender.send(entries)
            inject_fault(ctx.spec, ctx, "after_write", batch_number) if hasattr(
                ctx, "spec"
            ) else None
        except Exception:
            if attempt + 1 >= profile.delivery_attempts:
                raise
            end = time.monotonic() + min(
                60, profile.retry_backoff_ms * 2**attempt / 1000
            )
            while time.monotonic() < end:
                ctx.check()
                ctx.wait(min(200, max(0, (end - time.monotonic()) * 1000)))
            continue
        with outbox() as conn:
            conn.executemany(
                "UPDATE outbox_v2 SET status='delivered',delivered_at=? WHERE profile_id=? AND target=? AND record_key=?",
                [
                    (
                        datetime.now(timezone.utc).isoformat(),
                        profile.id,
                        target,
                        e["record_key"],
                    )
                    for e in entries
                ],
            )
        return


def handle(spec, ctx, profile, store):
    """生成した本文を先に保存し、記録専用モード以外では配送する。"""
    check_stream_profile(spec, profile.kind)
    overrides = {
        name: getattr(spec.stream, name)
        for name in ["delivery_attempts", "retry_backoff_ms"]
        if getattr(spec.stream, name) is not None
    }
    if overrides:
        profile = profile.model_copy(update=overrides)
    sender = None
    size = 0
    paced = 0
    step = batch_limit(
        spec,
        min(spec.batch_size, spec.target_rate) if spec.target_rate else spec.batch_size,
        kind="stream",
    )
    if spec.stream.message_size_bytes:
        step = min(step, max(1, 4 * 1024 * 1024 // spec.stream.message_size_bytes))
    if spec.stream.duplicate_rate:
        step = max(1, step // 2)
    try:
        for offset in range(0, spec.rows, step):
            ctx.check()
            count = min(step, spec.rows - offset)
            entries = []
            for i in range(count):
                sequence = spec.start_sequence + offset + i
                row = generate_record(spec, sequence)
                events = build_events(spec, row, sequence, profile.topic)
                topic = events[0]["topic"]
                check_stream_topic(profile.kind, topic)
                entries.extend(events)
            size += sum(len(e["payload"].encode()) for e in entries)
            if size > spec.max_output_mb * 1024 * 1024:
                raise RuntimeError("run_size_limit")
            data = Path(os.environ.get("DATA_DIR", "./data"))
            if (
                sum(p.stat().st_size for p in data.glob("outbox.sqlite3*"))
                > int(os.environ.get("MAX_SPOOL_MB", "16384")) * 1024 * 1024
            ):
                raise RuntimeError("outbox_size_limit")
            fresh, pending = enqueue(profile, entries)
            ctx.progress(enqueued=fresh)
            if pending and profile.kind != "capture":
                if sender is None:
                    sender = Sender(profile)
                deliver(profile, sender, pending, ctx, offset // step + 1)
                ctx.progress(delivered=len(pending))
            if pending and profile.kind == "capture":
                inject_fault(spec, ctx, "before_batch", offset // step + 1)
                inject_fault(spec, ctx, "after_write", offset // step + 1)
            ctx.progress(
                processed=count,
                commits=1,
                bytes_written=sum(len(e["payload"].encode()) for e in entries),
            )
            paced += len(entries)
            if offset + count < spec.rows:
                ctx.pace(paced)
    finally:
        if sender:
            sender.close()


def summary():
    """送信状態の件数と直近100件を返す。旧形式の未送信件数も別に示す。"""
    with outbox() as conn:
        counts = {
            r[0]: r[1]
            for r in conn.execute(
                "SELECT status,count(*) FROM outbox_v2 GROUP BY status"
            )
        }
        legacy = (
            conn.execute(
                "SELECT count(*) FROM outbox WHERE state='pending'"
            ).fetchone()[0]
            if conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='outbox'"
            ).fetchone()
            else 0
        )
        return {
            "counts": counts,
            "legacy_pending": legacy,
            "events": [
                dict(r)
                for r in conn.execute(
                    "SELECT profile_id,record_key,status,attempts,created_at FROM outbox_v2 ORDER BY created_at DESC LIMIT 100"
                )
            ],
        }


def capture_rows(store, limit, *, before=None, row_id=None, include_payload=False):
    """記録専用の接続履歴に一致する保存行だけを、新しい順で取得する。

    SQLiteのstatusは配送待ちとローカル記録の区別に使えない。
    接続IDと宛先の照合値を両方検査し、同じ接続IDの外部配送データも除外する。
    """
    targets = sorted(
        {(profile.id, fingerprint(profile)) for profile in store.profile_versions_of_kind("capture")}
    )
    if not targets:
        return
    columns = "o.rowid AS id,o.profile_id,o.record_key,o.topic,o.created_at"
    columns += ",length(CAST(o.payload AS BLOB)) AS bytes"
    if include_payload:
        columns += ",o.payload"
    query = f"""
        SELECT {columns}
          FROM json_each(?) AS target
          JOIN outbox_v2 AS o
            ON o.profile_id=json_extract(target.value,'$[0]')
           AND o.target=json_extract(target.value,'$[1]')
    """
    args = [json.dumps(targets)]
    if row_id is not None:
        query += " WHERE o.rowid=?"
        args.append(row_id)
    elif before is not None:
        query += " WHERE o.rowid<?"
        args.append(before)
    query += " ORDER BY o.rowid DESC LIMIT ?"
    args.append(limit)
    # StreamingResponse can resume a sequential iterator on different worker threads.
    with outbox(check_same_thread=False) as conn:
        for row in conn.execute(query, args):
            yield dict(row)


def retry(spec, ctx, profile, store):
    """現在の接続先と一致する未配送分だけを、保存順と本文形式に沿って再送する。"""
    if profile.kind == "capture":
        raise GenerationError("記録専用の接続先では再送できません")
    sender = Sender(profile)
    remaining = spec.rows
    cursor = None
    try:
        while remaining:
            ctx.check()
            with outbox() as conn:
                query = "SELECT rowid AS enqueue_order,* FROM outbox_v2 WHERE profile_id=? AND target=? AND status='pending'"
                args = [profile.id, fingerprint(profile)]
                if cursor:
                    query += " AND rowid>?"
                    args += [cursor]
                query += " ORDER BY rowid LIMIT ?"
                args += [min(remaining, spec.batch_size, 100)]
                entries = [dict(row) for row in conn.execute(query, args)]
            if not entries:
                break
            cursor = entries[-1]["enqueue_order"]
            # 並び替えると配送順が変わるため、同じ本文形式が連続する範囲だけをまとめる。
            for mode, mode_entries in groupby(entries, key=lambda e: e["body_mode"]):
                group = []
                size = 0
                for entry in mode_entries:
                    if (
                        group
                        and size + len(entry["payload"].encode()) > 4 * 1024 * 1024
                    ):
                        deliver(profile, sender, group, ctx)
                        ctx.progress(processed=len(group), delivered=len(group))
                        group = []
                        size = 0
                    group.append(entry)
                    size += len(entry["payload"].encode())
                if group:
                    deliver(profile, sender, group, ctx)
                    ctx.progress(processed=len(group), delivered=len(group))
            remaining -= len(entries)
    finally:
        sender.close()
