# モジュール読解: 宣言された規則から決定的に行を生成し、型変換・テンプレート・異常注入を行う純粋な計算層。
# 接続先へ書き込まず、任意コードを評価しない。代表位置による事前検証は全行保証と区別する。
"""Deterministic declarative generation. No eval, SQL fragments, or Python execution."""

from __future__ import annotations

import hashlib
import json
import math
import random
import re
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext

from config import RunSpec


class GenerationError(ValueError):
    # 宣言した生成条件を実行できない場合の、利用者向けの検証例外。
    pass


def record_key(spec, sequence):
    """実行キー・シード・通番から再試行でも変わらないレコード識別子を作る。"""
    return hashlib.sha256(
        f"source.v2:{spec.run_key}:{spec.seed}:{sequence}".encode()
    ).hexdigest()[:32]


def encode_json(value, *, pretty=False, limit=1024 * 1024):
    """非有限数を拒否し、UTF-8のバイト数上限を守ってJSONへ直列化する。"""
    chunks = []
    size = 0
    encoder = json.JSONEncoder(
        ensure_ascii=False,
        allow_nan=False,
        indent=2 if pretty else None,
        separators=None if pretty else (",", ":"),
    )
    for part in encoder.iterencode(value):
        size += len(part.encode())
        if size > limit:
            raise GenerationError("1レコードのJSONは1MiB以下にしてください")
        chunks.append(part)
    return "".join(chunks)


def resolve(value, parameters):
    """先頭がドル記号の値だけをパラメーター参照として解決する。"""
    if isinstance(value, str) and value.startswith("$"):
        key = value[1:]
        if key not in parameters:
            raise GenerationError(f"パラメーター {key} が定義されていません")
        return parameters[key]
    return value


def render(template, values):
    """項目名と短い数値書式だけを許可してテンプレートを展開する。

    属性アクセスや変換指定は受け付けず、展開後の長さにも上限を設ける。
    """
    parts = []
    for literal, name, format_spec, conversion in string.Formatter().parse(template):
        parts.append(literal)
        if name is None:
            continue
        if (
            not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}", name)
            or conversion
            or not re.fullmatch(
                r"(?:0?[0-9]{1,2})?(?:\.[0-9]{1,2})?[dfsg]?", format_spec
            )
        ):
            raise GenerationError(
                "テンプレートは項目名と短い数値書式だけを参照できます"
            )
        if name not in values:
            raise GenerationError(f"テンプレート参照 {name} が見つかりません")
        parts.append(format(values[name], format_spec))
    result = "".join(parts)
    if len(result) > 8192:
        raise GenerationError("テンプレート結果が長すぎます")
    return result


def coerce(value, field):
    """項目定義に合わせて値を変換し、型・精度・NULLの制約を検査する。

    小数は精度を保つ文字列、日時はUTCのISO表現として返す。
    """
    if value is None:
        if field.primary_key:
            raise GenerationError("主キーはNULLにできません")
        return None
    dtype = field.data_type
    if dtype == "string":
        result = str(value)
        if len(result) > field.length:
            raise GenerationError(f"{field.name} が文字数上限を超えています")
        return result
    if dtype == "integer":
        if isinstance(value, float) and not value.is_integer():
            raise GenerationError(f"{field.name} は整数ではありません")
        result = int(value)
        if not -(2**63) <= result < 2**63:
            raise GenerationError("整数は符号付き64ビットの範囲にしてください")
        return result
    if dtype in {"number", "decimal"}:
        number = float(value)
        if not math.isfinite(number):
            raise GenerationError("数値は有限である必要があります")
        if dtype == "number":
            return round(number, field.scale)
        with localcontext() as context:
            context.prec = 60
            result = Decimal(str(value)).quantize(Decimal(1).scaleb(-field.scale))
        if len(result.as_tuple().digits) > field.precision:
            raise GenerationError("小数の精度上限を超えています")
        return str(result)
    if dtype == "boolean":
        if not isinstance(value, bool):
            raise GenerationError("真偽値の項目にはboolean生成を指定してください")
        return value
    if dtype == "datetime":
        dt = datetime.fromisoformat(str(value))
        if dt.tzinfo is None:
            raise GenerationError("日時にはタイムゾーンが必要です")
        return dt.astimezone(timezone.utc).isoformat()
    return value


def generate_record(spec: RunSpec, sequence: int, *, apply_anomalies=True, trace=None):
    """通番に対応する一行を定義順に生成し、必要なら異常ルールを適用する。

    乱数をレコードと項目ごとに固定するため、バッチ分割に依存しない。
    参照項目は先に生成されている必要がある。
    """
    row = {}
    key = record_key(spec, sequence)
    parameters = spec.parameters
    for field in spec.fields:
        rng = random.Random(
            int(hashlib.sha256((key + ":" + field.name).encode()).hexdigest()[:16], 16)
        )

        # 読解 generate_record.get: 現在の項目の属性を読み、ドル記号の参照ならspec.parametersから解決する。
        # ループ中のfieldを即時参照する補助であり、後から実行するcallbackとして保存しない。
        def get(name):
            return resolve(getattr(field, name), parameters)

        group = int(get("group_size"))
        if group < 1:
            raise GenerationError("group_sizeは1以上にしてください")
        index = sequence // group
        modulo = int(get("modulo"))
        if modulo < 0:
            raise GenerationError("moduloは0以上にしてください")
        if modulo:
            index %= modulo
        kind = field.generator
        if kind == "record_id":
            value = key
        elif kind == "uuid":
            value = str(uuid.uuid5(uuid.NAMESPACE_URL, key + ":" + field.name))
        elif kind == "sequence":
            value = float(get("start")) + index * float(get("step"))
        elif kind in {"integer", "uniform"}:
            low, high = float(get("minimum")), float(get("maximum"))
            if low > high:
                raise GenerationError("最小値が最大値を超えています")
            value = (
                rng.randint(int(low), int(high))
                if kind == "integer"
                else rng.uniform(low, high)
            )
        elif kind == "normal":
            deviation = float(get("stddev"))
            if deviation < 0:
                raise GenerationError("標準偏差は0以上にしてください")
            value = rng.gauss(float(get("mean")), deviation)
        elif kind == "choice":
            choices = get("choices")
            if not isinstance(choices, list) or not choices:
                raise GenerationError("選択肢を指定してください")
            if field.weights and (
                len(field.weights) != len(choices)
                or min(field.weights) < 0
                or sum(field.weights) <= 0
            ):
                raise GenerationError("選択肢と重みを確認してください")
            value = rng.choices(choices, weights=field.weights or None, k=1)[0]
        elif kind == "boolean":
            probability = float(get("probability"))
            if not 0 <= probability <= 1:
                raise GenerationError("確率は0〜1にしてください")
            value = rng.random() < probability
        elif kind == "constant":
            value = get("value")
        elif kind == "template":
            value = render(
                field.template,
                {**parameters, **row, "sequence": sequence, "record_id": key},
            )
        elif kind == "timestamp":
            at = datetime.fromisoformat(str(get("start")))
            if at.tzinfo is None:
                raise GenerationError("開始日時にはタイムゾーンが必要です")
            value = (at + timedelta(seconds=index * float(get("step")))).isoformat()
        else:
            try:
                values = [row[name] for name in field.sources]
            except KeyError as exc:
                raise GenerationError("参照元の項目は先に定義してください") from exc
            if kind == "reference":
                value = values[0]
            else:
                converter = Decimal if field.data_type == "decimal" else float
                with localcontext() as context:
                    context.prec = 60
                    numeric = [converter(str(v)) for v in values]
                    if kind == "sum":
                        value = sum(numeric)
                    elif kind == "difference":
                        value = numeric[0] - sum(numeric[1:])
                    elif kind == "product":
                        value = math.prod(numeric)
                    elif kind == "ratio":
                        if len(numeric) != 2 or not numeric[1]:
                            raise GenerationError("比率には0でない分母が必要です")
                        value = numeric[0] / numeric[1]
        if field.condition:
            condition = field.condition
            if condition.field not in row:
                raise GenerationError("条件が参照する項目を先に定義してください")
            left, right = row[condition.field], resolve(condition.value, parameters)
            op = condition.operator
            matches = {
                # コールバック: 選択されたときだけ等値比較を評価する無引数関数。左辺と右辺は現在の行の条件値。
                "eq": lambda: left == right,
                # コールバック: 選択されたときだけ不一致比較を評価する無引数関数。左辺と右辺は現在の行の条件値。
                "ne": lambda: left != right,
                # コールバック: 選択されたときだけより大きい比較を評価する無引数関数。左辺と右辺は現在の行の条件値。
                "gt": lambda: left > right,
                # コールバック: 選択されたときだけ以上比較を評価する無引数関数。左辺と右辺は現在の行の条件値。
                "ge": lambda: left >= right,
                # コールバック: 選択されたときだけより小さい比較を評価する無引数関数。左辺と右辺は現在の行の条件値。
                "lt": lambda: left < right,
                # コールバック: 選択されたときだけ以下比較を評価する無引数関数。左辺と右辺は現在の行の条件値。
                "le": lambda: left <= right,
                # コールバック: 選択されたときだけ包含比較を評価する無引数関数。左辺と右辺は現在の行の条件値。
                "in": lambda: left in right,
            }[op]()
            if matches:
                value = resolve(condition.then_value, parameters)
        if field.null_probability and rng.random() < field.null_probability:
            value = None
        row[field.name] = coerce(value, field)
    if apply_anomalies:
        row = inject_anomalies(spec, row, sequence, trace)
    return row


def matches(left, operator, right):
    """宣言済みの比較演算子を適用する。式の評価や演算子の推測はしない。"""
    return {
        # コールバック: 選択されたときだけ等値比較を評価する無引数関数。左辺と右辺は現在の行の条件値。
        "eq": lambda: left == right,
        # コールバック: 選択されたときだけ不一致比較を評価する無引数関数。左辺と右辺は現在の行の条件値。
        "ne": lambda: left != right,
        # コールバック: 選択されたときだけより大きい比較を評価する無引数関数。左辺と右辺は現在の行の条件値。
        "gt": lambda: left > right,
        # コールバック: 選択されたときだけ以上比較を評価する無引数関数。左辺と右辺は現在の行の条件値。
        "ge": lambda: left >= right,
        # コールバック: 選択されたときだけより小さい比較を評価する無引数関数。左辺と右辺は現在の行の条件値。
        "lt": lambda: left < right,
        # コールバック: 選択されたときだけ以下比較を評価する無引数関数。左辺と右辺は現在の行の条件値。
        "le": lambda: left <= right,
        # コールバック: 選択されたときだけ包含比較を評価する無引数関数。左辺と右辺は現在の行の条件値。
        "in": lambda: left in right,
    }[operator]()


def inject_anomalies(spec, row, sequence, trace=None):
    """位置・確率・条件が一致した異常ルールを行へ順番に適用する。

    コピー元は異常注入前の行から再生成し、再帰的な異常適用を避ける。
    明示された検証迂回ルール以外は項目の型制約を再確認する。
    """
    offset = sequence - spec.start_sequence
    fields = {f.name: f for f in spec.fields}
    for index, rule in enumerate(spec.anomalies):
        if (
            not rule.enabled
            or offset < rule.from_row
            or (rule.to_row is not None and offset > rule.to_row)
            or (offset - rule.from_row) % rule.every
        ):
            continue
        rng = random.Random(
            int(
                hashlib.sha256(
                    (record_key(spec, sequence) + ":anomaly:" + str(index)).encode()
                ).hexdigest()[:16],
                16,
            )
        )
        if rng.random() >= rule.probability:
            continue
        if rule.field not in fields:
            raise GenerationError("異常ルールの対象項目が定義されていません")
        if rule.when:
            if rule.when.field not in row:
                raise GenerationError("異常条件が参照する項目が見つかりません")
            if not matches(
                row[rule.when.field],
                rule.when.operator,
                resolve(rule.when.value, spec.parameters),
            ):
                continue
        if trace is not None:
            trace.append(rule.name)
        if rule.operation == "omit":
            row.pop(rule.field, None)
            continue
        value = resolve(rule.value, spec.parameters)
        original = row.get(rule.field)
        if rule.operation == "set":
            result = value
        elif rule.operation == "null":
            result = None
        elif rule.operation in {"freeze", "copy_from"}:
            anchor = rule.from_row if rule.operation == "freeze" else int(value)
            if anchor < 0:
                raise GenerationError("コピー元のレコード位置は0以上にしてください")
            result = generate_record(
                spec, spec.start_sequence + anchor, apply_anomalies=False
            )[rule.field]
        elif rule.operation == "timestamp_shift":
            result = (
                datetime.fromisoformat(str(original)) + timedelta(seconds=float(value))
            ).isoformat()
        else:
            with localcontext() as context:
                context.prec = 60
                number = Decimal(str(original))
                amount = Decimal(str(value))
                result = (
                    number * amount
                    if rule.operation == "multiply"
                    else number + amount * (offset - rule.from_row)
                    if rule.operation == "ramp"
                    else number + amount
                )
        if rule.bypass_validation and isinstance(result, Decimal):
            result = (
                str(result)
                if fields[rule.field].data_type == "decimal"
                else float(result)
            )
        row[rule.field] = (
            result if rule.bypass_validation else coerce(result, fields[rule.field])
        )
    return row


def sample_offsets(spec):
    """先頭・途中・末尾と異常ルールの境界を含む代表位置を返す。"""
    offsets = {0, min(97, spec.rows - 1), spec.rows - 1}
    for rule in spec.anomalies:
        if rule.enabled and rule.from_row < spec.rows:
            offsets.add(rule.from_row)
            offsets.add(min(spec.rows - 1, rule.from_row + rule.every))
            if rule.to_row is not None:
                offsets.add(min(spec.rows - 1, rule.to_row))
    return sorted(offsets)


def validate_generation(spec):
    # Check the beginning, a later point and the end without materializing the run.
    """代表位置の生成とJSON展開を事前確認する。全行の成功保証ではない。"""
    for offset in sample_offsets(spec):
        sequence = spec.start_sequence + offset
        row = generate_record(spec, sequence)
        encode_json(row)
        for template in [spec.files.json_template, spec.stream.payload_template]:
            if template is not None:
                encode_json(
                    map_json(
                        template,
                        row,
                        spec.parameters,
                        {
                            "sequence": sequence,
                            "record_key": record_key(spec, sequence),
                            "run_key": spec.run_key,
                        },
                    )
                )
    return spec


def batch_limit(spec, requested):
    """代表行のサイズからバッチ上限を見積もり、要求数とバースト幅で抑える。

    全行を実体化しない近似値であり、最大行サイズの厳密な証明ではない。
    """
    size = 256
    for offset in sample_offsets(spec):
        row = generate_record(spec, spec.start_sequence + offset)
        size = max(size, len(encode_json(row).encode()))
        for template in [spec.files.json_template, spec.stream.payload_template]:
            if template is not None:
                size = max(
                    size,
                    len(
                        encode_json(
                            map_json(
                                template,
                                row,
                                spec.parameters,
                                {
                                    "sequence": spec.start_sequence + offset,
                                    "record_key": record_key(
                                        spec, spec.start_sequence + offset
                                    ),
                                    "run_key": spec.run_key,
                                },
                            )
                        ).encode()
                    ),
                )
    return max(
        1,
        min(
            requested,
            spec.burst_rows or requested,
            (16 * 1024 * 1024) // max(256, size * 4),
        ),
    )


def map_json(template, row, parameters, metadata, depth=0):
    """行・パラメーター・メタ情報への参照を、型を保ってJSON構造へ写す。

    未知の参照と深すぎる入れ子を拒否する。通常の文字列は展開しない。
    """
    if template is None:
        return row
    if depth > 32:
        raise GenerationError("JSONの入れ子は32段階までにしてください")
    if isinstance(template, dict):
        return {
            k: map_json(v, row, parameters, metadata, depth + 1)
            for k, v in template.items()
        }
    if isinstance(template, list):
        return [map_json(v, row, parameters, metadata, depth + 1) for v in template]
    if isinstance(template, str) and template.startswith(
        ("$row.", "$parameters.", "$meta.")
    ):
        namespace, *parts = template[1:].split(".")
        value = {"row": row, "parameters": parameters, "meta": metadata}[namespace]
        for part in parts:
            if isinstance(value, dict) and part in value:
                value = value[part]
            elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
                value = value[int(part)]
            else:
                raise GenerationError("JSONテンプレートの参照先が見つかりません")
        return value
    return template


def stream_payload(spec, row, sequence):
    """本文を組み立て、指定時だけ衝突しないキーへメタ情報を付ける。"""
    metadata = {
        "record_key": record_key(spec, sequence),
        "sequence": sequence,
        "run_key": spec.run_key,
    }
    payload = map_json(spec.stream.payload_template, row, spec.parameters, metadata)
    if spec.stream.envelope:
        if not isinstance(payload, dict):
            raise GenerationError(
                "メタデータを追加する場合、本文テンプレートはJSONオブジェクトにしてください"
            )
        if spec.stream.metadata_key in payload:
            raise GenerationError("メタデータの項目名と送信本文のキーが重複しています")
        payload = {**payload, spec.stream.metadata_key: metadata}
    return payload


def inject_fault(spec, ctx, stage, batch):
    """異常シナリオが有効な場合だけ、指定段階の停止・遅延判定へ委譲する。"""
    if spec.faults.enabled and spec.faults.action != "none":
        ctx.inject(stage, batch)
