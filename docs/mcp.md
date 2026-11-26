# CLIとMCPから操作する

CLIはこのリポジトリのアプリを操作します。MCPは1プロセスで、起動時に登録した複数のFactoryアプリを操作できます。

## CLI

ホストからは `APP_PORT` 環境変数、リポジトリの `.env` の `APP_PORT`、アプリの既定ポートの順でループバックに接続します。別のURLを使うときは `--url` で指定します。

```bash
uv run --frozen python cli.py presets
uv run --frozen python cli.py export --preset-id PRESET_ID > template.json
uv run --frozen python cli.py validate template.json
uv run --frozen python cli.py validate --compact template.json > minimal.json
uv run --frozen python cli.py preview --spec template.json
uv run --frozen python cli.py status
```

`validate` はローカルで検証し、接続せずに失敗時の場所と理由を返します。ファイル名に `-` を指定すると標準入力からJSONを読みます。SQL・ファイル生成・ストリーム送信のジョブは `status --run-id ID` で個別の状態を取得でき、`stop --run-id ID` で停止できます。他のアプリの停止は実行IDなしの `stop` を使います。

アプリの管理認証を有効にしている場合は `ADMIN_USERNAME` と `ADMIN_PASSWORD_FILE` を環境変数で指定します。CLIは従来の `APP_PASSWORD_FILE` にも対応します。ユーザー名とパスワードをURLに含めず、HTTPSまたはループバックを使ってください。CLIとMCPはHTTPリダイレクトを追跡しません。

## MCPの登録

運用者がアプリのURLをJSONファイルに登録します。種別は `sql`、`files`、`stream`、`equipment`、`api`、`historian`、`logs`、`identification` です。必要なアプリだけを登録します。次は2アプリを登録する例です。

```json
{
  "apps": {
    "sql": {
      "url": "http://127.0.0.1:3560",
      "admin_username": "operator",
      "admin_password_file": "private/sql-admin-password",
      "confirmation_file": "private/sql-start-confirmation"
    },
    "files": { "url": "http://127.0.0.1:3561" }
  }
}
```

相対パスはこの設定ファイルを置いた場所が基準です。管理認証を使わない登録先では、ユーザー名とパスワードファイルを省略します。1つの登録先に限り、両方の代わりに `"use_admin_env": true` を指定して管理認証の環境変数を使えます。

MCPクライアントに標準入出力のサーバーとして登録します。絶対パスは実際の配置に置き換えます。標準ライブラリのみで動作するため、ブリッジ自体の依存パッケージはありません。アプリは別途起動してください。

```json
{
  "mcpServers": {
    "factory-apps": {
      "command": "python3",
      "args": [
        "/absolute/path/to/factory-repository/mcp_server.py",
        "--config",
        "/absolute/path/to/factory-mcp.json"
      ]
    }
  }
}
```

| ツール | 内容 |
| --- | --- |
| `list_presets` | 登録したアプリのひな型のIDと名前を表示 |
| `get_preset` | `preset_id` を指定して設定JSONを取得 |
| `validate_template` | `spec` の型や項目をアプリで検証 |
| `preview` | `spec` の見本を取得 |
| `get_status` | 状態・時刻・件数を取得 |
| `start` | `spec` の見本を既定で表示。実開始には `execute: true` と人が発行した確認ファイルが必要 |
| `stop` | `execute: true` で停止。ジョブ形式では `run_id` が必要 |

すべてのツールで `app` に登録済み種別を指定します。MCPの検証とプレビューは見本APIを使用し、書き込みや送信を開始しません。オフラインの検証はCLIを使います。状態の応答からは、アプリ設定、プロトコルや接続の詳細、エラー本文を除きます。MCPには確認トークンの発行、任意URLへのリクエスト、実行環境のファイル参照のツールはありません。

## 確認が必要な実行

1. `preview` で見本を確認します。
2. 人が開始先、接続の版、処理内容を確認するために、CLIで計画を作ります。確認ファイルは、運用者とMCPが管理する専用のディレクトリに置きます。

   ```bash
   uv run --frozen python cli.py plan --spec template.json \
     --confirmation-file private/start-confirmation
   ```

3. 表示された計画を確認したら、同じ設定と確認ファイルで開始します。

   ```bash
   uv run --frozen python cli.py start --spec template.json \
     --confirmation-file private/start-confirmation
   ```

MCPで開始する場合は、起動時に登録した `confirmation_file` と同じパスへ計画のトークンを書き出し、その後に人が許可して `start` を `execute: true` で呼びます。確認トークンの値をチャットや引数に貼り付ける必要はありません。トークンはファイル（権限0600）にだけ保存されます。設定内容と接続先の版は計画と実行で揃えてください。ログの固定プロファイル版が必要なときはCLIの計画・開始に `--profile-revision` を付け、MCPなら開始時に同じ `profile_revision` を指定します。CLIの計画は、通常の開始に確認が不要な場合も確認トークンを要求します。MCPの実開始は確認APIを備えたアプリに限ります。

### 同じ確認ファイルで繰り返す

MCPでアプリが開始を受け付けると、その要求に使用した確認ファイルを自動で削除します。次の実行では、人が同じパスに `plan` を実行して、改めて計画を確認します。

期限切れ・設定の違いで拒否された場合や、通信が切れて結果が分からない場合、確認ファイルは残ります。先に `status` または `get_status` で実行の有無を確かめてください。実行する必要がある場合は、人が次のコマンドで同じパスに再発行します。

```bash
uv run --frozen python cli.py plan --replace --spec template.json \
  --confirmation-file private/start-confirmation
```

再発行の途中で別の確認ファイルが保存された場合は、そのファイルを保護するために失敗します。ファイルを作り直した人に内容を確認してください。

SQLのテーブル準備には `plan --operation prepare` と `prepare`、ストリームの再送には `plan --operation retry` と `retry` を使います。確認を要求する条件と拒否理由は、それぞれのアプリのOpenAPIを参照してください。

仕様は [MCP 2025-11-25のstdio](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports) と [toolsの契約](https://modelcontextprotocol.io/specification/2025-11-25/server/tools) に従います。起動時に 2025-11-25 または 2025-06-18 をネゴシエートします。
