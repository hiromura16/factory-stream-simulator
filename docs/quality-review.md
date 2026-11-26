# 製品品質レビュー対応表

2026年11月26日に確認した、レビューに対応するIssueと変更・確認箇所をまとめます。

| Issue | 対応 | 確認先 |
| --- | --- | --- |
| [#9 生成エンジン](https://github.com/hiromura16/factory-stream-simulator/issues/9) | NULLや非数値を含む数値異常、条件の型比較、連番の文字列表現を修正。 | [資料またはテスト](template-guide.md) |
| [#10 テンプレートJSONのエラー表示で、どの項目の何が悪いか分からない](https://github.com/hiromura16/factory-stream-simulator/issues/10) | エラーを日本語と項目位置で返し、画面で表示。構文と内部エラーの失敗応答も確認。 | [資料またはテスト](../tests/test_app_help.py) |
| [#11 Ubuntu 26.04 の Python 3.14 で直接起動できない／空きメモリ6GiB未満で全実行が失敗する](https://github.com/hiromura16/factory-stream-simulator/issues/11) | Python 3.12〜3.14の依存を解決し、メモリの既定しきい値を1GiBへ。 | [資料またはテスト](../tests/test_memory_guard.py) |
| [#12 SQL・ファイル・ストリームの3ツール間でテンプレートJSONを相互に読み込めない](https://github.com/hiromura16/factory-stream-simulator/issues/12) | 3ジョブで共通形式を相互に検証し、アプリ固有の出力設定を区別。 | [資料またはテスト](template-guide.md) |
| [#13 製品品質レビュー](https://github.com/hiromura16/factory-stream-simulator/issues/13) | マニュアル、ひな型・設定ガイド、AIハーネス、API、管理認証の導入、ライセンス、変更履歴、CIを整備。 | [資料またはテスト](user-manual.md) |

構成例で接続先・ストレージ・認証を設定します。実運用先での配備と外部DBやブローカーの疎通は、各環境の運用手順に従って確認します。

[VM導入](vm-compose.md) · [API](api-guide.md) · [共通コードの同期](code-reading-guide.md) · [変更履歴](../CHANGELOG.md)
