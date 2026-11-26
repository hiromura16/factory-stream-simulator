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

## エラーの見方

| HTTP | 確認すること |
| --- | --- |
| 422 | `detail` の場所と説明を読み、JSONのキー・型・値を直します。 |
| 403 / 413 / 415 | 操作元、リクエストサイズ、Content-Typeを確認します。 |
| 409 | 実行中、接続の変更、データの競合を操作の説明と照合します。 |
| 500 | サーバー側の予期しないエラーです。再実行前に対象と履歴を確認します。 |

[設定リファレンス](settings-reference.md) · [JSONの書き方](template-guide.md)
