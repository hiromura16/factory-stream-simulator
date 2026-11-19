# モジュール読解: ブローカー固有の接続と配送確認を共通アダプターから分離する。配送完了の意味は方式ごとに異なる。
"""Additional broker transports. Each adapter defines its own acknowledgement boundary."""

from __future__ import annotations

import asyncio
import base64
import json
import re
import threading

from connection_security import connection_file, secret, tls_context
from generation import GenerationError


# 読解 headers: 設定済みの追加ヘッダーを取り出し、選ばれた認証方式のヘッダーを組み立てる。戻り値には送信時だけ使う秘密値が含まれる。
def headers(p):
    values = {
        name: value.get_secret_value()
        for name, value in p.headers.items()
        if value is not None
    }
    if p.auth_mode == "basic":
        values["Authorization"] = (
            "Basic "
            + base64.b64encode(
                (p.username + ":" + secret(p, "password")).encode()
            ).decode()
        )
    elif p.auth_mode == "bearer":
        values["Authorization"] = "Bearer " + secret(p, "bearer_token")
    elif p.auth_mode == "api_key":
        values[p.api_key_header] = secret(p, "api_key")
    return values


# 読解 validate_topic: 空名・制御文字を拒否し、Kafka名・NATS subject・AMQP routing keyの個別制約も確認する。
def validate_topic(kind, topic):
    if not topic or any(ord(c) < 32 for c in topic):
        raise GenerationError("配送先の名前が不正です")
    if kind == "kafka" and (
        not re.fullmatch(r"[A-Za-z0-9._-]{1,249}", topic) or topic in {".", ".."}
    ):
        raise GenerationError(
            "Kafkaトピックは英数字・点・下線・ハイフンで249文字以内にしてください"
        )
    if kind == "nats" and (
        any(c in topic for c in "*> ") or any(not token for token in topic.split("."))
    ):
        raise GenerationError(
            "NATS subjectには空白・空の要素・ワイルドカードを使用できません"
        )
    if kind == "amqp" and len(topic.encode()) > 255:
        raise GenerationError("AMQP routing keyは255バイト以内にしてください")


# 読解 Kafka: レコード識別子をキーとして送信し、キューの残りと配送コールバックで成功を判断する。
class Kafka:
    # 読解 Kafka.__init__: TLSとSASLの組合せ、通信時間上限、冪等送信を設定し、Producerを準備する。
    def __init__(self, p):
        from confluent_kafka import Producer

        self.p = p
        protocol = "SSL" if p.ssl_mode != "off" else "PLAINTEXT"
        if p.kafka_sasl_mechanism != "none":
            protocol = "SASL_" + protocol
        options = {
            "bootstrap.servers": p.bootstrap_servers
            or p.host + ":" + str(p.port or 9092),
            "security.protocol": protocol,
            "enable.idempotence": True,
            "acks": "all",
            "message.timeout.ms": p.timeout_seconds * 1000,
            "socket.timeout.ms": p.timeout_seconds * 1000,
            "log_level": 0,
        }
        if p.kafka_sasl_mechanism != "none":
            options.update(
                {
                    "sasl.mechanism": p.kafka_sasl_mechanism,
                    "sasl.username": p.username,
                    "sasl.password": secret(p, "password"),
                }
            )
        if p.ssl_mode != "off":
            options["enable.ssl.certificate.verification"] = p.ssl_mode == "verify"
            if p.tls_ca_file:
                options["ssl.ca.location"] = connection_file(p.tls_ca_file)
            if p.tls_cert_file:
                options["ssl.certificate.location"] = connection_file(p.tls_cert_file)
            if p.tls_key_file:
                options["ssl.key.location"] = connection_file(p.tls_key_file)
            if p.tls_key_password:
                options["ssl.key.password"] = secret(p, "tls_key_password")
        self.client = Producer(options)

    # 読解 Kafka.test: クラスタのメタデータを問い合わせる。疎通試験ではイベントを発行しない。
    def test(self):
        self.client.list_topics(timeout=self.p.timeout_seconds)
        return {"status": "connected", "published": False}

    # 読解 Kafka.send: トピックを検証してキューに追加し、全件の完了待ち後に残件や配送エラーを拒否する。
    def send(self, entries):
        failures = []

        # 読解 Kafka.send.ack: ブローカー配送結果のコールバック。失敗コードだけを外側の一覧に残す。
        def ack(error, message):
            if error:
                failures.append(error.code())

        for entry in entries:
            validate_topic("kafka", entry["topic"])
            self.client.produce(
                entry["topic"],
                value=entry["payload"].encode(),
                key=entry["record_key"].encode(),
                on_delivery=ack,
            )
            self.client.poll(0)
        if self.client.flush(self.p.timeout_seconds) or failures:
            raise ConnectionError("Kafkaの配送確認に失敗しました")

    # 読解 Kafka.close: 終了前に最長2秒の範囲で未送信キューの排出を待つ。
    def close(self):
        self.client.flush(min(2, self.p.timeout_seconds))


# 読解 AMQP: 配信確認を有効にしたチャネルでルーティング必須の永続メッセージを扱う。
class AMQP:
    # 読解 AMQP.__init__: 認証・必要なTLS・タイムアウトを指定して接続し、配送確認付きチャネルを開く。
    def __init__(self, p):
        import pika

        self.p = p
        self.declared = set()
        creds = pika.PlainCredentials(p.username or "guest", secret(p, "password"))
        tls = pika.SSLOptions(tls_context(p), p.host) if p.ssl_mode != "off" else None
        self.client = pika.BlockingConnection(
            pika.ConnectionParameters(
                host=p.host,
                port=p.port or (5671 if tls else 5672),
                virtual_host=p.amqp_virtual_host,
                credentials=creds,
                ssl_options=tls,
                socket_timeout=p.timeout_seconds,
                stack_timeout=p.timeout_seconds + 5,
                blocked_connection_timeout=p.timeout_seconds,
                heartbeat=30,
            )
        )
        self.channel = self.client.channel()
        self.channel.confirm_delivery()

    # 読解 AMQP.test: 構築時の接続成立を報告する。発行やキューの宣言はしない。
    def test(self):
        return {"status": "connected", "published": False}

    # 読解 AMQP.send: 必要時だけ既定交換先向けのキューを宣言し、レコードIDを持つメッセージを発行する。
    def send(self, entries):
        import pika

        for entry in entries:
            topic = entry["topic"]
            validate_topic("amqp", topic)
            if (
                self.p.amqp_declare_queue
                and not self.p.amqp_exchange
                and topic not in self.declared
            ):
                self.channel.queue_declare(queue=topic, durable=True)
                self.declared.add(topic)
            self.channel.basic_publish(
                exchange=self.p.amqp_exchange,
                routing_key=topic,
                body=entry["payload"].encode(),
                mandatory=True,
                properties=pika.BasicProperties(
                    content_type="application/json",
                    delivery_mode=2,
                    message_id=entry["record_key"],
                ),
            )
        self.client.process_data_events(time_limit=0)

    # 読解 AMQP.close: 接続がまだ開いている場合だけ閉じる。
    def close(self):
        if self.client.is_open:
            self.client.close()


# 読解 NATS: 同期呼出側と非同期クライアントの間を専用イベントループでつなぐ。
class NATS:
    # 読解 NATS.__init__: 認証・TLSを選んで再接続なしの接続を開始する。初期接続失敗時はループとスレッドを停止する。
    def __init__(self, p):
        import nats

        self.p = p
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()
        self.client = None
        args = {
            "servers": [
                ("tls" if p.ssl_mode != "off" else "nats")
                + "://"
                + p.host
                + ":"
                + str(p.port or 4222)
            ],
            "connect_timeout": p.timeout_seconds,
            "allow_reconnect": False,
            "max_reconnect_attempts": 0,
        }
        if p.nats_token:
            args["token"] = secret(p, "nats_token")
        elif p.username:
            args.update(user=p.username, password=secret(p, "password"))
        if p.nats_credentials_file:
            args["user_credentials"] = connection_file(p.nats_credentials_file)
        if p.ssl_mode != "off":
            args["tls"] = tls_context(p)
        try:
            self.client = self.call(nats.connect(**args))
        except Exception:
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.thread.join()
            self.loop.close()
            raise

    # 読解 NATS.call: 別スレッドのループにコルーチンを渡し、設定時間に猶予を加えた範囲で結果を待つ。
    def call(self, coroutine):
        return asyncio.run_coroutine_threadsafe(coroutine, self.loop).result(
            timeout=self.p.timeout_seconds + 2
        )

    # 読解 NATS.test: 現在の接続をflushして疎通を確かめる。イベントは発行しない。
    def test(self):
        self.call(self.client.flush(timeout=self.p.timeout_seconds))
        return {"status": "connected", "published": False}

    # 読解 NATS.send: 通常発行とJetStream発行を切り替え、最後に送信キューのflushを待つ。
    def send(self, entries):
        # 読解 NATS.send.publish: ループ上で各subjectを検査して順次発行する。JetStreamにだけ重複識別子を付ける。
        async def publish():
            js = (
                self.client.jetstream(timeout=self.p.timeout_seconds)
                if self.p.nats_jetstream
                else None
            )
            for entry in entries:
                validate_topic("nats", entry["topic"])
                if js:
                    await js.publish(
                        entry["topic"],
                        entry["payload"].encode(),
                        headers={"Nats-Msg-Id": entry["record_key"]},
                    )
                else:
                    await self.client.publish(entry["topic"], entry["payload"].encode())
            await self.client.flush(timeout=self.p.timeout_seconds)

        self.call(publish())

    # 読解 NATS.close: 非同期接続の終了後、失敗時もループ停止・スレッド待ち・ループ解放を実施する。
    def close(self):
        try:
            if self.client:
                self.call(self.client.close())
        finally:
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.thread.join(timeout=3)
            self.loop.close()


# 読解 WebSocket: 同期接続で本文を発行する。確認応答を要求するかは接続設定に従う。
class WebSocket:
    # 読解 WebSocket.__init__: TLS指定とURLを照合し、認証ヘッダーやサブプロトコルを付けて直接接続する。
    def __init__(self, p):
        from websockets.sync.client import connect

        self.p = p
        if p.ssl_mode != "off" and p.url.startswith("ws:"):
            raise GenerationError("TLS有効時はwss:// URLを指定してください")
        options = {
            "additional_headers": headers(p),
            "open_timeout": p.timeout_seconds,
            "close_timeout": min(5, p.timeout_seconds),
            "proxy": None,
        }
        if p.url.startswith("wss:"):
            options["ssl"] = tls_context(p)
        if p.websocket_subprotocols:
            options["subprotocols"] = p.websocket_subprotocols
        self.client = connect(p.url, **options)

    # 読解 WebSocket.test: すでに確立した接続の状態を報告する。本文は送らない。
    def test(self):
        return {"status": "connected", "published": False}

    # 読解 WebSocket.send: 各本文を送り、確認方式に応じて応答を待つ。部分失敗や不正応答は成功にしない。
    def send(self, entries):
        for entry in entries:
            self.client.send(entry["payload"])
            if self.p.websocket_ack != "none":
                ack = self.client.recv(timeout=self.p.timeout_seconds)
                if self.p.websocket_ack == "json":
                    value = json.loads(ack)
                    if (
                        not isinstance(value, dict)
                        or value.get("accepted") != 1
                        or value.get("errors")
                        or value.get("failed")
                    ):
                        raise ConnectionError("WebSocketの受信確認が不正です")
                elif str(ack).strip().lower() not in {"ok", "ack", "accepted"}:
                    raise ConnectionError("WebSocketの受信確認が不正です")

    # 読解 WebSocket.close: 同期WebSocket接続を閉じる。
    def close(self):
        self.client.close()


TRANSPORTS = {"kafka": Kafka, "amqp": AMQP, "nats": NATS, "websocket": WebSocket}
