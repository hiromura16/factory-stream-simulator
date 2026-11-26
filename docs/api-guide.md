# ストリーム送信のAPI

[Swagger UI](http://127.0.0.1:3562/docs)で操作ごとのリクエストと応答を確認できます。[OpenAPI JSON](http://127.0.0.1:3562/openapi.json)はAPIクライアントへの読み込み、[ReDoc](http://127.0.0.1:3562/redoc)はモデル参照に使えます。

## 最初のリクエスト

VM内でアプリに向けて実行します。別のURLで開いている場合は同じHTTPアドレスに読み替えます。

```sh
base='http://127.0.0.1:3562'
curl -fsS "$base/healthz"
curl -fsS "$base/api/info"
curl -fsS "$base/api/preview" \
  -H 'Content-Type: application/json' \
  --data-binary @docs/examples/stream-beginner.json
```

アプリの応答、種類と設定情報、合成データの一部を確認できます。`records` に見本があります。

## 操作を選ぶ

| 目的 | メソッドとパス | 結果や注意点 |
| --- | --- | --- |
| アプリの応答確認 | GET /healthz | 接続先とは別にアプリの応答を調べます。 |
| 設定スキーマを取得 | GET /api/info、GET /api/schemas | 設定の型や既定値の確認に使います。 |
| 生成値の確認 | POST /api/preview | データの一部を作り、外部には書き込みません。 |
| 接続設定を一覧・保存・確認 | GET／POST /api/connections、POST /api/connections/{identity}/test | 疎通確認は接続先へアクセスします。 |
| ひな型を一覧・保存・取得 | GET /api/presets、POST /api/presets/{identity}、GET /api/presets/{identity}/export | 同じIDに保存すると更新します。 |
| 実行を受け付ける | POST /api/runs | 202は受付です。応答の id を控え、run_id に指定します。 |
| 状態を調べる | GET /api/runs/{run_id} | 完了、失敗、停止を履歴で判断します。 |
| 停止を要求する | POST /api/runs/{run_id}/stop | 確定済みの出力が残る場合があります。 |

## このアプリで取得できる結果

`GET /api/outbox` で配送状態を読み、`POST /api/outbox/retry` で再送ジョブを作ります。`X-Expected-Connection-Revision` は開始時に接続先が変更されていないことを照合するためのヘッダーです。HTTP・MQTTなどへの実際の配送と後段処理を区別します。ローカル記録は `GET /api/outbox/capture` で新しい順にページを取得し、詳細APIで本文、`GET /api/outbox/capture/download` で1ページ分のJSON Linesを取得できます。

## 認証とPOST

管理画面の認証を設定した環境では、管理APIにも同じ認証が必要です。接続先の資格情報は環境側で管理します。


POSTには `Content-Type: application/json` を付けます。入力のない停止操作をcurlで呼ぶ場合は `--data '{}'` を付けます。ブラウザーからの変更操作は同一オリジンで実行します。

## 実行前に接続先と操作を確認する

外部の宛先への書き込み・送信、公開の開始、SQLのテーブル作成や行の変更には実行前の確認が必要です。プレビューと計画は生成・送信・書き込みを開始しません。

1. 実行パス（例 `/api/runs`、`/api/table/prepare`、`/api/start`）と送信するJSONを `{"path":"…","payload":{…}}` の形で `POST /api/operations/plan` に渡します。
2. 応答の `summary` にある操作、出力先、版、テーブル・件数を確認します。ログの開始URLに `profile_revision` を使う場合は、計画のJSONにも同じ値を指定します。
3. `confirmation_required` が `true` のときは、同じ設定と `X-Operation-Confirmation` ヘッダーで実行します。トークンは短時間で失効し、1回だけ使用できます。設定または接続先の版が変わると再確認が必要です。

HTTP 428では本文の `detail` を確認します。未指定なら計画を確認し、有効期限切れや使用済みなら人が計画を作り直します。操作・設定・接続先の版が合わない場合は、実行したい内容で計画を取り直してください。人が確認用ファイルを作るときはCLIの `plan` コマンドを使います。

## エラーの見方

| HTTP | 確認すること |
| --- | --- |
| 428 | `detail` の `code` を確認します。`confirmation_required` は未指定、`confirmation_expired` は期限切れ、`confirmation_invalid` は不明または使用済み、`confirmation_mismatch` は操作・設定・版の不一致です。 |
| 422 | `detail` の場所と説明を読み、JSONのキー・型・値を直します。 |
| 403 / 413 / 415 | 操作元、リクエストサイズ、Content-Typeを確認します。 |
| 409 | 実行中、接続の変更、データの競合を操作の説明と照合します。 |
| 500 | サーバー側の予期しないエラーです。再実行前に対象と履歴を確認します。 |

[設定リファレンス](settings-reference.md) · [JSONの書き方](template-guide.md)

[CLI・MCPの使い方](mcp.md)

確認プランと実行には同じ管理APIの権限が必要です。トークンは送信内容と接続先の取り違えを防ぎます。管理権限を持つクライアントは計画と実行の両方を呼べるため、承認者を分ける運用では管理資格情報の配布も制限してください。MCPは既定で見本・検証・参照だけを公開します。
