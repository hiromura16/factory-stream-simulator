# モジュール読解: ASGIサーバーが読み込む入口。create_appが保存領域と履歴を準備し、種類別アダプターを登録する。
# importだけでも初期化が走るため、単なる構文検査で実行してはならない。
"""ASGI起動用の入口。読み込み時に設定保存領域と実行管理を初期化する。"""

from factorylib import create_app
import stream_adapter

app = create_app("stream", "ストリーム データ送信", stream_adapter)
