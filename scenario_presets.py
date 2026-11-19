"""Manufacturing MES/ERP data anomalies and bounded, app-local processing faults."""

from config import AnomalyRule, FaultOptions, FieldRule, RunSpec


def key():
    return FieldRule(name="id", generator="record_id", primary_key=True, length=64)


def at():
    return FieldRule(
        name="event_time",
        data_type="datetime",
        generator="timestamp",
        start="$start_time",
        group_size=1,
    )


def dataset(spec, kind):
    if kind == "quality":
        spec.sql.table = "scenario_mes_quality"
        spec.fields = [
            key(),
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
            at(),
        ]
    elif kind == "routing":
        spec.sql.table = "scenario_mes_routing"
        spec.parameters["valid_work_orders"] = ["WO-0001", "WO-0002", "WO-0003"]
        spec.fields = [
            key(),
            FieldRule(
                name="equipment_id", generator="choice", choices=["EQ-01", "EQ-02"]
            ),
            FieldRule(
                name="work_order_id", generator="choice", choices="$valid_work_orders"
            ),
            FieldRule(
                name="process_step", data_type="integer", generator="sequence", modulo=5
            ),
            FieldRule(
                name="state", generator="choice", choices=["RUNNING", "IDLE", "ALARM"]
            ),
            at(),
        ]
    elif kind == "inventory":
        spec.sql.table = "scenario_erp_inventory"
        spec.fields = [
            key(),
            FieldRule(
                name="item_id",
                generator="choice",
                choices=["ITEM-A", "ITEM-B", "ITEM-C"],
            ),
            FieldRule(
                name="qty_on_hand",
                data_type="integer",
                generator="integer",
                minimum=100,
                maximum=1000,
            ),
            FieldRule(
                name="reserved",
                data_type="integer",
                generator="integer",
                minimum=0,
                maximum=50,
            ),
            FieldRule(
                name="available",
                data_type="integer",
                generator="difference",
                sources=["qty_on_hand", "reserved"],
            ),
            at(),
        ]
    elif kind == "amounts":
        spec.sql.table = "scenario_erp_amounts"
        spec.fields = [
            key(),
            FieldRule(
                name="invoice_id", generator="template", template="INV-{sequence:08d}"
            ),
            FieldRule(
                name="quantity",
                data_type="integer",
                generator="integer",
                minimum=1,
                maximum=50,
            ),
            FieldRule(
                name="unit_price",
                data_type="decimal",
                generator="choice",
                choices=["12.50", "99.99", "250.00"],
                scale=2,
            ),
            FieldRule(
                name="amount",
                data_type="decimal",
                generator="product",
                sources=["quantity", "unit_price"],
                precision=24,
                scale=2,
            ),
            FieldRule(name="currency", generator="constant", value="USD"),
            at(),
        ]
    elif kind == "documents":
        spec.sql.table = "scenario_erp_documents"
        spec.fields = [
            key(),
            FieldRule(
                name="document_id", generator="template", template="DOC-{sequence:08d}"
            ),
            FieldRule(
                name="order_id", generator="choice", choices=["ORDER-01", "ORDER-02"]
            ),
            FieldRule(
                name="quantity",
                data_type="integer",
                generator="integer",
                minimum=1,
                maximum=50,
            ),
            FieldRule(name="status", generator="choice", choices=["OPEN", "CLOSED"]),
            FieldRule(
                name="shipped_qty",
                data_type="integer",
                generator="reference",
                sources=["quantity"],
                condition={"field": "status", "value": "OPEN", "then_value": 0},
            ),
            at(),
        ]
    elif kind == "references":
        spec.sql.table = "scenario_erp_references"
        spec.parameters["valid_products"] = ["PRODUCT-A", "PRODUCT-B", "PRODUCT-C"]
        spec.fields = [
            key(),
            FieldRule(
                name="order_id", generator="choice", choices=["ORDER-01", "ORDER-02"]
            ),
            FieldRule(name="product_id", generator="choice", choices="$valid_products"),
            FieldRule(
                name="quantity",
                data_type="integer",
                generator="integer",
                minimum=1,
                maximum=50,
            ),
            at(),
        ]


def anomaly_library(tool):
    items = {}

    def add(
        number,
        slug,
        title,
        assumption,
        signal,
        verify,
        field=None,
        operation="set",
        value=None,
        data=None,
        **rule,
    ):
        identity = f"{number:02d}-{slug}"
        spec = RunSpec(
            name="異常 / " + title,
            description="",
            rows=120,
            target_rate=0,
            batch_size=10,
            run_key=identity,
            max_duration_seconds=600,
        )
        spec.files.formats = ["json", "csv"]
        spec.files.records_per_file = 10
        if data:
            dataset(spec, data)
        if field:
            spec.anomalies = [
                AnomalyRule(
                    name=title,
                    field=field,
                    operation=operation,
                    value=value,
                    from_row=20,
                    to_row=39,
                    **rule,
                )
            ]
        expected = "データ自体の異常です。DBや受信先に制約がなければ生成・配送は完了し、取り込み側の品質チェックで検知する想定です。"
        spec.description = f"【想定する状況】\n{assumption}\n\n【発生するデータ・タイミング】\n{signal}\n\n【確認すること】\n{verify}\n\n【実行・判定】\n{expected} 通常は0〜19件目が正常、20〜39件目が異常、40件目以降は復帰します。位置・割合・条件は異常ルールで編集できます。"
        if tool == "sql" and spec.sql.table != "sample_records":
            spec.description += (
                " SQLでは"
                + spec.sql.table
                + "を使用します。接続先で検証用テーブルのDDLを確認し、必要に応じて作成してください。"
            )
        items[identity] = spec
        return spec

    add(
        25,
        "mes-sensor-spike",
        "MES センサーの突発値",
        "測定系への瞬間的なノイズや設備の異常発熱を想定。平均50付近の値に短い高値区間を混ぜます。",
        "valueを20〜39件目だけ250へ変更。前後は通常の正規分布です。",
        "範囲チェック、異常期間の可視化、元の正常データへの復帰、異常レコードの隔離。",
        field="value",
        value=250,
    )
    add(
        26,
        "mes-sensor-drift",
        "MES センサーの徐々なドリフト",
        "校正ずれや温度上昇で値が徐々に偏るケース。単発の閾値超過より検知しにくい変化を再現します。",
        "valueへ20件目から1件ごとに2を追加するramp。39件目で最大+38、その後は復帰。",
        "移動平均や傾向監視、単純な閾値検知との差、校正前後の比較。",
        field="value",
        operation="ramp",
        value=2,
    )
    add(
        27,
        "mes-stuck-signal",
        "MES センサー値の固着",
        "センサーや通信キャッシュが停止し、時刻やレコードは増えるのに測定値が変化しない状態。",
        "20〜39件目のvalueを20件目の値に固定します。IDとevent_timeは進みます。",
        "連続同値、分散ゼロ、更新時刻と測定値の食い違いの検知。",
        field="value",
        operation="freeze",
    )
    add(
        28,
        "mes-missing-values",
        "MES 測定値の欠測",
        "一時的な機器読み取り失敗や、MESへの登録時に測定値が空になるケース。",
        "20〜39件目で50%の確率でvalueをNULL。seedが同じなら欠測位置も再現します。",
        "NULL率、欠測補完、集計の分母、欠測を0と誤認しないこと。",
        field="value",
        operation="null",
        probability=0.5,
    )
    add(
        29,
        "mes-late-events",
        "MES 遅延・順序逆転",
        "設備側のバッファやネットワーク遅延で、遅いイベント時刻のデータが後から到着する状態。",
        "20〜39件目のうち2件ごとにevent_timeを120秒戻します。配送順そのものはシーケンス順です。",
        "event_timeと取り込み時刻の区別、遅延許容窓、時系列の再整列。",
        field="event_time",
        operation="timestamp_shift",
        value=-120,
        every=2,
    )
    add(
        30,
        "mes-clock-skew",
        "MES 設備時計が未来へずれる",
        "NTP不調や設備時計の設定誤りで、1日先の時刻が登録されるケース。",
        "20〜39件目のevent_timeを86400秒進めます。タイムゾーン表記は有効なままです。",
        "未来時刻の検知、時刻補正、ダッシュボードの最新値が引っ張られないこと。",
        field="event_time",
        operation="timestamp_shift",
        value=86400,
    )
    add(
        31,
        "mes-unit-mismatch",
        "MES 単位・倍率の食い違い",
        "単位変更が伝わらず、kPa/Paやmm/µmのように1000倍の値が混在する状況。",
        "20〜39件目のvalueを1000倍にします。列名や型は変えません。",
        "単位のメタデータ管理、桁違い検知、範囲外データを正常平均へ混ぜないこと。",
        field="value",
        operation="multiply",
        value=1000,
    )
    add(
        32,
        "mes-unknown-state",
        "MES 未知の状態コード",
        "設備ファームウェアやMESバージョン更新で、未定義の状態コードが出るケース。",
        "20〜39件目のstatusをUNKNOWN_CODEへ変更します。文字列としては正常です。",
        "列挙値の検証、未知コードの隔離、スキーマ進化と既存集計への影響。",
        field="status",
        value="UNKNOWN_CODE",
    )
    add(
        33,
        "mes-negative-quantity",
        "MES 負の生産数量",
        "符号の取り違えや取消処理を通常実績として登録してしまうケース。",
        "totalを-20へ変更。good/reject/yield_ratioは変更前の計算値を残します。",
        "数量>=0とtotal=good+rejectの両方の検証。取消イベントとの区別。",
        field="total",
        value=-20,
        data="quality",
    )
    add(
        34,
        "mes-reject-exceeds-total",
        "MES 不良数が生産数を超える",
        "不良実績の二重登録や集計単位の混在で、不良数が総数より大きくなる状態。",
        "rejectを180へ変更。通常のtotalは100〜120です。",
        "reject<=total、集計粒度、重複検知、良品数との整合性。",
        field="reject",
        value=180,
        data="quality",
    )
    add(
        35,
        "mes-impossible-yield",
        "MES 歩留まりが100%を超える",
        "歩留まりの分母間違い、パーセントと比率の混同などを想定。",
        "yield_ratioだけを1.2へ変更。total/good/rejectは正常のままです。",
        "比率0〜1の範囲とgood/totalの再計算一致。表示上の120%を見落とさないこと。",
        field="yield_ratio",
        value=1.2,
        data="quality",
    )
    add(
        36,
        "mes-orphan-work-order",
        "MES 存在しない製造指図",
        "MES実績がERPの指図マスターへ結合できないケース。連携順序のずれも想定します。",
        "work_order_idをWO-MISSINGへ変更。通常の有効IDはparameters.valid_work_ordersに列挙しています。",
        "参照整合性、遅延到着マスターの待ち合わせ、未結合レコード数の監視。",
        field="work_order_id",
        value="WO-MISSING",
        data="routing",
    )
    add(
        37,
        "mes-route-step-jump",
        "MES 工程番号の飛び",
        "工程スキップ、ルート版の違い、手入力ミスで予定外の工程番号が記録される状態。",
        "process_stepへ100を加えます。通常は0〜4の周期です。",
        "ルートマスターとの照合、工程順序の検査、リワークと異常工程の区別。",
        field="process_step",
        operation="add",
        value=100,
        data="routing",
    )
    add(
        38,
        "erp-negative-stock",
        "ERP マイナス在庫",
        "出庫の先行連携、二重出庫、棚卸調整の誤りで在庫が負になるケース。",
        "qty_on_handを-5へ変更。reserved/availableは元の値を残します。",
        "在庫の下限、available=qty_on_hand-reservedの一致、出入庫の重複と到着順。",
        field="qty_on_hand",
        value=-5,
        data="inventory",
    )
    add(
        39,
        "erp-over-reservation",
        "ERP 引当が在庫を超える",
        "並行した指図引当や在庫更新の遅れにより、在庫以上に予約される状態。",
        "reservedを2000へ変更。通常qty_on_handは100〜1000です。",
        "引当<=在庫、有効在庫の再計算、拠点・ロット単位の整合性。",
        field="reserved",
        value=2000,
        data="inventory",
    )
    add(
        40,
        "erp-amount-discrepancy",
        "ERP 数量×単価と金額の不一致",
        "丸め差、税区分、転記ミス、誤った再計算で請求金額が合わないケース。",
        "amountへ0.01加算。quantityとunit_priceは変更しません。",
        "正確な小数演算、通貨ごとの丸め、許容差、金額再計算の照合。",
        field="amount",
        operation="add",
        value="0.01",
        data="amounts",
    )
    add(
        41,
        "erp-duplicate-document",
        "ERP 業務伝票の重複",
        "取り込みの再実行や送信側リトライで、同じ伝票番号が別レコードとして届く状態。",
        "20〜39件目のdocument_idを先頭行の番号に置き換えます。技術的なidは異なるため通常のPKでは検知できません。",
        "業務キーによる重複排除、技術IDとの違い、売上や在庫を二重計上しないこと。",
        field="document_id",
        operation="copy_from",
        value=0,
        data="documents",
    )
    add(
        42,
        "erp-orphan-product",
        "ERP 未登録の品目参照",
        "品目マスターより先に明細が届く、または廃番・コード変換の誤りで結合に失敗するケース。",
        "product_idをPRODUCT-MISSINGへ変更。通常の有効コードはparameters.valid_productsに列挙しています。",
        "参照マスターの遅延、未結合率、誤ったinner joinで明細が消えないこと。",
        field="product_id",
        value="PRODUCT-MISSING",
        data="references",
    )
    s = add(
        43,
        "invalid-value-type",
        "数値欄へ文字列が混入",
        "機器が数値の代わりにエラー文字列を返す、CSV連携で型推論が崩れる状況。",
        "valueへSENSOR_ERRORを入れ、型検証の迂回を明示的に有効化します。",
        "数値変換エラーの隔離、型の変化、元データの保持。SQLではバッチが拒否され停止し得ます。",
        field="value",
        value="SENSOR_ERROR",
        bypass_validation=True,
    )
    s.description += (
        " 意図的な不正型なので、SQLで失敗すること自体が期待する試験結果です。"
    )
    s = add(
        44,
        "missing-required-field",
        "必須項目そのものが欠落",
        "ソースのスキーマ変更やシリアライズ不具合で、NULLではなくキー自体が消えるケース。",
        "20〜39件目のvalueキーを削除します。JSON/ストリームは欠落、CSVは空セルになります。",
        "NULLと欠落の区別、スキーマ検査、必須列不足時の隔離。SQLは列データ不足として停止し得ます。",
        field="value",
        operation="omit",
    )
    if tool == "sql":
        s = add(
            45,
            "sql-duplicate-primary-key",
            "SQL 主キー重複 / 意図的な失敗",
            "再送を単純insertで取り込んだ際の主キー衝突。",
            "10件ずつcommit。20〜39件目のidを先頭のidへ変更し、重複するバッチはrollbackします。",
            "成功済みバッチと失敗バッチの境界、再実行のupsert設計、CDCに未commitデータが出ないこと。",
            field="id",
            operation="copy_from",
            value=0,
        )
        s.sql.operation = "insert"
        s.description += " run_keyを新しくして実行してください。失敗バッチは確定せず、前のcommitは残ります。"
        s = add(
            46,
            "sql-rollback-fault",
            "SQL COMMIT前の障害",
            "DBの通信障害やアプリ停止で、書き込んだトランザクションがcommitされない状況。",
            "1バッチ目の書き込み後・COMMIT前に意図的な例外を発生させます。",
            "バッチ全体のrollback、再実行、CDCへ未確定行が出ないこと。",
        )
        s.faults = FaultOptions(enabled=True, stage="after_write", action="fail")
        s = add(
            47,
            "sql-slow-batches",
            "SQL 処理遅延 / 断続的な待機",
            "ロック待ちや処理遅延に似た、アプリ側の待機を再現します。実際にDBをロック・停止する機能ではありません。",
            "最初の3バッチの処理前に1秒ずつ待機します。",
            "遅延による取り込みlag、停止要求、実行時間上限の挙動。",
        )
        s.faults = FaultOptions(
            enabled=True,
            stage="before_batch",
            action="delay",
            max_occurrences=3,
            delay_ms=1000,
        )
        s = add(
            48,
            "erp-cancelled-shipped",
            "ERP 取消済みなのに出荷済み",
            "取消伝票と出荷実績の連携順序や状態更新が食い違うケース。",
            "statusだけをCANCELLEDへ変更。CLOSEDだった行のshipped_qtyは正のまま残ります。",
            "状態と実績数量の横断チェック、取消と逆仕訳の関係。",
            field="status",
            value="CANCELLED",
            data="documents",
        )
    elif tool == "files":
        s = add(
            45,
            "file-truncated-json",
            "ファイル JSONの途中切れ",
            "ファイル転送や生成途中の中断で、JSONが構文として壊れた状態。",
            "JSONファイルの後半を意図的に切り落とします。CSVは正常で比較できます。",
            "JSONパーサーのエラー隔離、部分取り込みをしないこと、再処理の追跡。",
        )
        s.faults = FaultOptions(enabled=True, artifact_mode="truncate_json")
        s = add(
            46,
            "file-incomplete-bundle",
            "ファイル 完了前の中断",
            "JSON/CSVの一部または全部が到着しても、バッチの完了通知がまだないケース。",
            "ファイル保存後、ready.json作成前に意図的に停止。出力済みファイルはそのまま保持します。",
            "マニフェストを待つ取り込み、未完了ファイルの監視・期限管理、勝手に確定しないこと。",
        )
        s.faults = FaultOptions(enabled=True, stage="after_write", action="fail")
        s = add(
            47,
            "file-checksum-mismatch",
            "ファイル チェックサム不一致",
            "メタデータと実ファイルの版違いや転送破損を想定。",
            "完了マニフェストの最初のSHA256だけを誤った値にします。実ファイルは正常です。",
            "チェックサム検証、バッチの隔離、再取得と検証結果の記録。",
        )
        s.faults = FaultOptions(
            enabled=True, artifact_mode="manifest_checksum_mismatch"
        )
        s = add(
            48,
            "file-corrupt-images",
            "画像 破損・デコード失敗",
            "検査画像が途中で切れ、画像ヘッダーがあっても正常にデコードできないケース。",
            "人工PNGを先頭1/4に切り詰めます。sidecarとmanifestは残します。",
            "画像デコード、画像だけの隔離、レコードと画像の対応・再処理。",
        )
        s.rows = 12
        s.files.formats = ["image"]
        s.files.image.every = 1
        s.faults = FaultOptions(enabled=True, artifact_mode="truncate_image")
    else:
        s = add(
            45,
            "stream-before-send-fault",
            "配送 送信前の一時障害",
            "outboxへ永続化できたが、ネットワークへ送る前に接続が失敗する状態。",
            "2バッチ目の送信前に意図的に停止。最初の10件は配送済み、次の10件はpendingになる想定。",
            "pendingだけの再送、未生成分との区別、再起動後も記録が残ること。",
        )
        s.faults = FaultOptions(
            enabled=True, stage="before_batch", action="fail", from_batch=2
        )
        s = add(
            46,
            "stream-ack-loss",
            "配送 ACK消失 / 重複再送",
            "ブローカーには届いたが、送信側が配送済みと確定できない状況。",
            "2バッチ目を送信しACKを受けた直後、outbox更新前に意図的な例外。再送時は同じrecord_keyが再配送されます。",
            "受信側のrecord_keyによる重複排除、少なくとも1回配送の境界、二重計上を防ぐこと。",
        )
        s.faults = FaultOptions(
            enabled=True, stage="after_write", action="fail", from_batch=2
        )
        s = add(
            47,
            "stream-transient-retry",
            "配送 一過性の障害と自動再試行",
            "1回だけ接続エラーが出て、次の試行で回復する状態。",
            "2バッチ目の最初の送信前に1回だけ失敗。試行数3、待機200msで自動再試行します。",
            "全件配送、attemptsの増加、再試行による遅延と重複排除。",
        )
        s.faults = FaultOptions(
            enabled=True,
            stage="before_batch",
            action="fail",
            from_batch=2,
            max_occurrences=1,
        )
        s.stream.delivery_attempts = 3
        s.stream.retry_backoff_ms = 200
        s = add(
            48,
            "stream-backpressure-delay",
            "配送 遅延・バックプレッシャー",
            "受信側が遅い状態に似た、送信前の待機を再現。ブローカーや外部ネットワーク自体は変更しません。",
            "最初の3バッチの送信前に1秒ずつ待機します。",
            "outbox滞留、実測レート、最大実行時間、停止と再開。",
        )
        s.faults = FaultOptions(
            enabled=True,
            stage="before_batch",
            action="delay",
            max_occurrences=3,
            delay_ms=1000,
        )
    for spec in items.values():
        if spec.faults.enabled:
            if spec.faults.action == "fail":
                outcome = "この障害注入は意図的なfailed終了です。SQLは失敗バッチをrollback、ファイルは完了マニフェストを作らず、ストリームは配送を確定できない分をoutboxへ残します。成功済みの別バッチは残ります。"
            elif spec.faults.action == "delay":
                outcome = "意図的な待機が入ります。通常はcompletedとなりますが、時間上限や停止要求があれば途中で止まります。"
            else:
                outcome = "生成ジョブはcompletedでも、意図的に不正なファイルを含みます。取り込み側が検知・隔離することが期待する結果です。"
            spec.description = (
                spec.description.split("【実行・判定】")[0]
                + "【実行・判定】\n"
                + outcome
                + " 外部サーバーやネットワーク設定は変更しません。"
            )
    return items
