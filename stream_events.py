"""合成イベントを配送方式に依存しない送信単位へ変換する。"""

import hashlib

from generation import GenerationError, encode_json, record_key, render, stream_payload
from stream_connections import validate_topic


def build_events(spec, row, sequence, default_topic):
    """プレビューと実行で共通の本文・トピック・重複予定を組み立てる。"""
    key = record_key(spec, sequence)
    payload = stream_payload(spec, row, sequence)
    body = encode_json(payload)
    padding = max(0, spec.stream.message_size_bytes - len(body.encode("utf-8")))
    body += " " * padding
    topic = (
        render(
            spec.stream.topic_template,
            {**spec.parameters, **row, "sequence": sequence, "record_id": key},
        )
        if spec.stream.topic_template
        else default_topic
    )
    original = {
        "record_key": key,
        "payload": body,
        "topic": topic,
        "body_mode": spec.stream.http_body,
    }
    if not spec.stream.duplicate_rate:
        return [original]
    # 元イベントと同じ本文・トピックを維持し、outboxの配送枠だけ分離する。
    # リトライ・途中再開でも同じ重複イベントを同じ枠へ記録する。
    duplicate_key = hashlib.sha256(f"source.v2:duplicate:{key}".encode()).hexdigest()
    draw = int(duplicate_key[:13], 16) / (1 << 52)
    if draw < spec.stream.duplicate_rate:
        return [original, {**original, "record_key": duplicate_key[:32]}]
    return [original]


def check_stream_profile(spec, kind):
    """本文サイズと重複の追加指定は、MQTTかローカル記録だけに許可する。"""
    if (spec.stream.message_size_bytes or spec.stream.duplicate_rate) and kind not in {
        "mqtt",
        "capture",
    }:
        raise GenerationError(
            "本文サイズ・重複率はMQTTまたはローカル記録で使用できます"
        )


def check_stream_topic(kind, topic):
    """実送信と同様、方式に応じてトピックを検証する。"""
    if kind == "mqtt" and (
        not topic or len(topic) > 512 or any(c in topic for c in "#+\x00\n\r")
    ):
        raise GenerationError("送信用トピックが不正です")
    validate_topic(kind, topic)
