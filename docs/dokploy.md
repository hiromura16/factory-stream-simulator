# Dokploy配置手順

## この手順の対象と安全境界

これは検証用データを生成するアプリです。Dokploy（Docker Composeを管理する画面）へ配置するための手順であり、配置済み・会社ネットワークで動作確認済みという報告ではありません。以下のドメイン、パス、ポートは説明例です。

管理UI、操作API、/healthz、/metricsにログイン機能はありません。同一オリジン確認は認証の代わりにはなりません。最初はBIND_IP=127.0.0.1のまま、管理者だけのSSHトンネルで確認してください。公開ドメインを付ける前には、UIとAPI全体を覆う認証・アクセス制御を別途設計します。ルーターでの公開や無認証のドメイン割当ては行わないでください。

## 1. 準備するもの

- Docker Engine、Compose v2以降、十分な空きディスクを備えた検証用LinuxサーバーとDokploy。Stack（Swarm）ではなくDocker Composeを選びます。この構成はbuildを使います。
- 対象リポジトリを取得できる、必要最小限のGit連携。秘密鍵やトークンをリポジトリやこの文書へ貼りません。
- 他サービスと重ならないホストポート。コンテナ内はapp:8080です。
- 永続データを保護するバックアップ先。/dataにはDB、接続設定、暗号鍵、履歴、接続用ファイルを保存するため、単なる生成結果だけではありません。
- appはUID 1000の非特権ユーザーです。bind mount（ホストのディレクトリを渡す指定）は、そのユーザーが必要な範囲だけ読書きできるよう管理者が準備します。chmod 777で回避しません。

## 2. Dokployでサービスを作る

1. 専用のProjectとEnvironmentを作り、Docker Composeサービスを追加します。既存の運用アプリは使い回しません。
2. Gitソースにこのリポジトリを指定し、レビュー済みのブランチ/コミットを選びます。Composeファイルはリポジトリ直下のcompose.yaml、build contextは「.」です。最初は自動デプロイを無効にして手動確認します。
3. Environment欄へ.env.exampleを基に必要な値を入力します。Dokployの環境変数はComposeの補間に使われ、すべてが自動でコンテナへ入るわけではありません。env_fileで全項目を注入しないでください。
4. 後述のホスト側ファイルとディレクトリを用意してから、Composeの生成結果を管理者が非公開で確認します。秘密値を含み得るdocker compose configの全文を共有しません。
5. 現在のComposeはtraefik.enable=falseです。初回はDokployのDomainsを追加せず、SSHトンネルでアクセスします。ドメインが必要な場合、認証、Traefikラベル、共有ネットワーク、対象appの8080番を整合させる別の配備用設定が必要です。Domainsを登録するだけで保護されるとは考えないでください。
6. 準備できた検証環境だけでDeployします。ログでbuildと起動を分けて確認します。ホストbind pathはDokployの配置先サーバー上の絶対パスであり、操作しているPCのパスではありません。

## 3. 環境変数と永続化

共通項目はBIND_IP=127.0.0.1、APP_MEMORY=512m、APP_CPUS=1.0、MIN_AVAILABLE_GIB=6です。MIN_AVAILABLE_GIBはホストのメモリ余力（LinuxのMemAvailable、単位GiB）のしきい値で、ディスク容量ではありません。ディスクは別に2 GiBの固定しきい値を確認します。生成が停止したら、メモリとディスクをそれぞれ確認します。既定のapp-data named volumeを再配置で捨てないでください。サービス名/Compose project名を変更すると別ボリュームになる場合があります。

- APP_PORT=3562: 管理UI/API。MQTT_PUBLISHED_PORT=3563: 同梱ブローカーのホスト側ポート。両方loopback既定です。
- MQTT_HOST=mqtt、MQTT_PORT=1883、MQTT_TOPIC=factory/F01/telemetryを基本にします。
- MQTT_PASSWORD_FILE=/srv/simulator-example/private/mqtt-password: appとmqttが読む秘密ファイル。値を環境変数へ貼らず、UID 1000から読めるよう安全に用意します。
- MQTT_DATA_DIR=/srv/simulator-example/mqtt: UID 1000のMosquittoが読書きする永続先。MAX_SPOOL_MB=16384はoutbox上限です。
- mqttはeclipse-mosquitto:2.0.22を取得するimage-onlyサービスです。build argsもHTTP proxy変数も追加しません。appはmqttのhealthcheck成功後に起動します。

ローカル検証用には、空の作業ディレクトリで次を利用できます。スクリプトは.envや既存秘密ファイルを上書きしません。Dokployではファイルの保存先が配置先サーバーであることに注意してください。

```sh
uv sync --frozen
uv run python scripts/init_local.py --private-dir ./private --data-dir ./data --env-file .env
# .envのポートとパスを確認し、他のアプリと競合しない値に変更する
docker compose config --quiet
docker compose up -d --build
```

## 4. プロキシを3段階に分けて考える

| 段階 | 何が通信するか | 設定の場所 |
| --- | --- | --- |
| ベースイメージ取得 | Docker daemon / BuildKitがレジストリにアクセス | Docker/BuildKit管理者の設定。Compose build.argsでは直らない |
| イメージのbuild | DockerfileのRUNで依存を取得 | このComposeのapp.build.args、6種類の標準proxy変数 |
| アプリ実行 | 接続プロファイルで指定した相手へ送信 | ビルド用変数とは別。下記の実装制約を確認 |

事前取得を試す場合は、実際にbuildするDockerホスト/ビルダーで次を実行します。ただしキャッシュがあってもレジストリのメタデータ・認証確認が不要になる保証はありません。

```sh
docker pull python:3.12-slim@sha256:05a994d2344eb364cc186910f4fc8786a38215f39f00d0acc25bff33a08f4177
```

DockerfileのFROMはpython:3.12-slimをdigest sha256:05a994d2344eb364cc186910f4fc8786a38215f39f00d0acc25bff33a08f4177で固定しています。タグを変えるだけでは更新されません。証明書エラー時にTLS検証を無効化しないでください。組織CAの導入が必要なら管理者承認の別変更として扱います。

例の6行はコメントアウト済みです。利用するときだけ先頭の#を外し、大文字/小文字を対にして同じ値を指定します。プロキシ不要なら行をコメントのまま残します。明示的に空にする必要がある場合、HTTP_PROXY、HTTPS_PROXY、http_proxy、https_proxyは空欄で構いません。未設定はbuild argsの名前だけを渡す形式で、Dockerクライアントの既定値を不必要に空文字で上書きしません。明示した空欄はそのキーの既定値を上書きするため、既存のクライアント設定を使う場合は該当行を削除してください。NO_PROXY/no_proxyはlocalhost,127.0.0.1,::1を例示しています。必要な内部宛先だけを追加し、大文字・小文字を同じ値にします。プロキシが必要な場合のみ、承認された値をDokployの非公開Environment欄に設定します。例えば認証なしの説明用URLはhttp://proxy.example.test:3128です。実在するアドレス・ユーザー名・パスワードはドキュメントやコミットへ書きません。

Dockerの標準proxy build argsなのでDockerfileにARG/ENVを追加していません。一般の秘密値をbuild argsへ流用しないでください。標準proxy引数にもログ、管理画面、診断出力から漏れるリスクはあるため、URLをechoしたりログを無加工で共有したりしません。Dockerクライアントに別のproxy既定値がある場合も、実際のbuild環境を管理者が確認してください。

実行時HTTPはstream_adapter.pyのProxyHandler({})で環境プロキシを明示的に無効化しています。そのためHTTP_PROXYを実行時に追加しても対応済みにはなりません。この宛先・転送制限を変更していません。HTTPの実行時プロキシが必須なら追加設計が必要です。MQTT/Kafka/AMQP/NATSはHTTP proxyとは別方式で、WebSocketも自動で同じ設定を使うとは保証しません。実行時のproxy注入は今回追加しません。

## 5. 最小確認と障害切り分け

1. 起動状態はdocker compose ps、アプリのログはdocker compose logs --tail=100 appで確認します。実ログには宛先やデータが含まれる可能性があるため非公開で扱います。
2. サーバー自身からcurl --fail http://127.0.0.1:3562/healthzを実行します。これはWebプロセスの確認で、外部接続の成功ではありません。
3. 手元PCからSSH接続できる検証ホストなら、ssh -N -L 18080:127.0.0.1:3562 user@server.example.testで転送し、http://127.0.0.1:18080/ を開きます。SSHの正規鍵を検証し、警告を回避しません。
4. /api/infoをGETしてアプリ種類を確認します。画面でプリセットを選び、まずプレビューだけを試します。外部接続テスト/生成ボタンは実際に書込み・送信し得ます。
5. 外部配送を使わないキャプチャ方式・最小件数で生成し、outboxのpendingを確認します。この方式でpendingは失敗ではありません。その後必要な場合のみ、隔離した同梱MQTTで少量送信し、ブローカーACKと受信側保存の違いを確認します。
6. 停止はdocker compose stop。試験後もデータが必要ならdocker compose down -vやDokployのボリューム削除を実行しません。

ビルド前のFROM取得失敗はdaemon/BuildKit側、pipやapt取得失敗はbuild側、起動後の外部送信失敗は実行時の設定です。これらを一括してHTTP_PROXYで直そうとしないでください。ボリュームPermission deniedはUID/所有権、healthzだけ成功して配送失敗なら接続プロファイルや相手の受信状態を確認します。

## 6. 更新、バックアップ、テスト

実行中の生成を停止し、/dataとbind mountを整合した状態で保護してから更新します。元のコミット、イメージ、Compose設定、ボリューム名を記録し、同じ永続先を維持します。古いイメージへ戻してもDB形式が戻るとは限らないため、復元試験は隔離環境で行います。

```sh
uv sync --frozen
uv run pytest -q
python3 scripts/check_compose.py
python3 -m compileall -q app.py factorylib.py producer.py scripts
node --check static/app.js
docker compose build app
```

check_compose.pyは実.envを読まず、未設定/架空proxy値の2通りでComposeを展開してappへのbuild argsだけを確認します。コンテナ起動やネットワーク接続はしません。架空proxyでビルドが成功する試験ではありません。このCompose検証はローカルで実行します。既存CIのpytest/compile/node/docker buildは変更していません。CIにデプロイ処理はありません。実プロキシや実Dokployへの配備成功は別途確認が必要です。

## 参照

- [Dokploy Docker Compose](https://docs.dokploy.com/docs/core/docker-compose)
- [Dockerのbuild変数・標準proxy引数](https://docs.docker.com/build/building/variables/)
- [Docker daemonのproxy](https://docs.docker.com/engine/daemon/proxy/)
