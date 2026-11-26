"""ASGI起動用のモジュール。import時に保存領域と実行履歴を初期化する。"""

from factorylib import create_app
import stream_adapter

app = create_app("stream", "イベント送信シミュレーター", stream_adapter)
