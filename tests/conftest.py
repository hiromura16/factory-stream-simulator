# モジュール読解: 環境依存を隔離し、アダプターの進捗を実ジョブ管理なしで検査する共通道具。
import pytest


# 読解 isolated: 実ホストや既存設定を読まないよう環境変数を外し、試験用の保存先に切り替える。
@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    for name in [
        "APP_PASSWORD_FILE",
        "SQL_HOST",
        "MQTT_HOST",
        "LANDING_DIR",
        "PROFILE_KEY_FILE",
        "FILE_ALLOWED_ROOTS",
        "SQLITE_ROOT",
    ]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("APP_PASSWORD", raising=False)


# 読解 Context: アダプターテストで実時間待機やホスト余力判定を行わず、成果と進捗だけを観察する代替コンテキスト。
class Context:
    run_id = "test-job"
    outputs = []

    # 読解 Context.__init__: 個々の試験で進捗と成果物の一覧を独立させる。
    def __init__(self):
        self.stats = {}
        self.outputs = []

    # 読解 Context.check: ホスト資源や停止状態を使用しない試験用の継続判定。
    def check(self):
        pass

    # 読解 Context.wait: リトライ処理を実時間待機なしで検査するため、ミリ秒引数を消費しない。
    def wait(self, ms):
        pass

    # 読解 Context.progress: 呼出しごとの増分を合算し、件数のアサーションに使えるようにする。
    def progress(self, **values):
        for k, v in values.items():
            self.stats[k] = self.stats.get(k, 0) + v

    # 読解 Context.pace: 実時間の送信速度に依存しないようペース制御を省略する。
    def pace(self, completed):
        pass
