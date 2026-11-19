# モジュール読解: 互換用の公開入口。アダプターの関数を再公開し、生成規則の本体は別モジュールへ置く。
"""Public adapter entry point; generation rules live in declarative presets."""

from stream_adapter import handle, test_connection  # noqa: F401
