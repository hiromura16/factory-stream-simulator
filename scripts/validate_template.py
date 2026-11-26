"""保存済みテンプレートを、アプリの状態や接続先に触れず検証する。"""

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import ConfigurationError, RunSpec  # noqa: E402
from generation import (  # noqa: E402
    GenerationError,
    generation_context,
    sample_offsets,
    validate_generation,
)

KIND = "stream"
MAX_BYTES = 2 * 1024 * 1024


def validate_template(payload):
    """このアプリで使う設定と、代表行の生成を検証する。"""
    if KIND in {"files", "sql", "stream"}:
        spec = RunSpec.model_validate(payload)
        if KIND != "stream" and spec.task != "generate":
            raise GenerationError("再送はストリーム送信で使えます", path=("task",))
        if KIND != "files" and spec.faults.enabled and spec.faults.artifact_mode != "none":
            raise GenerationError(
                "不正ファイルの生成設定はファイル生成で使えます",
                path=("faults", "artifact_mode"),
            )
        validate_generation(spec, kind=KIND)
        if KIND == "stream":
            validate_stream_templates(spec)
        return spec

    from models import Spec

    spec = Spec.model_validate(payload)
    if KIND in {"api", "equipment", "historian"}:
        from validation import validate_source_spec

        validate_source_spec(KIND, spec)
    else:
        try:
            validate_generation(spec.generator, kind="source")
        except GenerationError as exc:
            raise GenerationError(str(exc), path=("generator", *exc.path)) from None
    if KIND == "logs":
        validate_log_template(spec)
    return spec


def validate_log_template(spec):
    """ドライバーの整形処理でログ本文の参照を確認する。配送は開始しない。"""
    from types import SimpleNamespace

    from drivers import EventDriver

    driver = EventDriver(SimpleNamespace(kind=KIND, spec=spec))
    with generation_context("logs", "message_template"):
        for offset in sample_offsets(spec.generator):
            driver.log_payload(driver.event(offset, trace=[]), offset)


def validate_stream_templates(spec):
    """接続情報を読み込まず、イベントの本文とトピックを組み立てる。"""
    from generation import generate_record
    from stream_events import build_events

    with generation_context("stream", "topic_template"):
        for offset in sample_offsets(spec):
            sequence = spec.start_sequence + offset
            build_events(spec, generate_record(spec, sequence), sequence, None)


def location(parts):
    """配列の位置を、JSON編集時に探せる0始まりのパスとして表示する。"""
    return "$" + "".join(
        f"[{part}]" if isinstance(part, int) else "." + str(part)
        for part in parts
    )


def read_template(path):
    """Web画面と同じサイズ上限で、ファイルまたは標準入力を読む。"""
    if path == "-":
        raw = sys.stdin.buffer.read(MAX_BYTES + 1)
    else:
        with Path(path).open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise GenerationError("JSONは2MiB以下にしてください")
    return json.loads(raw.decode("utf-8-sig"))


def show_validation_errors(exc):
    """入力値を表示せず、設定の位置と直すべき制約を出力する。"""
    messages = {
        "extra_forbidden": "設定にない項目です。キー名を確認してください",
        "missing": "必須項目です",
        "literal_error": "選択肢から指定してください",
        "string_pattern_mismatch": "文字の形式を確認してください",
        "string_too_long": "文字数を減らしてください",
        "string_too_short": "必要な文字数を入力してください",
        "too_short": "必要な要素を追加してください",
        "too_long": "要素数を減らしてください",
        "less_than_equal": "上限以下にしてください",
        "greater_than_equal": "下限以上にしてください",
        "finite_number": "有限の数を指定してください",
    }
    for error in exc.errors(include_input=False, include_url=False):
        kind = error["type"]
        message = messages.get(kind)
        if message is None:
            cause = error.get("ctx", {}).get("error")
            message = (
                str(cause) if isinstance(cause, ConfigurationError)
                else "この項目の型と制約を確認してください"
            )
        print(f"{location(error['loc'])}  {message}", file=sys.stderr)


def main():
    """検証成功は0、読込・入力エラーは1を返す。"""
    profile_note = (
        "保存済みの公開プロファイルは読み込まないため、Modbusの割当も確認します。"
        if KIND == "equipment" else None
    )
    parser = argparse.ArgumentParser(description=__doc__, epilog=profile_note)
    parser.add_argument("file", metavar="JSON", help="テンプレートのパス。- は標準入力")
    parser.add_argument(
        "--compact", action="store_true",
        help="既定値とエディター用の注釈を除いたJSONを標準出力へ出す",
    )
    args = parser.parse_args()
    try:
        spec = validate_template(read_template(args.file))
    except OSError:
        print("ファイルを開けません。パスと読み取り権限を確認してください。", file=sys.stderr)
        return 1
    except UnicodeDecodeError:
        print("UTF-8のJSONを指定してください。", file=sys.stderr)
        return 1
    except json.JSONDecodeError as error:
        print(f"{error.lineno}行 {error.colno}列  JSONの構文を確認してください。", file=sys.stderr)
        return 1
    except ValidationError as error:
        show_validation_errors(error)
        return 1
    except GenerationError as error:
        print(f"{location(error.path)}  {error}", file=sys.stderr)
        return 1
    except (ArithmeticError, RecursionError, TypeError, ValueError):
        print("入力の型、範囲、JSONの入れ子を確認してください。", file=sys.stderr)
        return 1

    if args.compact:
        payload = {"version": spec.version, **spec.model_dump(mode="json", exclude_defaults=True)}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print("設定と代表行の生成を検証しました。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
