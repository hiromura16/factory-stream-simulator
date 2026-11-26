"""Additional broker transports. Each adapter defines its own acknowledgement boundary."""

from __future__ import annotations

import asyncio
import base64
import json
import re
import threading

from connection_security import connection_file, secret, tls_context
from generation import GenerationError


def headers(p):
    """送信用の追加ヘッダーと認証ヘッダーを作る。戻り値に秘密値を含む。"""
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


def validate_topic(kind, topic):
    """空名と制御文字を拒否し、選んだ方式のトピック名の制約を適用する。"""
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


class Kafka:
    """レコードIDを送信キーに使い、ブローカーからの配送結果を待つ。"""
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

    def test(self):
        """イベントを発行せずに、クラスターのメタデータ取得で疎通を調べる。"""
        self.client.list_topics(timeout=self.p.timeout_seconds)
        return {"status": "connected", "published": False}

    def send(self, entries):
        """全件の配送を待ち、送信キューの残件と個々の配送エラーを検出する。"""
        failures = []

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

    def close(self):
        """終了前に、未送信キューが空になるまで最大2秒待つ。"""
        self.client.flush(min(2, self.p.timeout_seconds))


class AMQP:
    """配送確認を有効にしたチャネルで、ルーティング必須の永続メッセージを扱う。"""
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

    def test(self):
        """構築時の接続結果を返す。発行やキュー宣言は行わない。"""
        return {"status": "connected", "published": False}

    def send(self, entries):
        """既定の交換先を使う場合はキューを準備し、レコードID付きで発行する。"""
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

    def close(self):
        if self.client.is_open:
            self.client.close()


class NATS:
    """別スレッドのイベントループを使い、同期呼び出しからNATSへ接続する。"""
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

    def call(self, coroutine):
        """専用ループに処理を渡し、設定された時間に猶予を加えて待つ。"""
        return asyncio.run_coroutine_threadsafe(coroutine, self.loop).result(
            timeout=self.p.timeout_seconds + 2
        )

    def test(self):
        """発行せず、既存接続をフラッシュして疎通を調べる。"""
        self.call(self.client.flush(timeout=self.p.timeout_seconds))
        return {"status": "connected", "published": False}

    def send(self, entries):
        """通常発行またはJetStreamで送信し、最後に送信キューをフラッシュする。"""
        async def publish():
            """イベントを順に発行する。JetStreamの場合だけ重複識別子を付ける。"""
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

    def close(self):
        """接続の終了に失敗した場合も、専用ループとスレッドを片付ける。"""
        try:
            if self.client:
                self.call(self.client.close())
        finally:
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.thread.join(timeout=3)
            self.loop.close()


class WebSocket:
    """本文を送信し、設定で指定された場合は受信側からの確認応答を待つ。"""
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

    def test(self):
        """本文を送らず、確立済みの接続状態を返す。"""
        return {"status": "connected", "published": False}

    def send(self, entries):
        """設定された応答を待つ。部分失敗や不正な応答も失敗として返す。"""
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

    def close(self):
        self.client.close()


TRANSPORTS = {"kafka": Kafka, "amqp": AMQP, "nats": NATS, "websocket": WebSocket}
