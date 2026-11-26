# ひな型をJSONで作る

## 最初は使うキーだけ書く

JSONは設定をファイルで保存、共有、自動処理するときに使えます。省略可能な値はアプリが補います。このアプリで使う項目一覧は `fields` です。[最小構成の例](examples/stream-beginner.json)をコピーして見本を確認します。

```json
{
  "name": "設備テレメトリ / ライン別トピック / 欠測あり",
  "description": "【想定】設備がMQTTでテレメトリを送る。トピックはライン・設備ごと。\n【異常】電流が2%欠測。100〜149件目で振動値が固着。",
  "run_key": "telemetry-001",
  "seed": 11,
  "rows": 3,
  "target_rate": 20,
  "batch_size": 50,
  "parameters": {
    "start_time": "2026-12-01T00:00:00+09:00",
    "lines": [
      "L1",
      "L2"
    ]
  },
  "fields": [
    {
      "name": "event_id",
      "data_type": "string",
      "generator": "record_id",
      "primary_key": true,
      "length": 64
    },
    {
      "name": "line",
      "data_type": "string",
      "generator": "choice",
      "choices": "$lines",
      "length": 8
    },
    {
      "name": "machine_no",
      "data_type": "integer",
      "generator": "integer",
      "minimum": 1,
      "maximum": 5
    },
    {
      "name": "machine_id",
      "data_type": "string",
      "generator": "template",
      "template": "M-{machine_no:02d}",
      "length": 8
    },
    {
      "name": "vibration",
      "data_type": "number",
      "generator": "normal",
      "mean": 2.0,
      "stddev": 0.3,
      "scale": 3
    },
    {
      "name": "current_a",
      "data_type": "number",
      "generator": "uniform",
      "minimum": 10,
      "maximum": 12,
      "scale": 2,
      "null_probability": 0.02
    },
    {
      "name": "at",
      "data_type": "datetime",
      "generator": "timestamp",
      "start": "$start_time",
      "step": 1
    }
  ],
  "anomalies": [
    {
      "name": "振動の固着",
      "field": "vibration",
      "operation": "freeze",
      "from_row": 100,
      "to_row": 149
    }
  ],
  "stream": {
    "envelope": true,
    "metadata_key": "_source",
    "topic_template": "factory/{line}/{machine_id}/telemetry",
    "payload_template": {
      "id": "$row.event_id",
      "machine": {
        "line": "$row.line",
        "id": "$row.machine_id"
      },
      "metrics": {
        "vibration": "$row.vibration",
        "current_a": "$row.current_a"
      },
      "ts": "$row.at"
    }
  }
}
```

## 項目を増やす

1. `fields` の要素に名前 `name`、型 `data_type`、生成方法 `generator` を指定します。
2. 参照される項目を上に置きます。たとえば整数の `line_no` を先に定義し、その後で `EQ-{line_no:03d}` を使う文字列項目を定義します。
3. 日時は `+09:00` または `Z` のようなタイムゾーンを付けます。出力はUTCに揃います。小数の丸め桁は `scale`、精度を保つ文字列になる型は `decimal` です。
4. `anomalies` は正常値を作った後、記述順に適用します。位置は0始まりのレコード番号です。範囲の前後も見本で確認します。

| 作りたいもの | 生成器 | 使うキー |
| --- | --- | --- |
| 行を見分けるID | record_id / uuid | run_key、seed、通番。文字列の長さはそれぞれ32または36以上。 |
| 連番 | sequence | start、step、group_size、modulo。整数なら data_type を integer にします。 |
| 範囲内の値 | integer / uniform | minimum と maximum。整数と小数の型を合わせます。 |
| 平均周辺の値 | normal | mean と stddev。小数型を使います。 |
| 候補や真偽値 | choice / boolean | choices と必要に応じて weights。または probability。 |
| 固定の値 | constant | value に型と合うJSON値を入れます。 |
| 記号やコード | template | template で上にある項目を参照します。 |
| 等間隔の日時 | timestamp | start にタイムゾーン付き日時、step に秒数。 |
| コピーや計算 | reference / sum / difference / product / ratio | 先に作る項目を sources に入れます。ratioの分母は0を避けます。 |

`choice` の `weights` は数値の配列です。選択肢と重みの数を揃えます。 `number` は既定で小数3桁までに丸めます。`data_type` を省くとstringになるため、比較や書き込みに必要な型を明示します。

## 異常を一つ追加する

数値の一時上昇は `add`、連続したドリフトは `ramp`、固着は `freeze`、欠測は `null`、項目の欠落は `omit` を選びます。`when` の `in` に候補を書くときは `["RUN","IDLE"]` のように配列を指定します。

## 見本とオフライン検証

アプリでJSONを画面に適用し、見本を開きます。アプリが起動していないときでもPython環境から検証できます。

```sh
uv run --frozen python scripts/validate_template.py docs/examples/stream-beginner.json
```

見本とオフライン検証は、代表位置と異常の境界を調べます。少量で実行して、対象のファイル・テーブル・公開・配送の結果を確認します。

## 書き出しの大きさを選ぶ

「JSONを書き出す」の「既定値を省略」を選ぶと、既定と異なる設定を中心に保存できます。省略したキーは読み込むアプリが補います。設定時点の値を細部まで固定して保管したい場合は、チェックを外して書き出します。

## エディターの補完

VS Codeでリポジトリを開き、設定の `json.schemas` で作業ファイルを `contracts/preset.schema.json` に関連付けます。例えばリポジトリの `.vscode/settings.json` に次の設定を入れると、`drafts/` のJSONが補完対象になります。

```json
{
  "json.schemas": [{
    "fileMatch": ["/drafts/*.json"],
    "url": "./contracts/preset.schema.json"
  }]
}
```

テンプレートの `$schema` でも契約を指定できます。`_comment` は編集用の注記です。共有するひな型の用途は `name` と `description` に書きます。

## 修正箇所が分からないとき

| 表示 | 最初に確認すること |
| --- | --- |
| 知らないキー | プレビューに出た場所を[設定リファレンス](settings-reference.md)で引き、略さず正式なJSONキーを書く。 |
| 項目の型と値が合わない | その項目の型を見て、候補、書式、日時の入力を合わせる。 |
| 参照する項目が見つからない | 名前・大文字小文字を確認し、使う項目より上に定義する。 |
| APIで出力内容が異なる | 使うアプリの専用セクション、接続設定のIDと実行時の版を照合する。 |

[ひな型を選ぶ・作る](preset-guide.md) · [AIにひな型を頼む](AI_TEMPLATE_HARNESS.md)
