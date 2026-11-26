"""項目の生成、型変換、条件判定、異常値の適用を行う。

行と項目ごとに乱数を固定し、出力先やバッチ分割に依存せず結果を再現できるようにする。
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import re
import string
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, localcontext

from config import RunSpec


class GenerationError(ValueError):
    """生成設定の不備と、設定内で修正する位置を保持する。"""

    def __init__(self, message, *, path=()):
        super().__init__(message)
        self.path = tuple(path)


@contextmanager
def generation_context(*path):
    """生成例外を、入力値を含まない設定エラーに変換する。"""
    try:
        yield
    except GenerationError as exc:
        if exc.path:
            raise
        raise GenerationError(str(exc), path=path) from None
    except (ArithmeticError, IndexError, TypeError, ValueError):
        raise GenerationError(
            "値の型・範囲・書式を確認してください", path=path
        ) from None


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
            raise GenerationError("参照するパラメーターが定義されていません")
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
            raise GenerationError("テンプレートで参照する項目が見つかりません")
        value = values[name]
        if format_spec.endswith("d") and not isinstance(value, int):
            raise GenerationError("整数書式 d では整数型の項目を参照してください")
        try:
            parts.append(format(value, format_spec))
        except (TypeError, ValueError):
            raise GenerationError("テンプレートの書式と参照先の型を合わせてください") from None
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


_GENERATOR_INPUT = {
    "template": "template",
    "timestamp": "start",
    "sequence": "start",
    "uniform": "minimum",
    "integer": "minimum",
    "normal": "stddev",
    "choice": "choices",
    "boolean": "probability",
    "constant": "value",
    "reference": "sources",
    "sum": "sources",
    "difference": "sources",
    "product": "sources",
    "ratio": "sources",
}


def generate_record(spec: RunSpec, sequence: int, *, apply_anomalies=True, trace=None):
    """通番に対応する一行を定義順に生成し、必要なら異常ルールを適用する。

    乱数をレコードと項目ごとに固定するため、バッチ分割に依存しない。
    参照項目は先に生成されている必要がある。
    """
    row = {}
    key = record_key(spec, sequence)
    parameters = spec.parameters
    for index, field in enumerate(spec.fields):
        path = ("fields", index)
        input_key = _GENERATOR_INPUT.get(field.generator, "generator")
        with generation_context(*path):
            rng = random.Random(
                int(hashlib.sha256((key + ":" + field.name).encode()).hexdigest()[:16], 16)
            )
            value = _generate_field(
                field, row, parameters, sequence, key, rng, input_key, path
            )
            if field.condition:
                if field.condition.field not in row:
                    raise GenerationError(
                        "条件が参照する項目を先に定義してください",
                        path=(*path, "condition", "field"),
                    )
                value = conditional_value(field, value, row, parameters, path)
            if field.null_probability and rng.random() < field.null_probability:
                value = None
            with generation_context(*path, "data_type"):
                row[field.name] = coerce(value, field)
    if apply_anomalies:
        row = inject_anomalies(spec, row, sequence, trace)
    return row


def _generate_field(field, row, parameters, sequence, key, rng, input_key, path):
    """一項目の値を作る。条件、欠測率、型変換は呼び出し側で適用する。"""

    def get(name, convert=None):
        """パラメーターと型のエラーを、実際に指定されたキーへひも付ける。"""
        try:
            value = resolve(getattr(field, name), parameters)
            return convert(value) if convert else value
        except GenerationError as exc:
            raise GenerationError(str(exc), path=(*path, name)) from None
        except (ArithmeticError, TypeError, ValueError):
            raise GenerationError("値の型と範囲を確認してください", path=(*path, name)) from None

    group = get("group_size", int)
    if group < 1:
        raise GenerationError("group_sizeは1以上にしてください", path=(*path, "group_size"))
    index = sequence // group
    modulo = get("modulo", int)
    if modulo < 0:
        raise GenerationError("moduloは0以上にしてください", path=(*path, "modulo"))
    if modulo:
        index %= modulo
    kind = field.generator
    with generation_context(*path, input_key):
        if kind == "record_id":
            value = key
        elif kind == "uuid":
            value = str(uuid.uuid5(uuid.NAMESPACE_URL, key + ":" + field.name))
        elif kind == "sequence":
            start = get("start")
            step = get("step")
            # Pythonのfloatで正確に表せない通番でも、整数の開始値と増分は精度を保つ。
            if isinstance(start, int) and isinstance(step, int):
                value = start + index * step
            else:
                value = get("start", float) + index * get("step", float)
                if not math.isfinite(value):
                    raise GenerationError("連番の開始値と増分には有限の数を指定してください")
                if field.data_type == "string" and value.is_integer():
                    value = int(value)
        elif kind in {"integer", "uniform"}:
            low, high = get("minimum", float), get("maximum", float)
            if low > high:
                raise GenerationError("最小値が最大値を超えています")
            value = (
                rng.randint(int(low), int(high))
                if kind == "integer"
                else rng.uniform(low, high)
            )
        elif kind == "normal":
            deviation = get("stddev", float)
            if deviation < 0:
                raise GenerationError("標準偏差は0以上にしてください")
            value = rng.gauss(get("mean", float), deviation)
        elif kind == "choice":
            choices = get("choices")
            if not isinstance(choices, list) or not choices:
                raise GenerationError("選択肢を指定してください")
            if field.weights and (
                len(field.weights) != len(choices)
                or min(field.weights) < 0
                or sum(field.weights) <= 0
            ):
                raise GenerationError("選択肢と重みを確認してください", path=(*path, "weights"))
            value = rng.choices(choices, weights=field.weights or None, k=1)[0]
        elif kind == "boolean":
            probability = get("probability", float)
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
            value = (at + timedelta(seconds=index * get("step", float))).isoformat()
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
    return value


def conditional_value(field, value, row, parameters, path):
    """条件が成立した行だけ、生成した値を置き換える。"""
    condition = field.condition
    path = (*path, "condition")
    with generation_context(*path, "value"):
        applies = matches(
            row[condition.field], condition.operator, resolve(condition.value, parameters)
        )
    if applies:
        with generation_context(*path, "then_value"):
            return resolve(condition.then_value, parameters)
    return value


def matches(left, operator, right):
    """欠測値は順序比較に一致せず、inにはJSON配列を要求する。"""
    if operator == "eq":
        return left == right
    if operator == "ne":
        return left != right
    if operator == "in":
        if not isinstance(right, list):
            raise GenerationError("in の比較値にはJSON配列を指定してください")
        return left in right
    if left is None or right is None:
        return False
    try:
        if operator == "gt":
            return left > right
        if operator == "ge":
            return left >= right
        if operator == "lt":
            return left < right
        return left <= right
    except TypeError:
        return False


def numeric_anomaly(original, value, operation, distance):
    """数値異常の量は検証し、計算できない元の値はそのままにする。"""
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        raise GenerationError("加算・倍率・ドリフトの指定値には数値が必要です") from None
    if not amount.is_finite():
        raise GenerationError("加算・倍率・ドリフトの指定値には有限の数が必要です")
    if original is None:
        return None
    try:
        number = Decimal(str(original))
    except InvalidOperation:
        return None
    if not number.is_finite():
        return None
    with localcontext() as context:
        context.prec = 60
        if operation == "multiply":
            return number * amount
        if operation == "ramp":
            return number + amount * distance
        return number + amount

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
        path = ("anomalies", index)
        if rule.field not in fields:
            raise GenerationError(
                "異常ルールの対象項目が定義されていません", path=(*path, "field")
            )
        if rule.when:
            if rule.when.field not in fields:
                raise GenerationError(
                    "異常条件が参照する項目が見つかりません",
                    path=(*path, "when", "field"),
                )
            with generation_context(*path, "when", "value"):
                if not matches(
                    row.get(rule.when.field),
                    rule.when.operator,
                    resolve(rule.when.value, spec.parameters),
                ):
                    continue
        if rule.operation == "omit":
            row.pop(rule.field, None)
        else:
            with generation_context(*path, "value"):
                value = (
                    resolve(rule.value, spec.parameters)
                    if rule.operation not in {"null", "freeze"}
                    else None
                )
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
                    if original is None:
                        continue
                    result = (
                        datetime.fromisoformat(str(original)) + timedelta(seconds=float(value))
                    ).isoformat()
                else:
                    result = numeric_anomaly(
                        original, value, rule.operation, offset - rule.from_row
                    )
                    if result is None:
                        continue
                if rule.bypass_validation and isinstance(result, Decimal):
                    result = (
                        str(result)
                        if fields[rule.field].data_type == "decimal"
                        else float(result)
                    )
                row[rule.field] = (
                    result if rule.bypass_validation else coerce(result, fields[rule.field])
                )
        if trace is not None:
            trace.append(rule.name)
    return row


def sample_offsets(spec):
    """先頭・途中・末尾と異常ルールの境界を含む代表位置を返す。"""
    offsets = {*range(min(3, spec.rows)), min(97, spec.rows - 1), spec.rows - 1}
    for rule in spec.anomalies:
        if rule.enabled and rule.from_row < spec.rows:
            offsets.add(rule.from_row)
            offsets.add(min(spec.rows - 1, rule.from_row + rule.every))
            if rule.to_row is not None:
                offsets.add(min(spec.rows - 1, rule.to_row))
    return sorted(offsets)


def sample_payloads(spec, row, sequence, kind):
    """選んだ出力方式に関係するペイロードを検証用に生成する。"""
    if kind in {None, "files"} and spec.files.json_template is not None:
        if kind is None or "json" in spec.files.formats:
            with generation_context("files", "json_template"):
                yield map_json(
                    spec.files.json_template,
                    row,
                    spec.parameters,
                    {
                        "sequence": sequence,
                        "record_key": record_key(spec, sequence),
                        "run_key": spec.run_key,
                    },
                )
    if kind == "stream" or (kind is None and spec.stream.payload_template is not None):
        with generation_context("stream", "payload_template"):
            yield stream_payload(spec, row, sequence)


def validate_generation(spec, *, kind=None):
    """異常境界などの代表行を生成し、出力本文の参照と容量を検証する。"""
    for offset in sample_offsets(spec):
        sequence = spec.start_sequence + offset
        row = generate_record(spec, sequence)
        encode_json(row)
        for payload in sample_payloads(spec, row, sequence, kind):
            encode_json(payload)
    return spec


def batch_limit(spec, requested, *, kind=None):
    """代表行の大きさから、メモリに収まるバッチサイズを見積もる。"""
    size = 256
    for offset in sample_offsets(spec):
        sequence = spec.start_sequence + offset
        row = generate_record(spec, sequence)
        size = max(size, len(encode_json(row).encode()))
        for payload in sample_payloads(spec, row, sequence, kind):
            size = max(size, len(encode_json(payload).encode()))
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
