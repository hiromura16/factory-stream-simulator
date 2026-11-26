"""入力スキーマに、画面と設定リファレンスで使う項目名と説明を追加する。"""

from config import ConnectionProfile, RunSpec

HELP = {
    'completion_mode': ('完了通知形式', 'manifest-v2は従来の.ready.jsonを出力する既定方式です。lakehouse-products-localは信頼されたローカル領域への製品CSV・単一バッチ試験専用で、隣接SHA256 .readyを出力します。対応例の設定を使い、他形式・リモート接続・異常注入は拒否します。下流取込の完了は保証しません。'),
    "description": (
        "用途・メモ",
        "このプリセットの用途、変更した設定、実行前の条件を記録できます。選択欄にも表示します。接続先のパスワード等は記載せず、接続プロファイルへ保存してください。",
    ),
    "id": (
        "接続ID",
        "英数字・ハイフン・下線で指定する保存用ID。同じIDで保存すると更新します。例: test-oracle",
    ),
    "name": (
        "表示名",
        "一覧と実行履歴に表示する名前。業種や工場の種類を指定する必要はありません。",
    ),
    "kind": (
        "接続方式",
        "SQL Server / Oracle / PostgreSQL / MySQL / MariaDB / SQLite、ローカル / S3、MQTT / HTTP / 記録専用から、このツールで使う方式を選びます。",
    ),
    "host": (
        "ホスト",
        "接続先のDNS名またはIPアドレス。http://、ポート、ユーザー名は含めません。コンテナから到達できる名前を指定します。",
    ),
    "port": (
        "ポート",
        "空欄ならDB標準ポート、MQTTは1883またはTLS時8883。接続先に合わせてポートを指定してください。",
    ),
    "database": (
        "データベース名",
        "既存の接続先データベース。Oracleではサービス名 / SIDを使います。DB自体は自動作成しません。",
    ),
    "username": (
        "ユーザー名",
        "書き込み先専用のユーザーを推奨。HTTP Basic認証でもこの欄を使用します。",
    ),
    "password": (
        "パスワード",
        "書き込み専用の欄。空欄で保存すると同じ接続先の既存値を維持します。値は画面・JSON書き出しに戻りません。接続先を変更した場合は再入力してください。",
    ),
    "service_name": (
        "Oracle サービス名",
        "例: FREEPDB1。サービス名かSIDの片方だけを設定します。Thinドライバーで接続します。",
    ),
    "sid": (
        "Oracle SID",
        "サービス名を使用しない場合のSID。例: ORCL。サービス名と同時には指定できません。",
    ),
    "ssl_mode": (
        "通信のTLS",
        "off=平文、require=暗号化、verify=暗号化と証明書・ホスト検証。SQL Serverの同梱ドライバーはoff / require。OracleのTLSはTCPSリスナーが必要。HTTP/S3のrequire / verifyにはHTTPS URLを指定します。",
    ),
    "directory": (
        "出力ディレクトリ",
        "アプリから見えるパス。構成例では /landing またはその下の任意のディレクトリ。ホスト側のマウント元へ保存されます。FILE_ALLOWED_ROOTSで許可する領域を増やせます。",
    ),
    "sqlite_path": (
        "SQLiteファイル",
        "databases領域内の相対パス。例: trials/demo.sqlite3。SQLiteは追加サーバーなしで試せます。",
    ),
    "endpoint_url": (
        "S3互換エンドポイント",
        "R2、S3互換ストレージ等のHTTP(S) URL。AWS S3は空欄可。URLに認証情報は含めず、アクセスキー欄を使います。",
    ),
    "bucket": (
        "バケット名",
        "既存のバケットを指定します。バケットは自動作成しません。接続テストはHeadBucketのみです。",
    ),
    "prefix": (
        "S3 キー接頭辞",
        "バケット内の相対パス。例: landing/source-a。/から始めず、..を含めません。",
    ),
    "region": ("リージョン", "R2はauto、AWS S3はap-northeast-1等。署名に使用します。"),
    "access_key": (
        "アクセスキーID",
        "S3互換ストレージの認証情報。暗号化して保存します。空欄は既存値を維持。実行環境のIAM資格情報は自動使用しません。",
    ),
    "secret_key": (
        "シークレットアクセスキー",
        "アクセスキーに対応する秘密鍵。画面と書き出しでは値を返しません。",
    ),
    "session_token": (
        "セッショントークン",
        "一時的なS3認証情報を使う場合のみ指定。有効期限は利用者側で更新してください。",
    ),
    "url": (
        "送信URL",
        "HTTP受信側の完全なURL。例: http://receiver:8080/events。認証は別の欄で設定します。リダイレクトには追従しません。",
    ),
    "auth_mode": (
        "HTTP 認証方式",
        "none=認証なし、basic=ユーザー名とパスワード、bearer=Bearerトークン、api_key=指定ヘッダーにAPIキー。",
    ),
    "bearer_token": (
        "Bearerトークン",
        "Authorization: Bearer に付加する値。Bearerという接頭辞は入力しません。",
    ),
    "api_key": (
        "APIキー",
        "APIキーヘッダーに付加する値。空欄は同じ接続先の保存済み値を維持します。",
    ),
    "api_key_header": (
        "APIキーヘッダー名",
        "例: X-API-Key。APIキー認証を選択した場合だけ使用します。",
    ),
    "headers": (
        "追加HTTPヘッダー JSON",
        '例: {"X-Tenant":"sandbox"}。値はすべて暗号化・非表示。既存名にnullで値を維持、名前を削除してそのヘッダーを削除。Authorization等は認証設定を使います。',
    ),
    "topic": (
        "MQTT トピック",
        "送信先トピック。例: data/events。+と#の購読用ワイルドカードは使用できません。実行条件のトピックテンプレートで上書き可能。",
    ),
    "qos": (
        "MQTT QoS",
        "0=到達保証なし、1=少なくとも1回、2=MQTT区間で1回。再送や受信側の処理を含む全体の重複排除はrecord_keyで実装します。",
    ),
    "mqtt_version": (
        "MQTT バージョン",
        "ブローカーに合わせて3.1.1または5を選択します。",
    ),
    "client_id": (
        "MQTT クライアントID",
        "空欄なら接続ごとにランダム生成。固定する場合は他のクライアントと重複させないでください。",
    ),
    "keepalive": ("Keep Alive 秒", "MQTTブローカーへの生存確認間隔。5〜3600秒。"),
    "retain": (
        "MQTT retain",
        "有効にすると各トピックの最後のメッセージをブローカーが保持します。時系列イベントでは通常無効です。",
    ),
    "http_method": (
        "HTTP メソッド",
        "POST / PUT / PATCH。受信先APIの仕様に合わせます。",
    ),
    "content_type": (
        "Content-Type 上書き",
        "空欄ならJSONはapplication/json、NDJSONはapplication/x-ndjson。受信側が専用のMIME型を要求する場合に設定します。",
    ),
    "message_size_bytes": (
        "本文サイズの下限 (B)",
        "MQTT・ローカル記録用。JSONの末尾を空白で補います。0は無調整、上限64 KiB。元の本文は切り詰めません。",
    ),
    "duplicate_rate": (
        "重複率 (0〜1)",
        "同じ本文・トピックで1回追加送信する確率。1なら送信数は元の2倍です。",
    ),
    "delivery_attempts": (
        "1バッチの送信試行数",
        "1〜10回。失敗したバッチは永続outboxに残ります。受信済みでも応答が失われた場合は重複し得るためrecord_keyを使います。",
    ),
    "retry_backoff_ms": (
        "再試行の基準待機 ms",
        "同一バッチの再試行間隔。試行ごとに2倍、最大60秒。0は待機なし。",
    ),
    "timeout_seconds": (
        "接続・通信タイムアウト 秒",
        "1〜120秒。DBドライバー、MQTT接続と送信待機、HTTP/S3の通信に適用します。",
    ),
    "clear_secrets": (
        "削除する保存済み認証情報 JSON",
        '例: ["password"]。空欄による維持ではなく、明示的に保存値を削除したい場合に指定します。',
    ),
    "version": (
        "設定バージョン",
        "このアプリはバージョン2のプリセットJSONを使用します。",
    ),
    "connection_id": (
        "接続プロファイル",
        "この実行に使用する保存済みの接続先。プリセットにはIDだけが入ります。認証情報は接続プロファイル側で管理します。",
    ),
    "connection_revision": (
        "接続リビジョン固定",
        "通常はnull。実行開始時に接続設定の版を固定するので、実行中の接続先変更に影響されません。指定すると過去の版を使用します。",
    ),
    "run_key": (
        "実行キー",
        "再現性と重複判定の単位。英数字・ハイフン・下線。seedとシーケンスが同じなら同じrecord_idになります。別のデータ系列には別のキーを指定します。",
    ),
    "seed": (
        "乱数シード",
        "同じ実行キー・シード・シーケンス・項目名なら同じ値。0〜2147483647。",
    ),
    "rows": (
        "生成レコード数",
        "1〜1億件。SQLは行数、ファイルはレコード数、ストリームはイベント数。画像は間引き設定により少なくなります。全件をメモリには保持しません。",
    ),
    "target_rate": (
        "目標レコード数 / 秒",
        "0は速度制限なし。バッチ単位で調整する目標値です。実際の速度はDB・ディスク・通信・生成条件で変わります。まず少量で測定してください。",
    ),
    "batch_size": (
        "バッチ件数",
        "1〜10000。SQLはトランザクション、ストリームは送信単位。ファイルはファイルあたり件数を使用。メモリ量やDBパラメーター上限に合わせて内部で縮小する場合があります。",
    ),
    "start_sequence": (
        "開始シーケンス",
        "0から始まる連番。途中から再開したり、分割した負荷試験に使用します。run_key / seedも合わせると同じデータを再現できます。",
    ),
    "max_duration_seconds": (
        "実行時間の上限 秒",
        "この時間を超えると停止要求になります。進行中のDBトランザクションや通信の完了後に止まります。完了件数は履歴で確認できます。",
    ),
    "max_output_mb": (
        "出力量の上限 MiB",
        "ファイルとストリーム本文の論理上限。SQLのDB容量上限ではありません。サーバー側のメモリ・空き容量保護も常時有効です。",
    ),
    "initial_delay_seconds": (
        "開始前の待機 秒",
        "実行開始後、生成を始めるまでの待機時間。複数のソースの開始時刻をずらせます。実行時間の上限にはこの待機も含まれます。",
    ),
    "jitter_ms": (
        "送信間隔のゆらぎ ms",
        "速度調整の待機に0〜指定値の再現可能なゆらぎを加えます。目標速度が0の場合は適用しません。",
    ),
    "burst_rows": (
        "バーストのレコード数",
        "0は通常送信。例: 1000にすると1000件単位でバースト間待機を適用。バッチはこの値以下に調整します。",
    ),
    "burst_pause_ms": (
        "バースト間の待機 ms",
        "バーストの境界で加える待機。目標速度の制限と両方が適用されます。",
    ),
    "parameters": (
        "共有パラメーター JSON",
        '任意のキーとJSON値。例: {"count":100,"states":["ok","ng"]}。生成条件では$countや$statesで参照。テンプレートは{count}でも参照できます。',
    ),
    "fields": (
        "データ項目",
        "上から順に生成します。項目名・型・生成器・詳細条件を自由に変更できます。他の項目を参照する場合は参照元を先に置きます。",
    ),
    "data_type": (
        "値の型",
        "string / integer / number / decimal / boolean / datetime / json。decimalは正確な小数文字列、日時はUTC ISO形式。SQL保存時は対応する列の型に変換します。",
    ),
    "generator": (
        "生成ルール",
        "record_id=再現可能なキー、uuid=UUID、sequence=連番、integer/uniform/normal=分布、choice=重み付き選択、boolean=確率、constant=固定、template=書式、timestamp=時刻、reference/四則演算=先行項目から派生。",
    ),
    "primary_key": (
        "SQL 主キー",
        "テーブル作成時の主キー定義。upsert / update / deleteには接続先と一致する主キーが必要です。複数の項目を指定すると複合キーになります。",
    ),
    "length": (
        "文字数の上限",
        "stringの最大文字数。生成結果を検証し、新規SQLテーブルの列長にも使用します。1〜4000。",
    ),
    "precision": (
        "小数の精度",
        "decimal全体の桁数。1〜38。SQLのNUMERIC(precision,scale)に対応します。",
    ),
    "scale": (
        "小数桁数 / 丸め桁数",
        "decimalの小数桁数、numberの丸め桁数。decimalでは精度以下に指定します。",
    ),
    "minimum": (
        "最小値 / パラメーター参照",
        "integer / uniformの最小値。数値または$countのような共有パラメーター参照。",
    ),
    "maximum": (
        "最大値 / パラメーター参照",
        "integer / uniformの最大値。integerは両端を含みます。数値または$parameter。",
    ),
    "mean": ("平均", "正規分布normalの平均値。例: 50、または$value_mean。"),
    "stddev": (
        "標準偏差",
        "normalのばらつき。0なら常に平均値。0以上、または共有パラメーター参照。",
    ),
    "start": (
        "開始値 / 開始日時",
        "sequenceでは数値、timestampではタイムゾーン付きISO日時。例: 2026-11-13T09:00:00+09:00。$start_timeで参照も可能。",
    ),
    "step": (
        "増分 / 秒間隔",
        "sequenceは開始値に足す量、timestampは時刻を進める秒数。小数・負数・$parameterも指定できます。",
    ),
    "group_size": (
        "同じ連番値を使う件数",
        "sequence / timestampの増分を適用する前にまとめる件数。10なら0〜9番が同じ時刻・連番値になります。1以上または$parameter。",
    ),
    "modulo": (
        "連番値の繰り返し周期",
        "0は繰り返さない。10なら連番のインデックスが0〜9を繰り返します。sequence / timestampに適用。",
    ),
    "probability": (
        "true の確率",
        "boolean生成器のtrueの割合。0〜1、または$parameter。例: 0.02。",
    ),
    "choices": (
        "選択肢 JSON / 参照",
        '例: ["ok","warning","ng"]、または"$statuses"。型はデータ型と合わせてください。',
    ),
    "weights": (
        "選択肢の重み JSON",
        "例: [95,4,1]。選択肢と同じ個数で、0以上かつ合計が正。空の配列[]なら均等に選びます。",
    ),
    "value": (
        "固定値 / 比較値 JSON",
        '文字列は"sample"、数値は123、真偽値はtrue、空値はnull。"$parameter"で共有値を参照できます。',
    ),
    "template": (
        "文字列テンプレート",
        "例: DEV-{entity_no:05d}。先行項目、共有パラメーター、{sequence}、{record_id}を参照できます。属性アクセスや任意コードは実行しません。",
    ),
    "sources": (
        "参照元の項目名 JSON",
        '例: ["amount","unit_price"]。referenceは先頭、sum / difference / product / ratioは指定した先行項目を使用します。ratioは2項目で分母0不可。',
    ),
    "null_probability": (
        "NULL の確率",
        "生成結果をNULLに置き換える確率。0〜1。SQL主キーには指定できません。",
    ),
    "condition": (
        "条件による値の上書き",
        "有効にすると先行項目と比較し、一致する場合にthen_valueを採用。条件不一致時は通常の生成値を使用します。",
    ),
    "field": ("比較する先行項目", "すでに生成された項目名。例: status。"),
    "operator": (
        "比較方法",
        "eq=等しい、ne=異なる、gt/ge=超える/以上、lt/le=未満/以下、in=比較値の配列に含まれる。",
    ),
    "then_value": (
        "一致したときの値 JSON",
        '条件が真の場合に上書きする値。"$parameter"の参照も可能です。',
    ),
    "sql": (
        "SQL 書き込み設定",
        "スキーマ・テーブル・操作を指定。データの列定義は共通のデータ項目から作成します。",
    ),
    "schema_name": (
        "スキーマ / 所有者",
        "空欄はDBユーザーの既定スキーマ。SQL Serverは例: synthetic、Oracleは所有者名、PostgreSQLはpublic。MySQL / SQLiteでは通常空欄。スキーマ自体は自動作成しません。",
    ),
    "table": (
        "テーブル名",
        "英数字と下線の識別子。既存テーブルを選ぶ場合、生成項目と列名・型を合わせます。未作成ならDDLを確認して作成できます。",
    ),
    "operation": (
        "SQL 操作",
        "insert=追加のみ、upsert=主キーで追加/更新、update=既存行更新、delete=主キー一致行削除。DDLやDROPは実行しません。同時に同じ主キーへ書く別アプリがある場合は競合し得ます。",
    ),
    "files": (
        "ファイル設定",
        "形式・分割・命名・JSON構造・CSV仕様・画像条件を設定します。既存ファイルは上書きしません。",
    ),
    "formats": (
        "出力形式 JSON",
        '["json","csv","image"]から1つ以上。画像だけ、JSONとCSVだけ、など自由に組み合わせられます。',
    ),
    "records_per_file": (
        "ファイルあたりの件数",
        "JSON配列 / JSONL / CSVを分割する最大件数。objectモードは常に1レコード1ファイル。メモリ上限のため小さくなる場合があります。",
    ),
    "path_template": (
        "出力サブディレクトリ",
        "例: {run_key}/{job_id}。共有パラメーターも使用可能。相対パスのみ、..は禁止。job_idを含めると再実行時の衝突を避けられます。",
    ),
    "filename_template": (
        "ファイル名テンプレート",
        "例: {sequence:010d}-{record_id}。拡張子は自動付加。バッチ先頭の項目・共有値・run_key・job_idを参照可能。重複名はエラーになるので連番等を含めます。",
    ),
    "json_mode": (
        "JSON の格納形式",
        "array=配列、object=1レコード1ファイル、jsonl=1行1レコード。",
    ),
    "json_pretty": (
        "JSON の整形",
        "array / objectを字下げして見やすくします。JSONLでは無効。ファイルサイズが増えます。",
    ),
    "json_template": (
        "JSON 構造テンプレート",
        'nullなら生成行をそのまま出力。例: {"device":"$row.entity_id","metrics":{"value":"$row.value"},"key":"$meta.record_key"}。$parameters.xも利用可能。',
    ),
    "compression": (
        "JSON / CSV 圧縮",
        "noneまたはgzip。gzip時は.json.gz / .csv.gz等になり、画像・sidecar・manifestは圧縮しません。",
    ),
    "csv_delimiter": (
        "CSV 区切り文字",
        "1文字。例: , または ;。タブ区切りはJSON編集で\\tを指定できます。",
    ),
    "csv_quotechar": (
        "CSV 引用文字",
        "通常は二重引用符。1文字で指定します。区切り・改行を含む値はCSVライターが処理します。",
    ),
    "csv_quoting": (
        "CSV 引用規則",
        "minimal=必要なセル、all=全セル、nonnumeric=文字列セルを引用します。",
    ),
    "csv_header": (
        "CSV ヘッダー行",
        "有効なら最初に項目名を書き込みます。列順はデータ項目の順序です。",
    ),
    "csv_null_value": (
        "CSV のNULL表現",
        "空文字が既定。例: NULL、\\N。JSON値はJSON文字列としてセルへ保存します。",
    ),
    "csv_newline": (
        "CSV 改行コード",
        "LFまたはCRLF。読み込み先の仕様に合わせて指定します。",
    ),
    "csv_encoding": (
        "CSV 文字コード",
        "utf-8-sigはBOM付きUTF-8でExcel等向け。utf-8はBOMなし。",
    ),
    "write_sidecars": (
        "画像のメタデータ保存",
        "画像ごとの.meta.jsonにレコード・record_key・疑似欠陥ラベルを保存。画像は実物の検査写真ではなく人工パターンです。",
    ),
    "write_manifest": (
        "完了マニフェスト保存",
        "各バッチの全ファイル保存後に.ready.jsonを最後に作成します。下流はこれを取り込みの目印にできます。SHA256とサイズを記録します。",
    ),
    "image": (
        "疑似検査画像の条件",
        "格子・グラデーション・ドットの人工画像を再現可能に生成します。外部画像検索やAI APIは使用しません。",
    ),
    "width": (
        "画像の幅 px",
        "32〜4096ピクセル。大きな画像とノイズは生成負荷が増えます。",
    ),
    "height": ("画像の高さ px", "32〜4096ピクセル。出力容量と生成速度に影響します。"),
    "format": (
        "画像形式",
        "png=可逆圧縮、jpeg=非可逆圧縮。JSON / CSVと同じrecord_keyで対応付けます。",
    ),
    "pattern": (
        "人工画像パターン",
        "grid=格子、gradient=色の傾斜、dots=点群。背景色と前景色を変更できます。",
    ),
    "noise": (
        "画素ノイズ強度",
        "0はなし、1〜64は各RGB成分に加える最大ゆらぎ。CPU負荷が高くなるため小さい値から試します。",
    ),
    "defect_probability": (
        "疑似欠陥の確率",
        "0〜1。選ばれた画像に傷状の線を描き、sidecarにsynthetic_defectを記録します。",
    ),
    "every": (
        "画像生成の間引き",
        "1は全レコード、10はシーケンス番号が10の倍数のときのみ生成。大量の表データと少数画像を組み合わせられます。",
    ),
    "quality": ("JPEG 品質", "10〜100。PNGでは品質設定の効果はありません。"),
    "background": ("背景色", "#RRGGBB形式。例: #182a3a。"),
    "foreground": ("パターン色", "格子・点・グラデーション終端の#RRGGBB色。"),
    "defect_color": ("疑似欠陥の色", "傷状の線に使う#RRGGBB色。"),
    "stream": (
        "ストリーム設定",
        "メタデータの付加・本文形式・トピックを実行ごとに指定します。認証と配送方式は接続プロファイル側で管理します。",
    ),
    "envelope": (
        "配送メタデータを追加",
        "JSONオブジェクトにrecord_key / run_key / sequenceを追加。重複排除や追跡に推奨。本文が配列やスカラーの場合は無効にします。",
    ),
    "metadata_key": (
        "メタデータの項目名",
        "既定は_source。生成項目や本文テンプレートのキーと重複させないでください。",
    ),
    "http_body": (
        "HTTP 本文単位",
        "array=バッチをJSON配列、single=1件ずつ、ndjson=改行区切りJSON。MQTTは常に1イベント1メッセージです。",
    ),
    "topic_template": (
        "MQTT トピックテンプレート",
        "空欄なら接続設定のトピック。例: data/{entity_id}/events。生成項目・共有値・sequence・record_idを参照。+ / #は使えません。",
    ),
    "payload_template": (
        "送信本文のJSON構造",
        'nullなら生成行。例: {"device":"$row.entity_id","values":["$row.value"],"source":"$parameters.site"}。配列やスカラーならメタデータ追加を無効にします。',
    ),
    "task": (
        "実行タスク",
        "通常はgenerate。未配送の再送は履歴画面の操作から起動します。",
    ),
}


CONNECTION_HELP = {
    "description": (
        "用途・メモ",
        "このプリセットの用途、変更した設定、実行前の条件を記録できます。選択欄にも表示します。接続先のパスワード等は記載せず、接続プロファイルへ保存してください。",
    ),
    "sqlserver": (
        "SQL Server",
        "SQL Server認証、Windowsドメイン資格情報、Kerberos統合認証を選択できます。Entraのサービスプリンシパル・Managed Identity・アクセストークンも選べます。SQL認証は専用ユーザー、Windows資格情報はDOMAINとユーザー名・パスワードを入力。Kerberosはアプリサーバーの有効なチケット・DNS・SPNが必要で、ブラウザーのWindowsログインを自動使用するものではありません。",
    ),
    "oracle": (
        "Oracle",
        "ホストとサービス名 / SID、TNSエイリアス、接続記述子で接続。DBユーザー、Wallet、Thickモードの外部認証、OAuthトークンに対応。ThickはOracle Instant ClientとORACLE_CLIENT_MODE=thickでの起動が必要です。",
    ),
    "postgresql": (
        "PostgreSQL",
        "ユーザーとパスワード、TLSクライアント証明書、Kerberos / GSS、libpqのservice・Unixソケット・接続文字列に対応。サーバー側のpg_hba.confと認証条件を一致させます。",
    ),
    "mysql": (
        "MySQL",
        "ユーザーとパスワード、TLSクライアント証明書、事前配置したUnixソケット、接続URIに対応。caching_sha2_password等はドライバーがサーバーと交渉します。",
    ),
    "mariadb": (
        "MariaDB",
        "ユーザーとパスワード、TLSクライアント証明書、Unixソケット、接続URIに対応。外部認証はOSユーザーやサーバー側プラグインの設定が必要です。",
    ),
    "sqlite": (
        "SQLite（ローカルDB）",
        "追加サーバーが不要なファイル型DB。アプリのdatabases領域内に保存します。ユーザー認証はありません。まず動作を試す場合に適しています。",
    ),
    "local": (
        "ローカル / マウント済み共有",
        "アプリから見えるディレクトリへファイルを保存します。構成例では/landingを使用します。ローカルディスクだけでなく、ホストにマウントしてアプリへ渡した共有領域も利用できます。保存領域はFILE_ALLOWED_ROOTSで指定します。",
    ),
    "nfs": (
        "NFS（事前マウント）",
        "NFSv3/v4共有を利用環境のホストにマウントし、/network/nfs等のパスでアプリへ渡します。アプリは実際のNFSマウントであることを確認して書き込みます。NFSのUID/GID・Kerberos設定はホスト側で管理し、アプリへmount権限は与えません。",
    ),
    "smb": (
        "SMB / Samba（直接接続）",
        "Windowsファイル共有やSambaへSMB2/3で直接保存します。サーバー、共有名、共有内ディレクトリと、ユーザー / パスワード / 必要ならドメインを指定。KerberosにはチケットとGSSAPI対応環境が必要。SMB暗号化は既定で有効です。",
    ),
    "ftp": (
        "FTP / FTPS（直接接続）",
        "FTPサーバーへバイナリ転送します。TLS offはFTP、require / verifyはFTPS。Explicitは通常21、Implicitは通常990。制御ポートに加えパッシブ転送用ポートへの到達も必要です。一時ファイルを転送してから名前を確定します。",
    ),
    "sftp": (
        "SFTP（SSHで直接接続）",
        "SSHのファイル転送プロトコルで、FTPとは別方式です。通常22番。パスワードまたはSSH秘密鍵で認証し、known_hostsかSHA256でサーバーのホスト鍵を検証します。一時ファイルを転送してから名前を確定します。",
    ),
    "s3": (
        "S3互換オブジェクトストレージ",
        "R2やS3互換ストレージのバケットへオブジェクトを直接保存します。エンドポイント、バケット、キー接頭辞、アクセスキーを指定。ディレクトリへの書き込みとは異なり、下流はオブジェクトAPIで取り込みます。",
    ),
    "mqtt": (
        "MQTT（設備向けPub/Sub）",
        "ブローカーへトピック単位で1イベントずつJSONを送ります。軽量な設備通信やテレメトリー向け。受信側はトピックを購読します。QoS 1/2ではブローカーへの配送確認を待ちますが、受信アプリの処理完了は保証しません。",
    ),
    "http": (
        "HTTP（受信APIへ送信）",
        "受信側のHTTP APIへPOST / PUT / PATCHでJSONを送る方式です。単件・配列・NDJSONを選べ、Basic / Bearer / APIキーを設定できます。200 / 201 / 202 / 204を受付成功とし、accepted / failed / errorsが返れば確認します。Kafka等のブローカーは不要です。",
    ),
    "capture": (
        "キャプチャ（外部送信なし）",
        "生成したJSONをアプリの永続SQLite outboxへ記録します。ネットワークへ送信せず、生成条件・データ形式の確認用です。pendingは未配送ではなく保存のみという想定動作です。同じプロファイルを送信方式へ変更しても自動では別接続先へ再送しません。",
    ),
    "kafka": (
        "Kafka（イベントログ）",
        "Kafka互換ブローカーのトピックへ送信します。record_keyをメッセージキーにし、acks=allとidempotenceを有効化して配送確認を待ちます。再生可能な大量イベントの取り込み向け。SASL PLAIN / SCRAMとTLSに対応します。",
    ),
    "amqp": (
        "AMQP 0-9-1（RabbitMQ等）",
        "RabbitMQ等のexchange / routing keyへ永続メッセージを送信し、publisher confirmを待ちます。virtual hostと認証を設定。exchangeを空欄にするとrouting keyはキュー名です。キュー作成は明示的に有効化した場合のみ行います。",
    ),
    "nats": (
        "NATS / JetStream",
        "NATS subjectへJSONを配信します。Core NATSはサーバーまでのflushを確認し、購読者への永続配送は保証しません。JetStreamを有効にすると既存streamへの保存ACKを待ちます。ユーザー / トークン / credentialsファイルに対応します。",
    ),
    "websocket": (
        "WebSocket（常時接続）",
        'ws:// または wss://へ接続し、1イベント1テキストフレームでJSONを送ります。受信確認なしは送信完了まで、textはOK / ACK / accepted、jsonは{"accepted":1}の返答を待ちます。受信側とACK方式を合わせます。',
    ),
}

HELP.update(
    {
        "anomalies": (
            "データ異常の注入ルール",
            "正常データを生成した後、指定した行位置・割合・条件で異常を注入します。複数ルールは上から順に適用。異常を含むプリセットは意図的にDB制約や受信検証で拒否される場合があります。",
        ),
        "enabled": (
            "異常注入を有効にする",
            "無効なら、このルールまたは障害設定を適用しません。通常生成との比較に使用できます。",
        ),
        "from_row": (
            "異常の開始位置（0始まり）",
            "この実行内のレコード位置。20なら21件目から適用。start_sequenceとは別で、分割実行時は実行内の位置として評価します。",
        ),
        "to_row": (
            "異常の終了位置（含む）",
            "空欄は最後まで。例: from_row=20、to_row=29なら10件の異常期間です。",
        ),
        "when": (
            "異常を適用する条件",
            "生成後の値を比較し、一致する場合だけ異常を適用します。先に適用した異常の結果も参照できます。then_valueの指定は不要です。",
        ),
        "bypass_validation": (
            "型・必須検証を意図的に外す",
            "数値欄へ文字列、主キーへNULL等の不正値を作る場合に有効化。送信JSONは構文上有効のままですが、DBや受信側は拒否し得ます。omitはこの設定に関係なく項目を欠落させます。",
        ),
        "faults": (
            "処理障害・不正ファイルのシミュレーション",
            "この実行だけに障害を注入します。外部のサーバーやネットワーク設定は変更しません。SQLのロールバック、ファイル未完了、配送ACK消失、遅延等を再現できます。",
        ),
        "stage": (
            "障害を注入する段階",
            "before_batch: SQL/ファイルは処理前、ストリームはoutbox記録後の送信前。after_write: SQLはCOMMIT前、ファイルはマニフェスト前、ストリームは送信ACK後の配送済み記録前。",
        ),
        "action": (
            "障害の動作",
            "none=処理障害なし（不正ファイル指定だけ使う場合等）、fail=意図的な例外で停止、delay=指定時間だけ待機。ストリームの再試行を指定するとfailを再試行でき、ACK消失時には重複送信し得ます。",
        ),
        "from_batch": (
            "障害の開始バッチ（1始まり）",
            "2なら2バッチ目から注入。バッチ件数を小さくすると、正常分を先に配送・確定してから障害を発生させられます。",
        ),
        "every_batches": (
            "何バッチごとに障害を発生させるか",
            "1は毎バッチ、5は開始バッチから5バッチごと。最大回数と組み合わせて一過性・継続障害を作れます。",
        ),
        "max_occurrences": (
            "障害の最大回数",
            "1は1回だけ。0は回数制限なし。再試行時も回数に含みます。永続的な障害は0、一過性の障害は1等を指定。",
        ),
        "delay_ms": (
            "模擬遅延 ms",
            "action=delayの待機時間。実行時間の上限と停止要求を確認しながら待機します。実際の接続先を遅くする設定ではありません。",
        ),
        "artifact_mode": (
            "意図的に不正なファイルを作る",
            "ファイルツール専用。JSON切断 / 不正UTF-8 / CSVヘッダー不一致 / 画像切断 / 拡張子不一致 / マニフェストSHA256不一致。取り込み側の検知・隔離を試験します。",
        ),
    }
)

HELP.update(
    {
        "driver": (
            "DBドライバー",
            "autoは通常の同梱ドライバーを使用。SQL ServerのWindowsパスワードはpymssql、Kerberos / Entra / DSN / 検証TLSはpyodbc。SQL用イメージにはODBC Driver 18を同梱。Oracle Thin / Thickの切替にはプロセス全体の制約があります。",
        ),
        "database_auth": (
            "DB 認証方式",
            "password=DBユーザー / SQL Server認証。windows_password=DOMAINとユーザーの資格情報。kerberos=サーバー上のチケットで統合認証。client_certificate=TLS証明書。external=OS / Wallet等の外部認証。Entra系はAzure側設定、access_tokenは取得済みトークンを指定します。DBごとに対応方式を表示します。",
        ),
        "connection_method": (
            "DB 接続方法",
            "host=ホストとポート、dsn=ODBC DSN / Oracle TNS名、service=libpq service、unix_socket=事前配置ソケット、raw=暗号化保存したドライバー用接続文字列。接続先に適した方式を選択します。",
        ),
        "domain": (
            "Windows / SMB ドメイン",
            "例: CORP。ユーザー名とは分けて指定。Windows認証 / NTLMではCORP\\usernameへ組み立てます。Kerberos統合認証はチケットのprincipalを使用します。",
        ),
        "dsn": (
            "DSN / TNS / libpq service 名",
            "SQL Serverはodbc.iniのDSN名、Oracleはtnsnames.oraのTNSエイリアス、PostgreSQLはpg_service.confのサービス名。設定ファイルと必要なドライバーを配置します。",
        ),
        "connection_string": (
            "詳細接続文字列（暗号化・非表示）",
            "raw方式で使用。SQL ServerはODBC接続文字列、OracleはEasy Connectまたは接続記述子、PostgreSQLはlibpq URI / key=value、MySQL / MariaDBはmysql://user:password@host/db。値は書き出しに含めません。SQL Serverのrawはこの内容が認証・TLSを含め優先します。",
        ),
        "db_access_token": (
            "DB アクセストークン",
            "取得済みのDB向けOAuth / Entraトークン。アプリは取得・更新しません。有効期限が切れる前に接続プロファイルを更新してください。値は暗号化保存され、書き出しには含まれません。",
        ),
        "odbc_driver": (
            "ODBC ドライバー名",
            "例: ODBC Driver 18 for SQL Server。アプリサーバーにインストールされた名前と一致させます。SQL用Dockerイメージには18を同梱します。",
        ),
        "unix_socket": (
            "Unix ソケットのパス",
            "PostgreSQLはソケットのあるディレクトリ、MySQL / MariaDBは.sockファイル。ソケットをconnection-files領域へマウントして指定します。ローカルOSの認証設定・権限が必要です。",
        ),
        "config_dir": (
            "Oracle 設定ディレクトリ",
            "tnsnames.ora等を置くconnection-files内の相対パス。例: oracle。Thickでは起動時のOracle Client設定も合わせます。",
        ),
        "wallet_location": (
            "Oracle Wallet ディレクトリ",
            "connection-files内の相対パス。Thinはewallet.pem、Thickはcwallet.sso等が必要です。TLS通信とDBユーザー認証は別に設定します。",
        ),
        "wallet_password": (
            "Oracle Wallet パスワード",
            "Wallet暗号鍵のパスワード。DBユーザーのパスワードとは別です。空欄は同じ接続先の保存済み値を維持します。",
        ),
        "tls_ca_file": (
            "TLS CA 証明書ファイル",
            "connection-files領域のPEMファイル。独自CAのPostgreSQL / MySQL / Oracle / ファイル転送 / ストリーム用。空欄はシステムの信頼ストアを使用。ODBCはOSの証明書ストアを使用します。",
        ),
        "tls_cert_file": (
            "TLS クライアント証明書",
            "connection-files内のPEMファイル。mTLS / 証明書認証で使用。対応する秘密鍵も指定します。",
        ),
        "tls_key_file": (
            "TLS クライアント秘密鍵ファイル",
            "connection-files内のPEM秘密鍵。アップロードしたファイルはアクセス権600で保存され、プリセットには含まれません。",
        ),
        "tls_key_password": (
            "TLS 秘密鍵のパスフレーズ",
            "暗号化されたクライアント秘密鍵を使用する場合に指定。値は暗号化保存します。",
        ),
        "driver_options": (
            "追加ドライバー設定 JSON",
            "SQL Server: appname / tds_version。Oracle: retry_count / retry_delay / expire_time / stmtcachesize / disable_oob。PostgreSQL: application_name / options / client_encoding / target_session_attrs / gssencmode / krbsrvname / passfile。MySQL系: charset / sql_mode / init_command / program_name。認証情報は専用欄へ指定します。",
        ),
        "share": (
            "SMB 共有名",
            "例: landing。サーバー名やUNCパス全体ではなく共有名のみ。共有内の保存先はディレクトリ欄で指定します。",
        ),
        "file_auth": (
            "ファイル転送の認証",
            "password=ユーザー / パスワード、kerberos=SMBのチケット認証、ssh_key=SFTP秘密鍵、anonymous=匿名FTP。選んだ方式に対応する設定欄を使用します。",
        ),
        "ssh_private_key": (
            "SSH 秘密鍵（暗号化・非表示）",
            "OpenSSH / PEMの秘密鍵全文を貼り付けます。RSA / ECDSA / Ed25519に対応。SSH鍵ファイルのパスとどちらかを指定。秘密鍵は暗号化して保存します。",
        ),
        "ssh_key_password": (
            "SSH 秘密鍵のパスフレーズ",
            "暗号化されたSSH秘密鍵を開くパスフレーズ。SSHユーザーのログインパスワードとは別です。",
        ),
        "ssh_key_file": (
            "SSH 秘密鍵ファイル",
            "connection-files領域内の相対パス。鍵全文を入力する代わりに使用できます。",
        ),
        "ssh_known_hosts": (
            "SSH known_hosts ファイル",
            "connection-files内のknown_hosts。空欄はアプリ実行ユーザーの既存ファイル。ホスト鍵の照合に使用します。",
        ),
        "ssh_host_key_policy": (
            "SSH ホスト鍵の検証",
            "known_hosts=登録済み鍵と照合、sha256=指定フィンガープリントと照合、accept_any=検証なし。初期値はknown_hosts。自己署名のテストでもsha256で固定できます。",
        ),
        "ssh_host_key_sha256": (
            "SSH ホスト鍵 SHA256",
            "例: SHA256:Abc...。信頼できる経路で取得したサーバー鍵のフィンガープリントを入力します。末尾の=は不要。",
        ),
        "ftp_tls_mode": (
            "FTPS 接続方式",
            "explicit=接続後にAUTH TLSで暗号化、通常21番。implicit=最初からTLS、通常990番。TLS off時は通常FTPになります。",
        ),
        "ftp_passive": (
            "FTP パッシブモード",
            "有効ならクライアント側からデータ接続を開始。通常はこちらを使用します。サーバーのパッシブポート範囲へ到達できる必要があります。",
        ),
        "ftp_encoding": (
            "FTP パス文字コード",
            "ファイル名と制御通信の文字コード。通常utf-8。古いサーバーではcp932等を指定します。生成CSVの文字コードとは別です。",
        ),
        "smb_encrypt": (
            "SMB 転送暗号化",
            "既定は有効。SMB3サーバーの暗号化を要求します。古い共有サーバーで無効化する場合はネットワーク条件を確認してください。",
        ),
        "nfs_expected_source": (
            "NFS マウント元の確認",
            "任意。例: nas.example:/exports/landing。指定すると実際のマウント元と一致することを確認します。マウント操作自体はホストで行います。",
        ),
        "kafka_sasl_mechanism": (
            "Kafka SASL 認証",
            "none=クライアント証明書または認証なし、PLAIN / SCRAM-SHA-256 / SCRAM-SHA-512=ユーザーとパスワード。TLSと組み合わせてSASL_SSLになります。",
        ),
        "bootstrap_servers": (
            "Kafka ブートストラップサーバー",
            "例: broker-a:9092,broker-b:9092。空欄ならホストとポートを使用。各ブローカーのadvertised.listenersにも到達できる必要があります。",
        ),
        "amqp_virtual_host": (
            "AMQP virtual host",
            "RabbitMQ等の論理的な接続領域。既定は/。ユーザーにこのvhostの書き込み権限が必要です。",
        ),
        "amqp_exchange": (
            "AMQP exchange",
            "既存exchangeの名前。空欄はdefault exchangeで、トピック欄の名前がキュー名になります。配送はmandatory + publisher confirmで確認します。",
        ),
        "amqp_declare_queue": (
            "AMQP キューを作成",
            "exchangeが空の場合だけ、配送先名のdurableキューを作成します。既存キューと属性が異なると接続エラーになります。",
        ),
        "nats_token": (
            "NATS トークン",
            "NATSのトークン認証を使う場合の値。ユーザー / パスワードとの重複指定は避けてください。暗号化保存されます。",
        ),
        "nats_credentials_file": (
            "NATS credentials ファイル",
            "JWT / NKey認証用の.credsファイル。connection-files内のパス。ユーザー / トークンを使わない場合に指定します。",
        ),
        "nats_jetstream": (
            "NATS JetStream 保存確認",
            "有効ならJetStream streamへの保存ACKを待ちます。対象subjectを受け入れるstreamを事前作成してください。無効はCore NATS配信です。",
        ),
        "websocket_ack": (
            "WebSocket 受信ACK",
            'none=フレーム送信まで、text=OK / ACK / acceptedを待つ、json={"accepted":1}を待つ。noneでは受信アプリの処理完了を確認しません。',
        ),
        "websocket_subprotocols": (
            "WebSocket サブプロトコル JSON",
            '例: ["events.v1"]。受信側が要求するサブプロトコル名。空の配列は指定なしです。',
        ),
    }
)
HELP["topic"] = (
    "配送先トピック / subject / routing key",
    "MQTTは例data/events、Kafkaはdata-events、NATSはdata.events、AMQPはrouting keyまたはキュー名。HTTP / WebSocket / キャプチャでは配送先名としては使用しません。実行条件でテンプレートを指定できます。",
)
HELP["topic_template"] = (
    "配送先名のテンプレート",
    "空欄は接続プロファイルの配送先名。MQTT / Kafka / NATS / AMQPのトピック・subject・routing keyを項目ごとに変えられます。例: data.{entity_id}。各プロトコルの命名規則に合わせます。",
)
HELP["kind"] = (
    "接続方式",
    "このツールで利用できる接続方式を選択します。方式ごとの用途・認証・送信完了の判定は下に表示されます。",
)


HELP.update(
    {'avro_codec': ('Avro圧縮', 'nullは圧縮なし、deflateは圧縮。型とNULL許可は項目定義に従います。'),
     'avro_namespace': ('Avro名前空間',
                        '例: factory.source。日時はtimestamp-micros、小数はdecimal '
                        'logical typeを使用。'),
     'avro_record_name': ('Avroレコード名', 'Avroスキーマのrecord名。英数字と下線で指定します。'),
     'parquet_compression': ('Parquet圧縮',
                             'snappy / gzip / zstd / '
                             'none。型はデータ定義から固定し、日時はUTC、JSON項目はJSON文字列で保存します。'),
     'pdf_columns': ('PDF出力列 JSON',
                     '空の配列は全列。指定するとその順序の列だけをレポートに出力。例: '
                     '["entity_id","value","status"]。'),
     'pdf_font_size': ('PDF文字サイズ', '5〜14pt。日本語のCIDフォントを使用し、列幅に合わせて折り返します。'),
     'pdf_landscape': ('PDFを横向きにする', '列数が多い表には横向きA4を推奨。全レコードを複数ページへ出力します。'),
     'xlsx_allow_formulas': ('Excelの数式を許可',
                             '無効なら=で始まる値も文字列として保存。ユーザーが意図して数式を生成する場合だけ有効にします。'),
     'xlsx_sheet': ('Excelシート名',
                    '31文字以下。Excelで使用できない : / \\ ? * [ ] は含めません。'),
     'xml_root': ('XMLルート要素',
                  '例: records。日本語データはUTF-8、NULLはnull=true属性で表現します。'),
     'xml_row': ('XMLレコード要素', '例: record。データ項目名を子要素に使用し、XML特殊文字はエスケープします。')}
)


def annotated_schemas(kind=None):
    """入力スキーマに日本語の説明を加え、接続種別を現在のアプリに絞る。"""
    from config import ALLOWED_KINDS

    result = {
        "run": RunSpec.model_json_schema(),
        "connection": ConnectionProfile.model_json_schema(),
    }

    def annotate(schema):
        for name, prop in schema.get("properties", {}).items():
            if prop.get("x-editor-only"):
                continue
            title, description = HELP[name]
            prop.update(title=title, description=description)
        for child in schema.get("$defs", {}).values():
            annotate(child)

    for schema in result.values():
        annotate(schema)
    result["run"]["$defs"]["FieldRule"]["properties"]["name"].update(
        title="項目名",
        description="英字または下線で始まる英数字・下線、63文字まで。SQLの列名・CSVヘッダー・JSONキーになります。項目間参照にもこの名前を使います。",
    )
    definitions = result["run"]["$defs"]
    definitions["AnomalyRule"]["properties"]["field"].update(
        title="異常を注入する項目名",
        description="生成するデータ項目の名前。正常行の生成後に変更するため、先行項目だけでなく任意の生成項目を指定できます。",
    )
    definitions["AnomalyRule"]["properties"]["operation"].update(
        title="異常の作り方",
        description="set=値を置換、add=加算、multiply=倍率、ramp=開始位置から増加するドリフト、freeze=開始位置の値に固着、null=NULL、copy_from=指定位置の値をコピー、timestamp_shift=秒単位の時刻ずらし、omit=項目自体を欠落。加算・倍率・ドリフトは元の値が欠測・非数値の行では適用しません。",
    )
    definitions["AnomalyRule"]["properties"]["value"].update(
        title="置換値 / 増分 / 倍率 / 秒数 JSON",
        description="setの値、add/rampの増分、multiplyの倍率、timestamp_shiftの秒数、copy_fromの実行内コピー元位置（0始まり）を指定。$parameter参照も可能。freeze/null/omitでは使いません。",
    )
    definitions["AnomalyRule"]["properties"]["every"].update(
        title="何件ごとに異常を適用するか",
        description="開始位置から何件ごとに適用するか。1は全件、10は10件ごと。probabilityと組み合わせて断続的な異常を作ります。",
    )
    definitions["AnomalyRule"]["properties"]["probability"].update(
        title="異常が発生する確率",
        description="適用位置・条件を満たした行に対する0〜1の確率。同じrun_keyとseedなら再現可能です。",
    )
    comparison = (
        "eq/neは一致・不一致、gt/ge/lt/leは大小比較、inは配列に含まれるかを判定します。"
        "大小比較では欠測値や比較できない型は不一致になります。"
        "inの比較値はJSON配列、または配列を参照する共有パラメーターを指定します。"
    )
    for key in ("Condition", "Predicate"):
        definitions[key]["properties"]["operator"]["description"] = comparison
    if kind:
        result["connection"]["properties"]["kind"]["enum"] = sorted(ALLOWED_KINDS[kind])
        result["connection"]["properties"]["kind"]["description"] = "\n\n".join(
            CONNECTION_HELP[k][0] + ": " + CONNECTION_HELP[k][1]
            for k in sorted(ALLOWED_KINDS[kind])
        )
    return result
