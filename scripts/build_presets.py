"""Rebuild the public, credential-free preset library. No network or writes to a DB."""

from __future__ import annotations
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from config import RunSpec, FieldRule, Condition  # noqa: E402
from generation import validate_generation  # noqa: E402


def library(kind):
    """指定ツールの正常・異常シナリオをID付きの実行設定として返す。"""
    result = {}

    def add(identity, name, description, rows=120, rate=0):
        """共通の初期値と付与された説明から、新しいプリセットを登録する。"""
        spec = RunSpec(
            name=name,
            description=description,
            rows=rows,
            target_rate=rate,
            batch_size=100,
            max_duration_seconds=7200,
        )
        spec.run_key = identity
        if kind == "files":
            spec.files.image.every = 10
        result[identity] = spec
        return spec

    for key, name, rows, rate, batch in [
        ("01-quickstart", "小さく試す", 30, 10, 10),
        ("02-volume-100k", "10万件 / 負荷計測", 100000, 1000, 1000),
        ("03-volume-1m", "100万件 / 連続生成", 1000000, 5000, 2000),
        ("04-volume-10m", "1000万件 / 大規模試験", 10000000, 10000, 5000),
    ]:
        spec = add(
            key,
            name,
            "同じ汎用項目を使用し、件数・速度・バッチを段階的に変更する負荷試験。大規模試験前に少量で接続先の性能と容量を確認します。",
            rows,
            rate,
        )
        spec.batch_size = batch
        spec.max_output_mb = 4096
        if kind == "files":
            spec.files.image.every = 1000 if rows > 30 else 3
    if kind == "sql":
        s = add(
            "05-constant-baseline",
            "固定値 / 基準データ",
            "値を常に50とし、他の条件変更前の基準データを作ります。",
        )
        s.fields[5].generator = "constant"
        s.fields[5].value = 50
        s = add(
            "06-uniform-range",
            "一様分布 / 範囲指定",
            "valueを-20〜120の範囲で均等に生成します。",
        )
        s.fields[5].generator = "uniform"
        s.fields[5].minimum = -20
        s.fields[5].maximum = 120
        s = add(
            "07-weighted-states",
            "状態比率 95 : 4 : 1",
            "statusはok / warning / stoppedを95:4:1で選択。重み付き選択の例。",
        )
        s.fields[4].weights = [95, 4, 1]
        s = add(
            "08-nullable-measurements",
            "欠測あり / NULL率20%",
            "valueの20%をNULLにします。欠測の取り込み・集計確認用。",
        )
        s.fields[5].null_probability = 0.2
        s = add(
            "09-cyclic-counter",
            "周期カウンター / 0〜59",
            "sequence_noが0〜59を繰り返します。idは各行で異なるため主キーは衝突しません。",
        )
        s.fields[1].modulo = 60
        s = add(
            "10-grouped-clock",
            "グループ時刻 / 20件で1秒",
            "20レコードごとにevent_timeを1秒進めます。複数ソースから同時刻に発生するデータの例。",
        )
        s.fields[6].group_size = 20
        s = add(
            "11-historical-replay",
            "過去データ / 時系列再現",
            "過去の日付から0.1秒刻みで生成。生成速度とイベント日時を分けて制御します。",
        )
        s.parameters["start_time"] = "2025-01-01T00:00:00+09:00"
        s.fields[6].group_size = 1
        s.fields[6].step = 0.1
        s = add(
            "12-high-cardinality",
            "多数ソース / 10万種類",
            "entity_noを1〜10万から選択。高カーディナリティ列の検証用。",
            10000,
        )
        s.parameters["entity_count"] = 100000
        s = add(
            "13-burst-load",
            "バースト / 500件ずつ",
            "500件ごとに1秒待機する、間欠的な投入負荷。",
            5000,
        )
        s.burst_rows = 500
        s.burst_pause_ms = 1000
        s.batch_size = 100
        s = add(
            "14-low-rate",
            "低速 / 毎秒2件",
            "少量ずつ増えるソースを再現。バッチ1件、毎秒2件。",
            60,
            2,
        )
        s.batch_size = 1
        s = add(
            "15-multilingual",
            "多言語文字列 / UTF-8",
            "状態に日本語と英語を混在させ、文字化けや列長を確認します。",
        )
        s.parameters["statuses"] = ["正常", "注意", "停止", "maintenance"]
        s = add(
            "16-decimal-amounts",
            "金額・数量 / 正確な小数",
            "demo_amountsを使用。数量・単価・計算金額を生成します。未作成ならテーブル作成操作が必要です。",
        )
        s.sql.table = "demo_amounts"
        s.fields = [
            FieldRule(name="id", generator="record_id", primary_key=True, length=64),
            FieldRule(
                name="quantity",
                data_type="integer",
                generator="integer",
                minimum=1,
                maximum=100,
            ),
            FieldRule(
                name="unit_price",
                data_type="decimal",
                generator="choice",
                choices=["12.50", "99.99", "1000.00"],
                precision=18,
                scale=2,
            ),
            FieldRule(
                name="total",
                data_type="decimal",
                generator="product",
                sources=["quantity", "unit_price"],
                precision=24,
                scale=2,
            ),
            FieldRule(
                name="currency", generator="choice", choices=["JPY", "USD", "EUR"]
            ),
        ]
        s = add(
            "17-json-attributes",
            "任意属性 / JSON列",
            "demo_jsonを使用。入れ子の属性をSQLのJSON相当列へ保存する例。",
        )
        s.sql.table = "demo_json"
        s.fields = [
            FieldRule(name="id", generator="record_id", primary_key=True, length=64),
            FieldRule(
                name="attributes",
                data_type="json",
                generator="choice",
                choices=[
                    {
                        "unit": "C",
                        "tags": ["a", "b"],
                        "limits": {"low": 0, "high": 100},
                    },
                    {
                        "unit": "kPa",
                        "tags": ["pressure"],
                        "limits": {"low": 10, "high": 500},
                    },
                ],
            ),
        ]
        s = add(
            "18-composite-key",
            "複合主キー / グループと番号",
            "demo_compositeを使用。group_noとsample_noの組み合わせを主キーにします。",
        )
        s.sql.table = "demo_composite"
        s.fields = [
            FieldRule(
                name="group_no",
                data_type="integer",
                generator="sequence",
                group_size=10,
                primary_key=True,
            ),
            FieldRule(
                name="sample_no",
                data_type="integer",
                generator="sequence",
                modulo=10,
                primary_key=True,
            ),
            FieldRule(
                name="value",
                data_type="number",
                generator="uniform",
                minimum=0,
                maximum=1,
                scale=6,
            ),
        ]
        s = add(
            "19-derived-ratio",
            "派生項目 / 差分と比率",
            "demo_ratiosを使用。totalとrejectからgoodとyield_ratioを計算します。",
        )
        s.sql.table = "demo_ratios"
        s.fields = [
            FieldRule(name="id", generator="record_id", primary_key=True, length=64),
            FieldRule(
                name="total",
                data_type="integer",
                generator="integer",
                minimum=100,
                maximum=120,
            ),
            FieldRule(
                name="reject",
                data_type="integer",
                generator="integer",
                minimum=0,
                maximum=5,
            ),
            FieldRule(
                name="good",
                data_type="integer",
                generator="difference",
                sources=["total", "reject"],
            ),
            FieldRule(
                name="yield_ratio",
                data_type="number",
                generator="ratio",
                sources=["good", "total"],
                scale=6,
            ),
        ]
        s = add(
            "20-conditional-values",
            "条件による値変更",
            "statusがstoppedならvalueを0に置き換えます。先行項目を使った条件分岐の例。",
        )
        s.fields[5].condition = Condition(
            field="status", operator="eq", value="stopped", then_value=0
        )
        for identity, name, operation, mean in [
            ("21-insert-seed", "CRUD 1 / 初回追加", "insert", 40),
            ("22-upsert-refresh", "CRUD 2 / 同じキーを更新", "upsert", 70),
            ("23-update-existing", "CRUD 3 / 既存行だけ更新", "update", 90),
        ]:
            s = add(
                identity,
                name,
                "demo_upsertへ同じrun_keyとseedで120件生成。21は初回だけ、22は繰り返し可能、23は21または22の実行後に使用します。",
            )
            s.run_key = "crud-demo"
            s.sql.table = "demo_upsert"
            s.sql.operation = operation
            s.parameters["value_mean"] = mean
        s = add(
            "24-resume-sequence",
            "シーケンスの途中から再開",
            "既存系列と同じrun_key・seedを指定し、start_sequenceを変更する例。",
        )
        s.run_key = "resume-demo"
        s.start_sequence = 100000
    elif kind == "files":
        s = add(
            "05-jsonl",
            "JSONL / 1行1レコード",
            "JSONのみ。1ファイル50件の改行区切りJSON。",
        )
        s.files.formats = ["json"]
        s.files.json_mode = "jsonl"
        s.files.records_per_file = 50
        s = add(
            "06-nested-json",
            "入れ子JSON / 属性と測定値",
            "共有パラメーターと生成項目から入れ子のオブジェクト・配列を作ります。",
        )
        s.files.formats = ["json"]
        s.files.json_template = {
            "entity": {"id": "$row.entity_id"},
            "metrics": [{"name": "value", "value": "$row.value"}],
            "state": "$row.status",
            "key": "$meta.record_key",
        }
        s.files.json_pretty = True
        s = add(
            "07-object-gzip",
            "単件JSON / gzip圧縮",
            "1レコード1ファイルのJSONをgzip圧縮。",
        )
        s.files.formats = ["json"]
        s.files.json_mode = "object"
        s.files.compression = "gzip"
        s = add(
            "08-pretty-unicode",
            "整形JSON / 日本語",
            "日本語を含むJSONを字下げして保存します。",
        )
        s.files.formats = ["json"]
        s.files.json_pretty = True
        s.parameters["statuses"] = ["正常", "注意", "停止"]
        s = add(
            "09-csv-semicolon",
            "CSV / セミコロン・全引用",
            "全セル引用、セミコロン区切り、CRLF、BOM付きUTF-8。",
        )
        s.files.formats = ["csv"]
        s.files.csv_delimiter = ";"
        s.files.csv_quoting = "all"
        s.files.csv_newline = "CRLF"
        s = add(
            "10-tsv-no-header",
            "TSV / タブ区切り・ヘッダーなし",
            "タブ区切り、ヘッダーなし、BOMなしUTF-8。拡張子は.csvです。",
        )
        s.files.formats = ["csv"]
        s.files.csv_delimiter = "\t"
        s.files.csv_header = False
        s.files.csv_encoding = "utf-8"
        s = add(
            "11-csv-null-marker",
            "CSV / NULLと引用規則",
            "欠測値をNULL文字列で表現。文字列セルを引用します。",
        )
        s.files.formats = ["csv"]
        s.files.csv_null_value = "NULL"
        s.files.csv_quoting = "nonnumeric"
        s.fields[5].null_probability = 0.3
        s = add(
            "12-csv-gzip", "CSV / gzip分割", "50件ずつCSVを分割しgzipで保存します。"
        )
        s.files.formats = ["csv"]
        s.files.compression = "gzip"
        s.files.records_per_file = 50
        s = add(
            "13-grid-png",
            "画像 / 格子PNG",
            "格子の人工画像とsidecarを全レコード分生成。",
            12,
        )
        s.files.formats = ["image"]
        s.files.image.every = 1
        s.files.image.pattern = "grid"
        s = add(
            "14-gradient-jpeg",
            "画像 / グラデーションJPEG",
            "640×480のグラデーション。品質75で保存します。",
            12,
        )
        s.files.formats = ["image"]
        s.files.image.every = 1
        s.files.image.format = "jpeg"
        s.files.image.pattern = "gradient"
        s.files.image.width = 640
        s.files.image.height = 480
        s.files.image.quality = 75
        s = add(
            "15-dots-noise",
            "画像 / 点群とノイズ",
            "256×256の点群に小さなノイズ。疑似欠陥率20%。",
            12,
        )
        s.files.formats = ["image"]
        s.files.image.every = 1
        s.files.image.pattern = "dots"
        s.files.image.width = 256
        s.files.image.height = 256
        s.files.image.noise = 4
        s.files.image.defect_probability = 0.2
        s = add(
            "16-defect-labels",
            "画像 / 疑似欠陥ラベル",
            "全画像に傷状の線を描き、sidecarのラベルを確認します。",
            8,
        )
        s.files.formats = ["image"]
        s.files.image.every = 1
        s.files.image.defect_probability = 1
        s = add(
            "17-custom-colors",
            "画像 / 色と寸法を変更",
            "512×128、明るい背景・青い格子・赤い疑似欠陥。",
            8,
        )
        s.files.formats = ["image"]
        s.files.image.every = 1
        s.files.image.width = 512
        s.files.image.height = 128
        s.files.image.background = "#f0f4f8"
        s.files.image.foreground = "#2459a6"
        s.files.image.defect_color = "#e23232"
        s = add(
            "18-sparse-images",
            "表データ多数 / 画像は間引く",
            "JSONとCSVは全件、画像は100件に1枚。",
            1000,
        )
        s.files.image.every = 100
        s.files.records_per_file = 100
        s = add(
            "19-custom-paths",
            "任意パス / 命名テンプレート",
            "area共有値をディレクトリ名に使用し、連番中心のファイル名を付けます。",
        )
        s.parameters["area"] = "test-area"
        s.files.path_template = "{area}/{run_key}/{job_id}"
        s.files.filename_template = "records-{sequence:08d}"
        s.files.formats = ["json", "csv"]
        s = add(
            "20-json-array-values",
            "JSON配列の本文 / 任意構造",
            "各行を[id, entity_id, value]の配列に変換します。",
        )
        s.files.formats = ["json"]
        s.files.json_template = ["$row.id", "$row.entity_id", "$row.value"]
        s = add(
            "21-one-record-batches",
            "最小分割 / 1件ごとに確定",
            "1レコードずつJSON・CSV・マニフェストを保存します。",
            20,
        )
        s.files.formats = ["json", "csv"]
        s.files.records_per_file = 1
        s = add(
            "22-complete-bundle",
            "全形式 / 対応関係の確認",
            "JSON・CSV・画像・sidecar・SHA256付き完了マニフェストをまとめて確認。",
            20,
        )
        s.files.image.every = 1
        s.files.records_per_file = 10
        s = add(
            "23-burst-files",
            "バースト生成 / 100件ずつ",
            "100件単位で2秒待機。ファイル到着の偏りを再現します。",
            500,
        )
        s.files.formats = ["json", "csv"]
        s.files.records_per_file = 100
        s.burst_rows = 100
        s.burst_pause_ms = 2000
        s = add(
            "24-missing-and-weighted",
            "欠測と偏り / 混在レコード",
            "状態比率90:9:1、値の欠測率15%、JSONLとCSV。",
        )
        s.files.formats = ["json", "csv"]
        s.files.json_mode = "jsonl"
        s.fields[4].weights = [90, 9, 1]
        s.fields[5].null_probability = 0.15
    else:
        s = add(
            "05-flat-json",
            "平坦JSON / メタデータなし",
            "生成行をそのまま送信。idに安定したレコードキーが入ります。",
        )
        s.stream.envelope = False
        s = add(
            "06-nested-telemetry",
            "入れ子JSON / 測定値の配列",
            "任意の入れ子構造に変換して配送メタデータを追加します。",
        )
        s.stream.payload_template = {
            "device": "$row.entity_id",
            "measurements": [{"name": "value", "value": "$row.value"}],
            "status": "$row.status",
        }
        s = add(
            "07-dynamic-routing",
            "項目別の配送先 / テンプレート",
            "entity_idごとにevents.ENTITY-xxxxxへ配送先名を分けます。Kafka/NATS/AMQP側の対象作成・購読条件も合わせます。",
        )
        s.stream.topic_template = "events.{entity_id}"
        s = add(
            "08-http-ndjson",
            "HTTP / NDJSONバッチ",
            "HTTP受信APIを接続先に選択してください。1行1JSONのNDJSONで送ります。",
        )
        s.stream.http_body = "ndjson"
        s.batch_size = 20
        s = add(
            "09-http-single",
            "HTTP / 1件ずつ送信",
            "HTTP受信APIを接続先に選択してください。各リクエストの本文はJSONオブジェクト1件です。",
        )
        s.stream.http_body = "single"
        s.batch_size = 1
        s = add(
            "10-array-payload",
            "配列の本文 / 最小構造",
            "本文を[entity_id,value,event_time]へ変換。メタデータ追加は無効。",
        )
        s.stream.envelope = False
        s.stream.payload_template = ["$row.entity_id", "$row.value", "$row.event_time"]
        s = add(
            "11-weighted-status",
            "状態比率 / 98 : 1 : 1",
            "通常98%、warning1%、stopped1%の偏りを持つイベント。",
        )
        s.fields[4].weights = [98, 1, 1]
        s = add(
            "12-cyclic-counter",
            "周期カウンター / 0〜99",
            "sequence_noを0〜99の周期で繰り返します。record_keyは重複しません。",
        )
        s.fields[1].modulo = 100
        s = add(
            "13-paced-events",
            "定常送信 / 毎秒10件",
            "バッチ10件で毎秒10件を目標に送信します。イベント日時は10件ごとに1秒進みます。",
            300,
            10,
        )
        s.batch_size = 10
        s = add(
            "14-burst-1000",
            "バースト / 1000件と休止",
            "1000イベントごとに2秒休止。速度制限なしでバッチ100件ずつ処理。",
            5000,
        )
        s.burst_rows = 1000
        s.burst_pause_ms = 2000
        s = add(
            "15-jitter",
            "間隔のゆらぎ / 遅延を再現",
            "毎秒20件を目標に、待機へ最大300msのゆらぎを追加します。",
            300,
            20,
        )
        s.batch_size = 10
        s.jitter_ms = 300
        s = add(
            "16-many-sources",
            "多数ソース / 10万種類",
            "entity_idの種類を10万へ拡大し、高カーディナリティのイベントを生成。",
            10000,
        )
        s.parameters["entity_count"] = 100000
        s = add(
            "17-nullable-values",
            "欠測イベント / NULL率25%",
            "測定値が25%の確率でNULLになるイベント。",
        )
        s.fields[5].null_probability = 0.25
        s = add(
            "18-deterministic",
            "再現性 / 同一キーとシード",
            "run_keyを固定。再実行は既存outboxの同じデータを二重登録しません。生成条件を変える場合はrun_keyも変えます。",
            1000,
        )
        s.run_key = "deterministic-demo"
        s.seed = 123
        s = add(
            "19-resume",
            "途中から / シーケンス10万",
            "開始位置を10万に設定した分割生成。再開元とrun_key・seedを合わせて使用します。",
        )
        s.run_key = "resume-demo"
        s.start_sequence = 100000
        s = add(
            "20-historical",
            "過去データ / 高速リプレイ",
            "2025年の日時から0.01秒刻みでイベントを生成し、速度制限なしで送信。",
            1000,
        )
        s.parameters["start_time"] = "2025-01-01T00:00:00+09:00"
        s.fields[6].group_size = 1
        s.fields[6].step = 0.01
        s = add(
            "21-unicode",
            "多言語イベント / UTF-8",
            "日本語・英語の状態を含めたJSONの受信確認。",
        )
        s.parameters["statuses"] = ["稼働中", "停止", "点検待ち", "maintenance"]
        s = add(
            "22-derived-values",
            "派生イベント / 計算と条件",
            "生成したaとbからsumを計算し、a>80ならalert=trueにします。",
        )
        s.fields = [
            FieldRule(name="id", generator="record_id", length=64),
            FieldRule(
                name="a",
                data_type="integer",
                generator="integer",
                minimum=0,
                maximum=100,
            ),
            FieldRule(
                name="b",
                data_type="integer",
                generator="integer",
                minimum=0,
                maximum=100,
            ),
            FieldRule(
                name="sum", data_type="integer", generator="sum", sources=["a", "b"]
            ),
            FieldRule(
                name="alert",
                data_type="boolean",
                generator="constant",
                value=False,
                condition={
                    "field": "a",
                    "operator": "gt",
                    "value": 80,
                    "then_value": True,
                },
            ),
        ]
        s = add(
            "23-sparse-events",
            "まばらなイベント / 毎秒2件",
            "バッチ1件・毎秒2件・開始待機3秒。低頻度ソースの試験。",
            60,
            2,
        )
        s.batch_size = 1
        s.initial_delay_seconds = 3
        s = add(
            "24-custom-envelope",
            "独自メタデータ名 / metadata",
            "配送情報のキーをmetadataへ変更し、本文をdataの入れ子にします。",
        )
        s.stream.metadata_key = "metadata"
        s.stream.payload_template = {
            "data": {
                "id": "$row.entity_id",
                "value": "$row.value",
                "state": "$row.status",
            }
        }
    from scenario_presets import anomaly_library

    for identity, spec in result.items():
        original = spec.description
        if kind == "sql":
            assumption = "MES・ERPのソースDBからCDCで取り込む前の、正常データの基準・DB書き込み挙動を確認する想定です。"
            verify = "投入前後の行数、主キーの重複、列型、COMMIT単位、CDCでの変更内容。"
            prerequisite = "接続先を選択し、列・主キーを確認してください。独自テーブルのプリセットは接続先のDDLを確認し、必要に応じて作成してください。"
        elif kind == "files":
            assumption = "設備・検査装置・バッチ連携からランディングへ届くファイルを想定し、指定した形式の読み込み互換性を確認します。"
            verify = "パーサーの解釈、レコード数、文字コード、マニフェストのSHA256、画像とレコードの対応。"
            prerequisite = "保存先の権限と容量を確認。job_idを含むパスなら実行ごとに別領域へ保存します。画像は人工パターンです。"
        else:
            assumption = (
                "設備イベントやMES・ERPの連携イベントを受信側へ継続配送する想定です。"
            )
            verify = "実測レート、event_timeと受信時刻、record_keyによる重複排除、outboxの配送状態。"
            prerequisite = "使用するブローカー/APIを接続先から選択してください。HTTP形式の設定はHTTP接続時に適用。キャプチャは外部へ送信しません。"
        spec.description = f"【想定する状況】\n{assumption}\n\n【このプリセットの内容】\n{original} 件数{spec.rows:,}、目標速度{spec.target_rate:,}件/秒（0は制限なし）。\n\n【確認すること】\n{verify}\n\n【実行前の条件】\n{prerequisite} 設定は自由に変更して別名保存できます。"
    result.update(anomaly_library(kind))
    for identity, spec in result.items():
        # Re-validate nested assignments and check sample records without running the source.
        result[identity] = validate_generation(
            RunSpec.model_validate(spec.model_dump())
        )
    return result


def write_library(kind, directory):
    """配布用のJSONと、用途を確認するための索引を出力する。"""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    rows = [
        "# プリセット一覧",
        "",
        f"{kind}: 48種類（通常24・異常24）。接続プロファイルは別途選択できます。各JSONを画面から編集・複製・保存できます。",
        "",
        "| ID | 表示名 | 件数 | 用途・条件 |",
        "| --- | --- | ---: | --- |",
    ]
    for identity, spec in library(kind).items():
        (directory / (identity + ".json")).write_text(
            spec.model_dump_json(indent=2) + "\n"
        )
        rows.append(
            f"| {identity} | {spec.name} | {spec.rows:,} | "
            + spec.description.replace("\n", "<br>")
            + " |"
        )
    (directory / "README.md").write_text("\n".join(rows) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=["sql", "files", "stream"], required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "presets")
    args = parser.parse_args()
    write_library(args.kind, args.output)
    print("Saved 48 presets:", args.kind)
