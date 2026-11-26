# factory-stream-simulator の開発

このリポジトリは合成データの試験に使うアプリです。[操作ガイド](README.md)と[テンプレートの書き方](docs/template-guide.md)から、対象アプリの形式と動作を確認してください。

- テンプレートを検証するときは `uv run --frozen python scripts/validate_template.py <JSON>` を使います。アプリのプレビューは `POST /api/preview` です。実行の承認が必要になったら、対象、出力先、版、件数、操作をユーザーに示してください。
- 設定確認に実環境のデータ、接続トークン、パスワード、秘密鍵を使わないでください。テスト用の一時領域と合成入力を使います。管理パスワードをコードやログから渡さず、指定のファイルから読み込みます。
- 同一条件の見本が変化していないことを、変更前後の `records` と、代表位置・異常境界のテストで確認します。
- 共通ファイルを直したら対応するリポジトリにも同じ内容を反映し、`docs/shared-components.json` の照合値を更新します。共通ファイルの範囲はマニフェストに従います。
- ひな型の変更は生成元を直してから `uv run --frozen python scripts/build_presets.py --kind stream` を使います。契約は `uv run --frozen python scripts/export_contracts.py` で作り直します。
- ヘルプは `uv run --frozen --with markdown-it-py==4.0.0 python scripts/build_help.py` で生成します。

## 変更を確認する

- `uv sync --locked` と `uv run --frozen pytest -q`。
- `node --check static/app.js`。Nodeテストがある場合は `node --test tests/*.test.cjs`。
- `uv run --frozen --with markdown-it-py==4.0.0 python scripts/build_help.py --check` と `uv run --frozen python scripts/check_shared.py`。
- CIの対応バージョンはPython 3.12、3.13、3.14です。運用設定を変えたら `docker compose config` で展開結果を確認します。
- 変更と確認項目をPRに記載します。Issueは実装と検証が揃ったものを関連づけます。
