# AI向けテンプレート作成ハーネス

このファイルと末尾の依頼プロンプトをAIに渡し、**ストリーム送信（`factory-stream-simulator`）** の合成データのひな型を作ります。[設定リファレンス](settings-reference.md)で使えるキーを調べ、作ったJSONはアプリの見本と少量の試験で確認します。[自分でJSONを書く手順](template-guide.md)も使えます。

実データ、接続資格情報、非公開のホスト名をAIへの依頼や共有のひな型に含めないでください。

---

## 0. 人間向け：使い方

1. **決めておくこと**（AIに伝える内容）
   - どのツールで使うか（SQLに入れる / ファイルを置く / MQTT等で送る / 設備・API・ヒストリアン・ログ・RFIDとして読ませる）
   - どんな業務データか（例：「プレス機6台の温度・回転数・状態」「ERPの製造指図」）
   - 件数・時間間隔・期間（例：「1分ごと、1日分」「200件」）
   - 入れたい異常（例：「途中で温度が急上昇」「10%欠測」「同じ伝票番号の重複」）
   - SQLなら投入先テーブル名と書き込み方法（insert / upsert …）
2. AIに **このファイル＋§10のプロンプト** を渡す。
3. AIが返したJSONをファイル（例 `my-template.json`）に保存。
4. アプリ画面の「プリセット / JSON」（Family B は「設定の保存・JSON」）に貼り付け →「JSONを画面に適用」→「見本を見る」。
   - またはコマンドで検証（§8）。エラーが出たら、**エラー文をそのままAIに貼って「直して」と頼む**（§8.3 の表をAIが参照します）。
5. 問題なければ「ひな型として保存」。

---

## 1. AIに渡す作成ルール

AIはテンプレートを出力する前に、次をすべて守ること。

1. **JSON本体は1つのコードブロック**に入れ、説明はブロック外に書く。JSON内にコメント（`//`、`/* */`）や末尾カンマを書かない。
2. **未知のキーは1つも書かない**（全モデルが `extra="forbid"`。`"min"`、`"max"` など未定義のキーはエラー）。用途は `name` と `description`、編集用の注記は `_comment` に書く。必要なら `$schema` で対象の契約を指定する。
3. **最小構成で書く**。使わないセクション（Family A の `files` / `stream`、Family B の不要セクション）は**省略**する。省略すると既定値が入る。別の環境では接続先IDと版を選び直す（§5.6）。
4. 項目名（`fields[].name`）は **英字または `_` で始まる英数字・`_` のみ、63文字まで**。日本語・ハイフン・空白は不可。大文字小文字違いの重複も不可。
5. **`fields` は上から順に生成される**。他の項目を参照する項目（template / reference / sum / difference / product / ratio / condition）は、参照先より**下**に置く。
6. 各項目に **`data_type` を必ず明示**する（取り込み先が必要とする型を伝える）。
7. 日時は **タイムゾーン付きISO 8601**（例 `2026-12-01T08:00:00+09:00`）。出力は UTC（`+00:00`）に変換される。
8. 共有値は `parameters` に置き、数値・選択肢・日時の欄では `"$名前"` で参照できる（文字列全体が `$名前` の場合のみ）。テンプレート文字列内では `{名前}` で参照する。
9. §7 の境界条件を確認する。
10. 出力後に §8.2 の自己チェックリストを1項目ずつ確認し、結果を短く報告する。

---

## 2. ツールと形式の対応

| ツール（リポジトリ） | 用途 | 形式 | トップの形 | 使うセクション |
|---|---|---|---|---|
| factory-sql-data-loader | DBへ投入（SQL Server/Oracle/PostgreSQL/MySQL/MariaDB/SQLite） | **A** | RunSpec（`version: 2`） | `fields`, `parameters`, `anomalies`, `faults`, **`sql`** |
| factory-file-generator | ファイル出力（JSON/CSV/画像/XLSX/XML/Parquet/Avro/PDF） | **A** | RunSpec（`version: 2`） | `fields`, `parameters`, `anomalies`, `faults`, **`files`** |
| factory-stream-simulator | 送信（MQTT/Kafka/AMQP/NATS/WebSocket/HTTP） | **A** | RunSpec（`version: 2`） | `fields`, `parameters`, `anomalies`, `faults`, **`stream`** |
| factory-equipment-simulator | 設備として読まれる（OPC UA / Modbus TCP） | **B** | Spec（`version: 1`） | `generator`, **`equipment`** |
| factory-api-simulator | 業務APIとして取得される（REST / OData） | **B** | Spec（`version: 1`） | `generator`, **`business`** |
| factory-historian-simulator | 履歴DBとして取得される（期間・集計） | **B** | Spec（`version: 1`） | `generator`, **`history`** |
| factory-log-simulator | ログを出力（ファイル / Syslog） | **B** | Spec（`version: 1`） | `generator`, `batch_size`, **`logs`** |
| factory-identification-simulator | RFID・バーコード・作業者イベント | **B** | Spec（`version: 1`） | `generator`, `batch_size`, **`identification`** |

- **形式A**：`fields` などがトップレベルにある。
- **形式B**：トップに周期などの設定があり、データ項目は `generator` の中（中身は形式Aと同じ書き方）。
- 接続先・認証・送信先は **テンプレートに含めない**（画面の「接続先」「公開・出力設定」で別管理。テンプレートは `connection_id` / `profile_id` で参照するだけ。既定は `"default"`）。

---

## 3. 共通：データ項目（`fields`）の書き方 ― 最重要

`fields` は1〜100個。各項目は次のキーを持てる（**ここに無いキーはエラー**）。

| キー | 型・範囲 | 既定 | 意味 |
|---|---|---|---|
| `name` | 英字/`_`始まり英数字`_`、≤63 | 必須 | 列名・JSONキー・CSVヘッダー |
| `data_type` | `string` `integer` `number` `decimal` `boolean` `datetime` `json` | `string` | 出力の型。**必ず明示** |
| `generator` | §3.1 の16種 | `constant` | 値の作り方 |
| `primary_key` | bool | false | 主キー（SQLのupsert/update/deleteで必須。NULL不可） |
| `length` | 1〜4000 | 255 | string の最大文字数（超えるとエラー。SQLの列長にもなる） |
| `precision` | 1〜38 | 18 | decimal の全桁数 |
| `scale` | 0〜18（≤precision） | 3 | decimal の小数桁。**number は この桁数に丸められる** |
| `minimum` / `maximum` | 数値 or `"$param"` | 0 / 100 | integer・uniform の範囲（integerは両端含む） |
| `mean` / `stddev` | 数値 or `"$param"` | 50 / 5 | normal の平均・標準偏差（stddev≥0） |
| `start` | 数値 / ISO日時 / `"$param"` | 0 | sequence の開始値、timestamp の開始日時 |
| `step` | 数値 or `"$param"` | 1 | sequence の増分、timestamp の秒間隔（小数・負も可） |
| `group_size` | 整数≥1 or `"$param"` | 1 | 何件ごとに sequence / timestamp を1つ進めるか |
| `modulo` | 整数≥0 or `"$param"` | 0 | 0以外なら sequence / timestamp の進みを周期化（0〜modulo-1 を繰り返す） |
| `probability` | 0〜1 or `"$param"` | 0.5 | boolean が true になる確率 |
| `choices` | 配列 or `"$param"` | [] | choice の候補（文字列・数値・真偽・オブジェクト可） |
| `weights` | 数値配列（**`$param` 不可**） | [] | choice の重み。choices と同じ長さ。空なら均等 |
| `value` | 任意 or `"$param"` | null | constant の値 |
| `template` | 文字列 ≤2048 | `"{sequence}"` | template の書式（§3.3） |
| `sources` | 項目名の配列 ≤32 | [] | reference / sum / difference / product / ratio の参照元（先に定義された項目） |
| `null_probability` | 0〜1 | 0 | この確率で NULL にする（主キーには指定不可） |
| `condition` | オブジェクト or null | null | 条件による値の上書き（§3.4） |

### 3.1 生成器（`generator`）早見表

| generator | 使うキー | 推奨 data_type | 出力例 | 注意 |
|---|---|---|---|---|
| `record_id` | なし | string（length≥32） | `"2f2b3035516eda05dad9f4403a410d7b"` | `run_key`+`seed`+通番から決まる32桁16進。**ツールをまたいでも同じ条件なら同じ値**（突合キーに使える） |
| `uuid` | なし | string（length≥36） | `"696261e0-aaf5-5f73-..."` | 決定的なUUID v5 |
| `sequence` | start, step, group_size, modulo | **integer**（小数なら number） | `0, 1, 2…` | 型を明示して入力先と揃える |
| `integer` | minimum, maximum | integer | `37` | 両端含む |
| `uniform` | minimum, maximum | number / decimal | `11.25` | |
| `normal` | mean, stddev | number / decimal | `66.6` | **integer にすると「整数ではありません」エラー** |
| `choice` | choices, weights | 候補の型に合わせる | `"RUN"` | weights は数値配列のみ |
| `boolean` | probability | boolean | `true` | |
| `constant` | value | 値の型に合わせる | `"125.50"` | value 省略で常に null |
| `template` | template | string | `"EQ-009"` | §3.3 |
| `timestamp` | start, step, group_size, modulo | **datetime** | `"2026-11-30T23:00:00+00:00"` | start にタイムゾーン必須。出力はUTC |
| `reference` | sources（1つ） | 参照元と同じ | | 先行項目の値をコピー |
| `sum` | sources（1つ以上） | number / integer / decimal | | 合計 |
| `difference` | sources（2つ以上） | 同上 | | 1つ目 − 残りの合計 |
| `product` | sources | 同上 | | 積 |
| `ratio` | sources（**ちょうど2つ**） | number / decimal | `0.9468` | 分母が0だとエラー → 分母の最小値を1以上に |

- integer 型で受けられるのは結果が整数のときだけ（例：`difference` の結果 `89.0` は OK、`ratio` は通常NG）。
- decimal は精度を保つ**文字列**で出力される（例 `"125.50"`）。SQLでは NUMERIC(precision, scale)。
- number は `scale`（既定3）桁に丸められる。小数4桁以上が必要なら `scale` を指定。

### 3.2 共有パラメーター（`parameters`）

```json
"parameters": {"equipment_count": 10, "lines": ["L1","L2","L3"], "start_time": "2026-12-01T08:00:00+09:00"}
```
- 最大100キー。値は任意のJSON（数値・文字列・配列・オブジェクト）。
- 参照方法：
  - 数値・日時・選択肢・値の欄 → `"maximum": "$equipment_count"`、`"choices": "$lines"`、`"start": "$start_time"`（**文字列全体が `$名前`** のときだけ参照になる。`"L-$x"` のような埋め込みは不可）
  - template の中 → `"{equipment_count}"`
  - JSON構造テンプレートの中 → `"$parameters.lines"`
- 未定義の `$名前` は「パラメーター ○○ が定義されていません」エラー。
- `parameters` を省略すると既定値（`entity_count`, `statuses`, `value_mean`, `value_stddev`, `start_time`）が入る。自分の項目で使わないなら無害。

### 3.3 文字列テンプレート（`generator: "template"`、ファイル名・トピック・ログ本文）

- 参照できる名前：**それより上に定義した項目**、`parameters` のキー、`sequence`（通番）、`record_id`。
- 書式指定は **短い数値書式だけ**：`{no:05d}`（ゼロ埋め整数）、`{v:.2f}`（小数2桁）、`{s}`。`,` `x` `>` `!r` `.attr` `[0]` などは不可。
- **`:d` を使う項目は `data_type: "integer"` にする**（string や number だと「生成ルールの型・範囲・日時を確認してください」エラー）。
- **`:.2f` は number / integer 項目にのみ**。decimal は文字列なので `:.2f` 不可。
- datetime 項目を埋め込むと UTC の ISO 文字列になる。
- `{` `}` を文字として出したい場合はテンプレートで扱えないので、constant を使う。

### 3.4 条件による上書き（`condition`）

```json
{"name":"stop_reason","data_type":"string","generator":"constant","value":null,
 "condition":{"field":"status","operator":"eq","value":"STOP","then_value":"MAINTENANCE"}}
```
- `field`：**それより上の項目**。`operator`：`eq` `ne` `gt` `ge` `lt` `le` `in`。`value` / `then_value` は `"$param"` 可。
- `in` の `value` は **配列**にする（例 `["STOP","ALARM"]`）。
- 評価順：生成 → 条件 → `null_probability` → 型チェック。
- **`gt/ge/lt/le` で比較する項目に `null_probability` を付けない**（§7）。

### 3.5 書き方の型（コピー用スニペット）

```json
{"name":"id","data_type":"string","generator":"record_id","primary_key":true,"length":64}
{"name":"seq_no","data_type":"integer","generator":"sequence","start":1}
{"name":"machine_no","data_type":"integer","generator":"integer","minimum":1,"maximum":5}
{"name":"machine_id","data_type":"string","generator":"template","template":"M-{machine_no:02d}","length":8}
{"name":"status","data_type":"string","generator":"choice","choices":["RUN","IDLE","STOP"],"weights":[90,8,2],"length":8}
{"name":"temperature","data_type":"number","generator":"normal","mean":65,"stddev":2.5,"scale":1}
{"name":"price","data_type":"decimal","generator":"uniform","minimum":100,"maximum":200,"precision":12,"scale":2}
{"name":"is_defect","data_type":"boolean","generator":"boolean","probability":0.03}
{"name":"good_qty","data_type":"integer","generator":"difference","sources":["output_qty","reject_qty"]}
{"name":"event_time","data_type":"datetime","generator":"timestamp","start":"2026-12-01T08:00:00+09:00","step":60}
{"name":"attrs","data_type":"json","generator":"constant","value":{"vendor":"ACME","rev":2}}
```

---

## 4. 共通：異常ルール（`anomalies`）

正常値を作った**後**に、上から順に適用される（最大64個）。

| キー | 型 | 既定 | 意味 |
|---|---|---|---|
| `name` | 1〜120文字 | `"異常注入"` | 表示名（画面・履歴に出る） |
| `enabled` | bool | true | |
| `field` | 項目名 | 必須 | 対象項目（定義済みであること） |
| `operation` | 下表 | `set` | |
| `value` | 任意 / `"$param"` | null | 操作ごとの値 |
| `from_row` | 0以上 | 0 | 開始位置（**0始まり、実行内の位置**） |
| `to_row` | null or ≥from_row | null | 終了位置（含む）。null は最後まで |
| `every` | ≥1 | 1 | 何件おきに適用 |
| `probability` | 0〜1 | 1 | 適用確率（seedで再現） |
| `when` | `{field, operator, value}` or null | null | 生成済みの行に対する条件 |
| `bypass_validation` | bool | false | true にすると型チェックを迂回（数値欄に文字列を入れる等） |

| operation | value | 効果 | 使ってよい項目 |
|---|---|---|---|
| `set` | 置換値 | 値を置き換え | 何でも（型が合わない値は `bypass_validation: true`） |
| `add` | 増分 | 加算 | **数値項目、かつ NULL にならない項目のみ** |
| `multiply` | 倍率 | 乗算（単位違い×1000など） | 同上 |
| `ramp` | 1件あたり増分 | from_row から徐々に増える（ドリフト） | 同上 |
| `freeze` | 不要 | from_row の値に固着 | 何でも |
| `null` | 不要 | NULL にする | 主キー以外 |
| `copy_from` | **コピー元位置（整数、必須）** | 指定位置の値をコピー（重複伝票など） | 何でも |
| `timestamp_shift` | 秒（負も可） | 時刻をずらす（遅延・未来時刻） | datetime 項目 |
| `omit` | 不要 | 項目そのものを消す（キー欠落） | 主キー以外 |

- 「位置」は形式Aでは**実行内のレコード番号**。形式Bでは **tick 番号ではなくレコード通番**（設備・ヒストリアンは1tickで台数分進む。例：設備6台なら from_row 120 ≒ 20tick目。ログ・RFIDは1tickで `batch_size` 件進む）。
- 異常の「正解ラベル」はデータに混ぜず、`description` に「何件目〜何件目に何を入れたか」を書いておく。

### 4.1 処理障害（`faults`・形式Aのみ）

データではなく処理そのものを止める・遅らせる設定。**意図的に failed で終わる**ことがある。

```json
"faults": {"enabled": true, "stage": "before_batch", "action": "fail", "from_batch": 2, "every_batches": 1, "max_occurrences": 1, "delay_ms": 1000, "artifact_mode": "none"}
```
- `stage`: `before_batch` / `after_write`、`action`: `none` / `fail` / `delay`、`from_batch` は**1始まり**。
- `artifact_mode`（壊れたファイルを作る）は **file-generator 専用**：`truncate_json` `invalid_json_utf8` `csv_header_mismatch` `truncate_image` `wrong_image_extension` `manifest_checksum_mismatch`。他ツールで指定するとエラー。
- 形式B（設備〜RFID）では `generator.faults` は**無視される**。各セクションの専用異常（`business.fault`、`equipment.offline_from_tick` 等）を使う。

---

## 5. 形式A（SQL / ファイル / ストリーム）

### 5.1 トップレベル

| キー | 範囲 | 既定 | 意味 |
|---|---|---|---|
| `version` | 2 | 2 | 省略可 |
| `name` | 1〜120文字 | `"カスタムデータ"` | 表示名 |
| `description` | ≤1000文字 | `""` | 想定・異常の正解・確認事項（`\n` で改行） |
| `connection_id` | `[A-Za-z0-9_-]{1,64}` | `"default"` | 接続先ID（画面で登録したもの） |
| `connection_revision` | null | null | **null のままにする** |
| `run_key` | `[A-Za-z0-9_-]{1,64}` | `"trial-001"` | 系列名。record_id の元。**同じ run_key+seed なら同じデータ** |
| `seed` | 0〜2147483647 | 42 | 乱数シード |
| `rows` | 1〜100,000,000 | 30 | 件数 |
| `target_rate` | 0〜1,000,000 | 10 | 1秒あたり件数（0=制限なし） |
| `batch_size` | 1〜10000 | 1000 | まとめて書く件数（SQLのCOMMIT単位など） |
| `start_sequence` | 0〜 | 0 | 通番の開始（続きから作る時） |
| `max_duration_seconds` | 1〜86400 | 3600 | 時間上限 |
| `max_output_mb` | 1〜 | 1024 | 容量上限 |
| `initial_delay_seconds` | 0〜3600 | 0 | 開始待ち |
| `jitter_ms` | 0〜60000 | 0 | 送信間隔のゆらぎ |
| `burst_rows` / `burst_pause_ms` | | 0 / 0 | N件ごとにM ms休む |
| `parameters` | ≤100キー | 既定あり | §3.2 |
| `fields` | 1〜100 | 既定7項目 | §3 |
| `anomalies` | ≤64 | [] | §4 |
| `faults` | | 無効 | §4.1 |
| `sql` / `files` / `stream` | | 既定あり | **使うツールのものだけ書く** |
| `task` | `"generate"` | | 省略可（`retry` は書かない） |

### 5.2 `sql`（factory-sql-data-loader）

```json
"sql": {"schema_name": "", "table": "equipment_results", "operation": "insert"}
```
- `table` / `schema_name`：英字/`_`始まり英数字`_`。MySQL・MariaDB・SQLite は `schema_name` を空にする。
- `operation`：`insert`（追加のみ）/ `upsert`（あれば更新）/ `update`（既存のみ更新）/ `delete`。**upsert/update/delete は `primary_key: true` の項目が必要**で、DB側の主キーと一致していること。
- テーブルが無い場合は画面の「未作成のテーブルを作成」で作る（作らないと `NoSuchTableError` で失敗）。
- 画面から作るテーブルの列型：string→NVARCHAR系(length)、integer→BIGINT、number→FLOAT（OracleはBINARY_DOUBLE）、decimal→NUMERIC(precision,scale)、boolean→BOOLEAN相当、datetime→DATETIME系（**タイムゾーンなし**、SQL ServerはDATETIME2。値はUTCで入る）、json→長いテキスト列（既存テーブルにJSON型の列があればJSONとして書く）。

### 5.3 `files`（factory-file-generator）

| キー | 値 | 既定 |
|---|---|---|
| `formats` | `json` `csv` `image` `xlsx` `xml` `parquet` `avro` `pdf` の配列（1〜8個） | `["json","csv","image"]` |
| `records_per_file` | 1〜10000 | 100 |
| `path_template` | フォルダ。`{run_key}` `{job_id}` と parameters を参照可 | `"{run_key}/{job_id}"` |
| `filename_template` | ファイル名（拡張子なし）。`{sequence:010d}` `{record_id}` `{run_key}` `{job_id}`、先頭レコードの項目・parameters | `"{sequence:010d}-{record_id}"` |
| `json_mode` | `array` / `object`（1件1ファイル） / `jsonl` | `array` |
| `json_pretty` | bool | false |
| `json_template` | §5.5 の構造テンプレート or null | null |
| `compression` | `none` / `gzip` | `none` |
| `csv_delimiter` / `csv_quotechar` | 1文字 | `,` / `"` |
| `csv_quoting` | `minimal` `all` `nonnumeric` | `minimal` |
| `csv_header` | bool | true |
| `csv_null_value` | NULLの表記 | `""` |
| `csv_newline` | `LF` / `CRLF` | `LF` |
| `csv_encoding` | `utf-8` / `utf-8-sig`（BOM付き、Excel向け） | `utf-8-sig` |
| `write_sidecars` | 画像の付帯JSON | true |
| `write_manifest` | 完了印 `.ready.json` | true |
| `image` | `{width, height, format(png/jpeg), pattern(grid/gradient/dots), noise, defect_probability, every, quality, background, foreground, defect_color}` | 320×240 png grid |
| `xlsx_sheet` / `xlsx_allow_formulas` | シート名 / 数式を許可 | `"Data"` / false |
| `xml_root` / `xml_row` | 要素名 | `records` / `record` |
| `parquet_compression` | `snappy` `gzip` `zstd` `none` | `snappy` |
| `avro_record_name` / `avro_namespace` / `avro_codec` | | `SourceRecord` / `factory.source` / `deflate` |
| `pdf_landscape` / `pdf_font_size` / `pdf_columns` | 横向き / 5〜14 / 出す列名の配列 | true / 8 / [] |
| `completion_mode` | `manifest-v2`（通常は書かない） | |

- `json_template` は **JSON出力にだけ**効く（CSV等は平らな行のまま）。

### 5.4 `stream`（factory-stream-simulator）

| キー | 値 | 既定 |
|---|---|---|
| `envelope` | true で本文に `_source`（record_key/sequence/run_key）を追加 | true |
| `metadata_key` | 追加キー名（項目名と重複不可） | `"_source"` |
| `http_body` | HTTP送信時 `array` / `single` / `ndjson` | `array` |
| `topic_template` | 送信先トピック/subject等。項目・parameters・`{sequence}`・`{record_id}` 参照可。空なら接続先の既定 | `""` |
| `payload_template` | §5.5 の構造テンプレート or null（null なら行そのまま） | null |
| `message_size_bytes` | 0〜65536。本文を空白で水増し（MQTT/キャプチャ） | 0 |
| `duplicate_rate` | 0〜1。同じメッセージを1回追加送信する確率 | 0 |
| `delivery_attempts` / `retry_backoff_ms` | null（接続先の設定を使う）or 数値 | null |

- `envelope: true` のとき `payload_template` は**オブジェクト**でなければならない。
- MQTT のトピックに `#` `+` は使えない。

### 5.5 JSON構造テンプレート（`files.json_template` / `stream.payload_template`）

任意の入れ子オブジェクト・配列を作れる。値が次の文字列なら置き換わる（型は保たれる）：

| 書き方 | 意味 |
|---|---|
| `"$row.項目名"` | その行の値 |
| `"$parameters.名前"` / `"$parameters.名前.0"` | パラメーター（配列は番号で） |
| `"$meta.record_key"` / `"$meta.sequence"` / `"$meta.run_key"` | メタ情報 |

それ以外の文字列・数値はそのまま出力。入れ子は32段まで、1件1MiBまで。**存在しない参照はエラー**（`$row.xxx` の綴りに注意）。`omit` 異常で消える項目を参照すると、その行でエラーになるので注意。

### 5.6 3ツール共通で使い回したいとき

- SQL・ファイル・ストリームでは同じ version: 2 のデータ定義を利用できます。接続先ID・版と利用する出力セクションを実行先で確認します。
- 使い回すテンプレートは **`fields` / `parameters` / `anomalies` と基本キーだけ**の最小構成にし、`sql` / `files` / `stream` は各ツール用に足す。
- `run_key` と `seed` と `fields` を揃えると、SQL・ファイル・ストリームで **同じ record_id・同じ値** が作られ、レイクハウス側での突合試験に使える。

---

## 6. 形式B（設備 / API / ヒストリアン / ログ / RFID）

### 6.1 トップレベル（Spec）

| キー | 範囲 | 既定 | 意味 |
|---|---|---|---|
| `version` | 1 | 1 | 省略可 |
| `name` | ≤120 | `"小さく試す"` | 表示名 |
| `description` | ≤2000 | `""` | 想定・異常の正解 |
| `profile_id` | ID | `"default"` | 公開・出力設定のID |
| `interval_ms` | 10〜60000 | 1000 | 1tick の周期 |
| `batch_size` | 1〜1000 | 5 | **ログ・RFID**の1tickあたり件数（設備・ヒストリアンは台数を使う） |
| `max_ticks` | 0〜 | 0 | 0=停止まで続ける |
| `storage_limit_mb` | 16〜102400 | 1024 | データ容量上限 |
| `generator` | 形式Aと同じ RunSpec | 既定7項目 | **使われるのは `fields` `parameters` `anomalies` `run_key` `seed` `start_sequence` のみ**（`rows` `target_rate` `batch_size` `sql` `files` `stream` `faults` 等は無視される。書かない） |
| `equipment` / `business` / `history` / `logs` / `identification` | | 既定あり | **使うツールのものだけ書く** |

> ⚠ 既定値の罠：`equipment.registers` の既定は `value` / `sequence_no` / `status` を、`history.tags` の既定は `value` を、`logs.message_template` の既定は `entity_id` / `status` / `value` を参照する。**自分で `generator.fields` を書いたら、使うツールのセクションも必ず明示して自分の項目名に合わせる。**

### 6.2 設備（factory-equipment-simulator）：`equipment`

- `generator.fields` の**全項目**が OPC UA の `ns=1;s=Device001.<項目名>` として公開される（文字列も可）。
- Modbus には `registers` で指定した項目だけが載る。

| キー | 値 | 既定 |
|---|---|---|
| `devices` | 1〜247（Modbus device ID 1〜N） | 4 |
| `registers[]` | `{field, area, address, encoding, byte_order, word_order, scale, offset, enum_values}` | value/sequence_no/status |
| ・`area` | `holding` `input` `coil` `discrete` | holding |
| ・`address` | 0始まり（40001表記ではない） | |
| ・`encoding` | `uint16` `int16`（1語）/ `uint32` `int32` `float32`（2語）/ `float64`（4語）/ `bool` | float32 |
| ・`byte_order` / `word_order` | `big` / `little` | big |
| ・`scale` / `offset` | レジスター値 = 値×scale+offset | 1 / 0 |
| ・`enum_values` | 文字列→数値の対応 `{"RUN":0,"IDLE":1}` | {} |
| `quality` | `Good` `BadSensorFailure` `UncertainLastUsableValue` | Good |
| `quality_from_tick` / `quality_until_tick` | 品質異常の期間（0=開始/最後まで） | 0 / 0 |
| `offline_from_tick` / `offline_ticks` | 一時切断（0=なし） | 0 / 5 |
| `read_delay_ms` | Modbus応答遅延 0〜5000 | 0 |
| `writable` | クライアント書込を許可 | false |

ルール：
- 同じ `area` 内でアドレス幅が重ならないこと（float32 は2語使う：address 0 なら 0〜1）。`coil` / `discrete` は `bool` のみ。
- `registers[].field` は `generator.fields` に**実在する名前**にする（綴り違いはエラーにならず、Modbus読取が失敗する。§7）。
- 文字列項目をレジスターに載せるなら `enum_values` に**全候補**を書く（`choices` と一致させる）。
- 値がエンコードの範囲に収まること（uint16 は 0〜65535、scale 適用後）。

### 6.3 業務API（factory-api-simulator）：`business`

| キー | 値 | 既定 |
|---|---|---|
| `resources[]` | `{name, rows, generator}`（1〜30個、name 重複不可） | orders 200件 |
| ・`name` | URL末尾 `/source/rest/<name>` | |
| ・`rows` | 初期件数 1〜1,000,000 | 200 |
| ・`generator` | null（=トップの `generator` を使う）or このコレクション専用の RunSpec（`fields` 等） | null |
| `updates_per_tick` | 各tickで更新する件数（0=固定データ） | 2 |
| `delete_every_ticks` | N tickごとに1件論理削除（0=なし） | 0 |
| `cursor_ttl_seconds` | カーソル有効期限 | 600 |
| `page_size` | 既定ページ件数 1〜1000 | 100 |
| `fault` | `none` `rate_limit`(429) `server_error`(503) `unauthorized`(401) `delay` `duplicate_page` `skip_page` `truncate_json` `cursor_expired` | none |
| `fault_every` / `fault_delay_ms` | 何リクエストごとに異常 / delayの待ち | 5 / 1000 |

ルール：
- **`id` は必ず32桁のキーで上書きされる**。業務キー（指図番号など）は `order_code` のような別名の項目にする。
- 更新時は seed を変えて再生成されるため、乱数項目（choice等）は更新で値が変わる。不変にしたい項目は `sequence` / `template`（通番ベース）で作る。
- 画面の見本はトップの `generator` の行だけを表示する。`resources[].generator` の誤りは開始後に失敗として出るので、まず `max_ticks` を小さくして開始し状態を確認する。
- 主コレクションはトップの `generator` に書いて `generator: null`、2つ目以降の列構成が違うコレクションだけ専用 `generator` を持たせるのが分かりやすい。

### 6.4 ヒストリアン（factory-historian-simulator）：`history`

| キー | 値 | 既定 |
|---|---|---|
| `tags` | 記録する項目名の配列（1〜100）。タグ名は `device-001.<項目名>` | `["value"]` |
| `devices` | 1〜1000 | 4 |
| `initial_samples` | 開始時に作る過去の時点数 | 1000 |
| `sample_seconds` | 記録上の時刻間隔（秒）。`interval_ms` と別 | 1 |
| `source_time_field` | 空=時刻を自動計算 / datetime 項目名=その値を時刻に使う | `""` |
| `shift_every` / `timestamp_shift_seconds` | N時点ごとに時刻をずらす | 0 / 0 |
| `retention_days` | 保持日数 | 90 |
| `quality` / `bad_every` | 品質異常コード（Bad/Uncertain）とN時点ごと | Good / 0 |
| `missing_every` | N時点ごとに欠測（保存しない） | 0 |

ルール：
- `tags` は **数値項目（integer / number / decimal）**にする。文字列や存在しない名前は、エラーにならず**値 null・品質 Bad** として記録されてしまう。
- `initial_samples × devices × tags数 ≤ 2,000,000`。
- `source_time_field` を使う場合は `data_type: "datetime"` の項目名を正確に書く（綴り違いは黙って無視される）。

### 6.5 ログ（factory-log-simulator）：`logs`

| キー | 値 | 既定 |
|---|---|---|
| `format` | `jsonl` `plain` `rfc5424` `rfc3164` | rfc5424 |
| `facility` / `severity` | 0〜23 / 0〜7 | 16 / 6 |
| `hostname` / `app_name` | `[A-Za-z0-9_.-]` | factory-device / mes-demo |
| `message_template` | 本文。§3.3 と同じ書式で項目と `{sequence}` を参照 | 既定は entity_id/status/value を参照 → **必ず自分の項目で書き直す** |
| `tcp_framing` | `octet_counting` / `newline` | octet_counting |
| `rotate_mb` / `backups` | 1〜100 / 1〜30 | 10 / 5 |
| `duplicate_every` / `malformed_every` | N件ごとに二重出力 / ヘッダー破損 | 0 / 0 |

- トップの `batch_size` が1tickあたりのログ件数。
- `jsonl` は行の全項目＋`message` を出力する。画面見本の timestamp は固定値（2000-01-01）で表示される（実出力は現在時刻）。

### 6.6 RFID・バーコード（factory-identification-simulator）：`identification`

| キー | 値 | 既定 |
|---|---|---|
| `tags` | タグ・品目の種類数 1〜100000 | 100 |
| `readers` | 通過順の読取機名の配列 | GATE-IN, ASSEMBLY, INSPECTION, GATE-OUT |
| `operators` | 架空の作業者IDの配列 | WORKER-001〜003 |
| `barcode` | `code128` `ean13` `qr` | code128 |
| `duplicate_every` / `drop_every` | N件ごとに二重読取 / 読み飛ばし | 0 / 0 |
| `wrong_reader_every` / `unauthorized_every` | N件ごとに予定外読取機 / 未登録作業者 | 0 / 0 |

- 自動で付く項目：`event_id` `tag_id` `epc` `reader_id` `operator_id` `event_type` `direction` `lot_id` `barcode`。**同名の項目を `generator.fields` に書くと自分の値が優先**される（標準ラベルAPIのタグと一致しなくなる点に注意）。
- `generator.fields` には追加情報（電波強度、読取時刻、工程情報など）だけを書けばよい。

---

## 7. 境界条件を確認する

| 条件 | 確認すること |
| --- | --- |
| 欠測と加算・倍率・ドリフト | 数値の項目で、有効な値と欠測を分けて確認する。 |
| 大小比較 | 比較する型を揃える。NULLは大小比較で一致しない。 |
| in | 候補は配列にする。 |
| copy_from | コピー元は実行内で0始まりの整数位置を使う。 |
| {no:03d} | noを先に整数の項目として定義する。 |
| 設備 | レジスターの型・幅・番地と文字列のenum割当を照合する。 |
| ヒストリアン | タグに生成する数値項目、時刻源に日時項目を指定する。 |
| 業務API | コレクション別の定義も見本と少量試験で確認する。 |

---

## 8. 検証のしかた

### 8.1 オフラインとアプリで確認

- Python環境で `uv run --frozen python scripts/validate_template.py my-template.json` を実行する。

- 画面：「プリセット / JSON」（形式Bは「設定の保存・JSON」）に貼り付け →「JSONを画面に適用」→「見本を見る」。
- コマンド（アプリを起動した状態で。ポートは各リポジトリの `.env` の `APP_PORT`。既定例：SQL 3560 / ファイル 3561 / ストリーム 3562 / 設備 3640 / API 3641 / ヒストリアン 3642 / ログ 3643 / RFID 3644）：

```bash
curl -s -X POST http://127.0.0.1:3560/api/preview -H 'Content-Type: application/json' --data @my-template.json | python3 -m json.tool | head -60
```

  - 成功：`records`（見本行）が返る。設備は `protocol_mapping.modbus_registers[].status` がすべて「変換成功」か確認。
  - 失敗：`detail` にエラー。§8.3 で原因を引く。
- 見本は**先頭・途中・末尾と異常の境界だけ**を作る確認です。全件の成功保証ではないため、本番前に少ない件数（`rows` や `max_ticks` を小さく）で一度実行してください。

### 8.2 AIの自己チェックリスト（出力前に全項目を確認）

- [ ] JSONとして正しい（コメント無し・末尾カンマ無し・ダブルクォート）
- [ ] 形式（A/B）がツールに合っている。形式Bは項目を `generator.fields` に書いた
- [ ] 本書に無いキーを1つも使っていない（`min` `max` `type` 等）
- [ ] 全 `fields` に `name` `data_type` `generator` がある。name は英数字`_`、重複なし
- [ ] 参照（template / sources / condition.field）は**上にある項目**だけ
- [ ] `$param` で参照した名前はすべて `parameters` にある
- [ ] template の `:d` は integer 項目、`:.Nf` は number/integer 項目だけ
- [ ] 日時はタイムゾーン付き。timestamp 項目は `data_type: "datetime"`
- [ ] choice の `weights` は choices と同じ長さ
- [ ] ratio の分母は0にならない（最小値1以上）
- [ ] string の値が `length` に収まる
- [ ] 主キーに `null_probability` を付けていない。SQL の upsert/update/delete なら主キーがある
- [ ] 異常ルールは §7 の境界条件を確認した。`field` は実在、`to_row ≥ from_row`
- [ ] 使わないセクションを省略した（形式Aの不要な `files`/`stream`、形式Bの不要セクション、`generator.rows` 等）
- [ ] 形式Bで使うセクションを明示し、`registers[].field` / `history.tags` / `logs.message_template` が自分の項目名と一致
- [ ] `description` に「想定」「異常の位置と内容（正解）」「確認すること」を書いた

### 8.3 エラーメッセージ → 原因 → 直し方

| エラー（`detail`） | 原因 | 直し方 |
|---|---|---|
| `Extra inputs are not permitted`（`loc` の最後がキー名） | 存在しないキー・綴り違い（`min`→`minimum` など） | 本書の表にあるキー名に直す。`loc` の数字は**0始まり**の配列番号（`["body","fields",1,"min"]` = 2番目の項目の `min`） |
| `Input should be 'record_id', 'uuid', ...` | generator / data_type / operation 等の綴り | 列挙値から選ぶ |
| `String should match pattern '^[A-Za-z_]...'` | 項目名・テーブル名に日本語・ハイフン等 | 英数字と `_` に |
| `JSON decode error` | JSONの構文エラー | 末尾カンマ・コメント・クォートを確認 |
| `パラメーター X が定義されていません` | `$X` の参照先が無い | `parameters` に X を追加 |
| `テンプレート参照 X が見つかりません` | template で X を参照したが上に無い | 項目の順番を入れ替える／綴りを直す |
| `テンプレートは項目名と短い数値書式だけを参照できます` | `{x:,}` `{x!r}` 等 | `{x}` `{x:05d}` `{x:.2f}` だけにする |
| `生成ルールの型・範囲・日時を確認してください` | 書式 `:d` と型の不一致、日時の書式誤り、NULLとの大小比較、`in` に配列以外、copy_from の value 無し | §7 と §8.2 を順に確認 |
| `X は整数ではありません` | integer 型に小数（normal 等） | number にするか integer 生成器に |
| `開始日時にはタイムゾーンが必要です` / `日時にはタイムゾーンが必要です` | `+09:00` などが無い | タイムゾーンを付ける |
| `最小値が最大値を超えています` | minimum > maximum | 入れ替える |
| `選択肢と重みを確認してください` | weights の長さ違い・合計0・負数 | 長さを揃える |
| `参照元の項目は先に定義してください` / `条件が参照する項目を先に定義してください` | 参照先が下にある | 順番を入れ替える |
| `参照元の項目が必要です` | reference/sum等で `sources` が空 | `sources` を書く |
| `比率には0でない分母が必要です` | ratio の sources が2つでない／分母0 | 2つにし、分母の最小値を1以上に |
| `項目名は重複できません` | 同名（大小文字無視） | 名前を変える |
| `主キーにNULL率は指定できません` | 主キーに null_probability | 外す |
| `小数桁数は精度以下にしてください` | scale > precision | 直す |
| `異常ルールの対象項目が定義されていません` | anomalies.field の綴り | 実在する項目名に |
| `異常終了位置は開始位置以上にしてください` | to_row < from_row | 直す |
| `JSONテンプレートの参照先が見つかりません` | `$row.xxx` 等の綴り、omit で消えた項目 | 綴り・異常との組合せを確認 |
| `メタデータを追加する場合、本文テンプレートはJSONオブジェクトにしてください` | envelope=true で payload_template が配列等 | オブジェクトにするか envelope=false |
| `ストリームのメタデータ名と生成項目名が重複しています` | `_source` という項目がある | 項目名か metadata_key を変える |
| `レジスターのアドレス幅が重複・範囲外です` | float32 等の幅を考えずに連番アドレス | 幅（§6.2）を考えて振り直す |
| `coil/discreteの型はboolです` | coil に数値型 | encoding を bool に |
| `初期履歴は合計200万点以下にしてください` | initial_samples×devices×tags が大きすぎ | どれかを減らす |
| `コレクション名は重複できません` | resources の name 重複 | 変える |
| `不正ファイルの生成設定はファイルツール専用です` | file 以外で artifact_mode | `"none"` に |
| 実行が `failed` で `host_memory_headroom_low` | ホストの空きメモリが設定した閾値を下回った | 環境変数 `MIN_AVAILABLE_GIB` を下げて起動 |
| 実行が `failed` で `NoSuchTableError`（SQL） | テーブル未作成 | 画面で「未作成のテーブルを作成」 |

---

## 9. ツール別の完成例

### 9.1 SQL：設備実績（形式A）

```json
{
  "name": "設備実績 / 3ライン / 温度スパイクあり",
  "description": "【想定】3ライン×10設備の生産実績をSQLに投入し、CDCで取り込む。\n【異常】50〜59件目で温度が250℃に跳ねる。",
  "run_key": "equip-results-001",
  "seed": 42,
  "rows": 200,
  "target_rate": 0,
  "batch_size": 100,
  "parameters": {"equipment_count": 10, "lines": ["L1", "L2", "L3"], "start_time": "2026-12-01T08:00:00+09:00"},
  "fields": [
    {"name": "id", "data_type": "string", "generator": "record_id", "primary_key": true, "length": 64},
    {"name": "seq_no", "data_type": "integer", "generator": "sequence"},
    {"name": "equipment_no", "data_type": "integer", "generator": "integer", "minimum": 1, "maximum": "$equipment_count"},
    {"name": "equipment_code", "data_type": "string", "generator": "template", "template": "EQ-{equipment_no:03d}", "length": 16},
    {"name": "line", "data_type": "string", "generator": "choice", "choices": "$lines", "length": 8},
    {"name": "status", "data_type": "string", "generator": "choice", "choices": ["RUN", "IDLE", "STOP"], "weights": [90, 8, 2], "length": 8},
    {"name": "temperature", "data_type": "number", "generator": "normal", "mean": 65, "stddev": 2.5, "scale": 1},
    {"name": "output_qty", "data_type": "integer", "generator": "integer", "minimum": 80, "maximum": 120},
    {"name": "reject_qty", "data_type": "integer", "generator": "integer", "minimum": 0, "maximum": 5},
    {"name": "good_qty", "data_type": "integer", "generator": "difference", "sources": ["output_qty", "reject_qty"]},
    {"name": "yield_ratio", "data_type": "number", "generator": "ratio", "sources": ["good_qty", "output_qty"], "scale": 4},
    {"name": "unit_price", "data_type": "decimal", "generator": "constant", "value": "125.50", "precision": 12, "scale": 2},
    {"name": "stop_reason", "data_type": "string", "generator": "constant", "value": null, "length": 32,
     "condition": {"field": "status", "operator": "eq", "value": "STOP", "then_value": "MAINTENANCE"}},
    {"name": "event_time", "data_type": "datetime", "generator": "timestamp", "start": "$start_time", "step": 60, "group_size": "$equipment_count"}
  ],
  "anomalies": [
    {"name": "温度スパイク", "field": "temperature", "operation": "set", "value": 250, "from_row": 50, "to_row": 59}
  ],
  "sql": {"schema_name": "", "table": "equipment_results", "operation": "insert"}
}
```

### 9.2 ファイル：検査結果 CSV＋JSONL（形式A）

```json
{
  "name": "検査結果 / CSVとJSONL / 入れ子JSON",
  "description": "【想定】検査装置が出力する検査結果ファイルをlandingに置き、ready.jsonを合図に取り込む。\n【異常】300〜399件目で寸法が1件ごとに0.01mmずつ増える。",
  "run_key": "inspection-001",
  "seed": 7,
  "rows": 500,
  "target_rate": 0,
  "batch_size": 100,
  "parameters": {"start_time": "2026-12-01T00:00:00+09:00", "lots": ["LOT-A01", "LOT-A02", "LOT-B01"]},
  "fields": [
    {"name": "inspection_id", "data_type": "string", "generator": "uuid", "primary_key": true, "length": 36},
    {"name": "lot_id", "data_type": "string", "generator": "choice", "choices": "$lots", "length": 16},
    {"name": "serial_no", "data_type": "integer", "generator": "sequence", "start": 100000},
    {"name": "serial_code", "data_type": "string", "generator": "template", "template": "SN-{serial_no:08d}", "length": 16},
    {"name": "width_mm", "data_type": "number", "generator": "normal", "mean": 25.0, "stddev": 0.05, "scale": 3},
    {"name": "judge", "data_type": "string", "generator": "choice", "choices": ["OK", "NG"], "weights": [97, 3], "length": 2},
    {"name": "inspected_at", "data_type": "datetime", "generator": "timestamp", "start": "$start_time", "step": 2.5}
  ],
  "anomalies": [
    {"name": "寸法ドリフト", "field": "width_mm", "operation": "ramp", "value": 0.01, "from_row": 300, "to_row": 399}
  ],
  "files": {
    "formats": ["csv", "json"],
    "records_per_file": 100,
    "json_mode": "jsonl",
    "json_template": {
      "id": "$row.inspection_id",
      "lot": "$row.lot_id",
      "serial": "$row.serial_code",
      "measure": {"width_mm": "$row.width_mm"},
      "result": "$row.judge",
      "at": "$row.inspected_at",
      "source_run": "$meta.run_key"
    },
    "csv_encoding": "utf-8"
  }
}
```

### 9.3 ストリーム：設備テレメトリ（形式A）

```json
{
  "name": "設備テレメトリ / ライン別トピック / 欠測あり",
  "description": "【想定】設備がMQTTでテレメトリを送る。トピックはライン・設備ごと。\n【異常】電流が2%欠測。100〜149件目で振動値が固着。",
  "run_key": "telemetry-001",
  "seed": 11,
  "rows": 300,
  "target_rate": 20,
  "batch_size": 50,
  "parameters": {"start_time": "2026-12-01T00:00:00+09:00", "lines": ["L1", "L2"]},
  "fields": [
    {"name": "event_id", "data_type": "string", "generator": "record_id", "primary_key": true, "length": 64},
    {"name": "line", "data_type": "string", "generator": "choice", "choices": "$lines", "length": 8},
    {"name": "machine_no", "data_type": "integer", "generator": "integer", "minimum": 1, "maximum": 5},
    {"name": "machine_id", "data_type": "string", "generator": "template", "template": "M-{machine_no:02d}", "length": 8},
    {"name": "vibration", "data_type": "number", "generator": "normal", "mean": 2.0, "stddev": 0.3, "scale": 3},
    {"name": "current_a", "data_type": "number", "generator": "uniform", "minimum": 10, "maximum": 12, "scale": 2, "null_probability": 0.02},
    {"name": "at", "data_type": "datetime", "generator": "timestamp", "start": "$start_time", "step": 1}
  ],
  "anomalies": [
    {"name": "振動の固着", "field": "vibration", "operation": "freeze", "from_row": 100, "to_row": 149}
  ],
  "stream": {
    "envelope": true,
    "metadata_key": "_source",
    "topic_template": "factory/{line}/{machine_id}/telemetry",
    "payload_template": {
      "id": "$row.event_id",
      "machine": {"line": "$row.line", "id": "$row.machine_id"},
      "metrics": {"vibration": "$row.vibration", "current_a": "$row.current_a"},
      "ts": "$row.at"
    }
  }
}
```

### 9.4 設備：プレス機6台（形式B）

```json
{
  "name": "プレス機 / 6台 / OPC UAとModbus",
  "description": "【想定】プレス機6台の温度・回転数・状態・ショット数を収集クライアントが読む。\n【異常】記録位置120〜179（約20〜29tick目）で温度がドリフトする。",
  "profile_id": "default",
  "interval_ms": 1000,
  "max_ticks": 0,
  "generator": {
    "run_key": "press-001",
    "seed": 3,
    "fields": [
      {"name": "id", "data_type": "string", "generator": "record_id", "primary_key": true, "length": 64},
      {"name": "temperature", "data_type": "number", "generator": "normal", "mean": 42.0, "stddev": 0.8, "scale": 2},
      {"name": "rpm", "data_type": "integer", "generator": "integer", "minimum": 1180, "maximum": 1220},
      {"name": "status", "data_type": "string", "generator": "choice", "choices": ["RUN", "IDLE", "ALARM"], "weights": [94, 5, 1], "length": 8},
      {"name": "shot_count", "data_type": "integer", "generator": "sequence"}
    ],
    "anomalies": [
      {"name": "温度ドリフト", "field": "temperature", "operation": "ramp", "value": 0.2, "from_row": 120, "to_row": 179}
    ]
  },
  "equipment": {
    "devices": 6,
    "registers": [
      {"field": "temperature", "area": "holding", "address": 0, "encoding": "float32"},
      {"field": "rpm", "area": "holding", "address": 2, "encoding": "uint16"},
      {"field": "status", "area": "holding", "address": 3, "encoding": "uint16", "enum_values": {"RUN": 0, "IDLE": 1, "ALARM": 2}},
      {"field": "shot_count", "area": "holding", "address": 4, "encoding": "uint32"}
    ]
  }
}
```

### 9.5 業務API：製造指図＋在庫（形式B）

```json
{
  "name": "業務API / 製造指図と在庫 / 50件ページ",
  "description": "【想定】ERPの製造指図APIと在庫APIを、収集側がページング＋差分で取得する。",
  "interval_ms": 2000,
  "generator": {
    "run_key": "erp-orders-001",
    "seed": 21,
    "parameters": {"products": ["P-100", "P-200", "P-300"]},
    "fields": [
      {"name": "order_no", "data_type": "integer", "generator": "sequence", "start": 1},
      {"name": "order_code", "data_type": "string", "generator": "template", "template": "WO-{order_no:06d}", "length": 16},
      {"name": "product_id", "data_type": "string", "generator": "choice", "choices": "$products", "length": 16},
      {"name": "quantity", "data_type": "integer", "generator": "integer", "minimum": 10, "maximum": 500},
      {"name": "status", "data_type": "string", "generator": "choice", "choices": ["planned", "running", "done"], "weights": [30, 50, 20], "length": 16},
      {"name": "due_date", "data_type": "datetime", "generator": "timestamp", "start": "2026-12-05T17:00:00+09:00", "step": 3600}
    ]
  },
  "business": {
    "resources": [
      {"name": "orders", "rows": 300, "generator": null},
      {"name": "inventory", "rows": 60, "generator": {
        "run_key": "erp-inventory-001",
        "seed": 22,
        "fields": [
          {"name": "item_no", "data_type": "integer", "generator": "sequence", "start": 1},
          {"name": "item_code", "data_type": "string", "generator": "template", "template": "ITEM-{item_no:04d}", "length": 16},
          {"name": "qty_on_hand", "data_type": "integer", "generator": "integer", "minimum": 0, "maximum": 1000},
          {"name": "reserved", "data_type": "integer", "generator": "integer", "minimum": 0, "maximum": 100},
          {"name": "available", "data_type": "integer", "generator": "difference", "sources": ["qty_on_hand", "reserved"]}
        ]
      }}
    ],
    "updates_per_tick": 3,
    "page_size": 50,
    "cursor_ttl_seconds": 600,
    "fault": "none"
  }
}
```

### 9.6 ヒストリアン：炉の温度・圧力（形式B）

```json
{
  "name": "ヒストリアン / 炉温度と圧力 / 8設備",
  "description": "【想定】8台の炉の温度・圧力を1秒間隔で1日分バックフィルし、その後リアルタイムで追記する。\n【異常】記録位置4000〜4399（500〜549時点目）で温度が固着。",
  "interval_ms": 1000,
  "generator": {
    "run_key": "furnace-001",
    "seed": 5,
    "fields": [
      {"name": "id", "data_type": "string", "generator": "record_id", "primary_key": true, "length": 64},
      {"name": "temperature", "data_type": "number", "generator": "normal", "mean": 850, "stddev": 3, "scale": 1},
      {"name": "pressure_kpa", "data_type": "number", "generator": "uniform", "minimum": 101.0, "maximum": 103.0, "scale": 2}
    ],
    "anomalies": [
      {"name": "温度の固着", "field": "temperature", "operation": "freeze", "from_row": 4000, "to_row": 4399}
    ]
  },
  "history": {
    "tags": ["temperature", "pressure_kpa"],
    "devices": 8,
    "initial_samples": 86400,
    "sample_seconds": 1,
    "missing_every": 0,
    "bad_every": 0
  }
}
```

### 9.7 ログ：MESアプリログ（形式B）

```json
{
  "name": "MESアプリログ / JSON Lines / 毎秒10件",
  "description": "【想定】MESのアプリケーションログをJSON Linesで回転ファイルに出力し、ログ収集基盤で取り込む。",
  "interval_ms": 1000,
  "batch_size": 10,
  "generator": {
    "run_key": "meslog-001",
    "seed": 8,
    "fields": [
      {"name": "id", "data_type": "string", "generator": "record_id", "primary_key": true, "length": 64},
      {"name": "level", "data_type": "string", "generator": "choice", "choices": ["INFO", "WARN", "ERROR"], "weights": [90, 8, 2], "length": 8},
      {"name": "station_no", "data_type": "integer", "generator": "integer", "minimum": 1, "maximum": 12},
      {"name": "station", "data_type": "string", "generator": "template", "template": "ST-{station_no:02d}", "length": 8},
      {"name": "work_order", "data_type": "string", "generator": "template", "template": "WO-{sequence:06d}", "length": 16},
      {"name": "elapsed_ms", "data_type": "integer", "generator": "integer", "minimum": 5, "maximum": 400}
    ]
  },
  "logs": {
    "format": "jsonl",
    "hostname": "mes-app-01",
    "app_name": "mes-core",
    "message_template": "station={station} wo={work_order} level={level} elapsed_ms={elapsed_ms}",
    "rotate_mb": 10,
    "backups": 5
  }
}
```

### 9.8 RFID：組立ライン（形式B）

```json
{
  "name": "組立ラインRFID / 5工程 / 二重読取あり",
  "description": "【想定】仕掛品タグが5つのゲートを順に通過する。\n【異常】50件ごとに同じ読取（同じevent_id）を再送する。",
  "interval_ms": 1000,
  "batch_size": 5,
  "generator": {
    "run_key": "rfid-assembly-001",
    "seed": 13,
    "fields": [
      {"name": "id", "data_type": "string", "generator": "record_id", "primary_key": true, "length": 64},
      {"name": "rssi_dbm", "data_type": "integer", "generator": "integer", "minimum": -70, "maximum": -40},
      {"name": "read_at", "data_type": "datetime", "generator": "timestamp", "start": "2026-12-01T08:00:00+09:00", "step": 2}
    ]
  },
  "identification": {
    "tags": 200,
    "readers": ["GATE-IN", "WELD", "PAINT", "ASSEMBLY", "GATE-OUT"],
    "operators": ["WORKER-001", "WORKER-002", "WORKER-003", "WORKER-004"],
    "barcode": "code128",
    "duplicate_every": 50
  }
}
```

---

## 10. 依頼プロンプト（コピーして【】を埋める）

```text
あなたは、添付の「ダミーデータ生成ツール群 テンプレートJSON作成ハーネス」に厳密に従って、
テンプレート（プリセット）JSONを作るアシスタントです。ハーネスに無いキーや書き方は使わないでください。

■ 対象ツール：【例：factory-stream-simulator】
■ 何を試したいか（業務・システムの状況）：【例：MESの設備実績をSQL Serverに入れて、CDCでレイクハウスに取り込めるか確認したい】
■ データの中身（わかる範囲で）：【例：設備10台、3ライン、状態はRUN/IDLE/STOP、温度は平均65℃前後、生産数・不良数・良品数・歩留まり】
■ 件数・時間：【例：1分ごと、200件／8時から】
■ 入れたい異常：【例：50〜59件目で温度が250℃。不良数が生産数を超える行を少し】（なければ「なし」）
■ 出力先の条件：【SQLならテーブル名と insert/upsert/update/delete。ファイルなら形式。ストリームならトピックの形。設備なら台数とModbusの割当。APIならコレクション名…】
■ 他ツールと揃えたいキー：【例：run_key=line-a-2026-12、seed=42、equipment_code の形式 EQ-001】（なければ「なし」）

出力は次の順で：
1. 項目設計表（項目名 / data_type / generator / 主な設定 / 説明）
2. 異常の正解表（何件目〜何件目に、どの項目へ、何をしたか）
3. テンプレートJSON（```json のコードブロック1つだけ。最小構成で、使わないセクションは省略）
4. ハーネス §8.2 自己チェックリストの確認結果（各項目 OK／該当なし）
5. 画面で確認すべき点（見本のどこを見ればよいか）を3行以内で
```

### 10.1 エラーが出たときの追い依頼

```text
このJSONをアプリで検証したところ、次のエラーが出ました。ハーネス §7・§8.3 を参照して原因を説明し、
修正後のJSON全体を ```json ブロック1つで出してください。変更した箇所も箇条書きで教えてください。

エラー：
【ここにエラー表示（detail）をそのまま貼る】
```

### 10.2 既存テンプレートを直したいときの依頼

```text
次のテンプレートJSONを、ハーネスに従って【やりたい変更：例「温度の欠測を5%追加」「件数を1万件に」】に変更してください。
不要なキーは削って最小構成にし、§8.2 のチェック結果も付けてください。

【ここに今のJSONを貼る】
```
