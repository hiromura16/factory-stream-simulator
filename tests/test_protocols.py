# モジュール読解: 明示設定がある場合に限り、ブローカーの疎通と実配送確認を試験する。
"""Opt-in real broker checks; fixture credentials are never committed."""

import json
import os
import uuid
from pathlib import Path

import pytest

from config import ConnectionProfile, RunSpec
from conftest import Context
from stream_adapter import handle, test_connection as check_connection


# 読解 test_real_broker_confirmations: 実ブローカー向けプロファイルで、設定済み方式が接続でき、3件の配送が確認されることを検証する。
@pytest.mark.skipif(
    not os.environ.get("STREAM_TEST_PROFILES_FILE"), reason="External brokers opt-in"
)
def test_real_broker_confirmations():
    for values in json.loads(Path(os.environ["STREAM_TEST_PROFILES_FILE"]).read_text()):
        p = ConnectionProfile.model_validate(values)
        assert check_connection(p)["status"] == "connected"
        spec = RunSpec(
            rows=3, target_rate=0, run_key="acceptance-" + uuid.uuid4().hex[:12]
        )
        ctx = Context()
        handle(spec, ctx, p, None)
        assert ctx.stats["delivered"] == 3
