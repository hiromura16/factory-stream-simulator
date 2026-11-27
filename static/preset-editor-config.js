"use strict";

(() => {
  function field(path, label, type, options = {}) {
    return { path, label, type, ...options };
  }

  function choices(labels) {
    return Object.entries(labels).map(([value, label]) => ({ value, label }));
  }

  const generatorOptions = choices({
    record_id: "一意のレコードID", uuid: "UUID", sequence: "連番",
    integer: "ランダムな整数", uniform: "一様乱数", normal: "正規分布",
    choice: "候補から選択", boolean: "真偽値", constant: "固定値",
    template: "テンプレート", timestamp: "時刻", reference: "別の項目を参照",
    sum: "合計", difference: "差", product: "積", ratio: "比率",
  });

  const anomalyOptions = choices({
    set: "値の置き換え", add: "加算", multiply: "乗算", ramp: "段階変化",
    freeze: "値の固定", null: "欠損値", copy_from: "別項目からコピー",
    timestamp_shift: "時刻のずれ", omit: "項目を省略",
  });

  function generationSections(prefix) {
    return [
      {
        title: "データ項目と再現性",
        description: "同じシードと設定で同じ合成値を得られます。生成方式ごとの細かい条件はJSONで調整できます。",
        fields: [
          field(prefix + "run_key", "生成の識別子", "text", {
            help: "連番や一意IDの基準です。プリセットの保存IDとは別に指定します。",
          }),
          field(prefix + "seed", "乱数シード", "integer", { min: 0, max: 2147483647, default: 42 }),
          field(prefix + "parameters", "共通パラメーター", "json", {
            help: "JSONオブジェクトで定義します。対応する生成条件から $パラメーター名 で参照できます。",
          }),
          field(prefix + "fields", "生成する項目", "table", {
            default: { name: "new_field", data_type: "string", generator: "constant", value: "" },
            columns: [
              field("name", "項目名", "text"),
              field("data_type", "データ型", "select", {
                options: choices({
                  string: "文字列", integer: "整数", number: "数値", decimal: "小数",
                  boolean: "真偽値", datetime: "日時", json: "JSON",
                }),
              }),
              field("generator", "生成方式", "select", { options: generatorOptions }),
              field("template", "テンプレート", "text", {
                help: "テンプレート方式で参照できる例は {sequence} です。",
              }),
              field("value", "固定値（JSON）", "json"),
            ],
          }),
        ],
      },
      {
        title: "データの異常ルール",
        description: "対象の値を変える条件を追加します。位置は0始まりです。条件式や終了位置はJSONで調整できます。",
        fields: [
          field(prefix + "anomalies", "異常ルール", "table", {
            default: { field: "", operation: "null", from_row: 0, every: 1, enabled: true },
            columns: [
              field("enabled", "有効", "boolean", {default: true}),
              field("field", "対象項目", "text"),
              field("operation", "変更方法", "select", { options: anomalyOptions }),
              field("from_row", "開始位置", "integer", { min: 0, max: 100000000 }),
              field("every", "何件ごと", "integer", { min: 1, max: 100000000 }),
              field("value", "値（JSON）", "json"),
            ],
          }),
        ],
      },
    ];
  }

  function summarize(spec, preview) {
    const stream = spec?.stream || {};
    const duplicateRate = stream.duplicate_rate ?? 0;
    const count = Number.isFinite(spec?.rows) && spec.rows > 0
      && Number.isFinite(duplicateRate) && duplicateRate >= 0 && duplicateRate <= 1
      ? Math.round(spec.rows * (1 + duplicateRate)) : null;
    const number = new Intl.NumberFormat("ja-JP", { maximumFractionDigits: 2 });
    const rows = [];
    if (count !== null) {
      rows.push({ label: "配信予定（重複分を含む概算）", value: number.format(count) + " 件" });
      if (spec.target_rate === 0) {
        rows.push({ label: "目標レート", value: "制限なし" });
      } else if (Number.isFinite(spec.target_rate) && spec.target_rate > 0) {
        rows.push({ label: "所要時間の目安", value: number.format(count / spec.target_rate) + " 秒（待ち時間・再試行を除く）" });
      }
    }
    const samples = preview?.stream_messages;
    if (!Array.isArray(samples) || !samples.length) return rows;

    const first = samples[0];
    const average = samples.reduce((sum, item) => sum + item.bytes, 0) / samples.length;
    const bytes = new Intl.NumberFormat("ja-JP", { maximumFractionDigits: 0 });
    rows.push({ label: "配送先名の展開例", value: first.topic || "該当なし" });
    rows.push({ label: "本文サイズ（見本の平均）", value: bytes.format(average) + " B／件" });
    if (Number.isFinite(spec.target_rate) && spec.target_rate > 0) {
      rows.push({
        label: "本文帯域の目安",
        value: number.format(average * spec.target_rate / 1024) + " KiB／秒（ヘッダーを除く）",
      });
    }
    const firstPayload = preview.json_payloads?.[0];
    if (firstPayload !== undefined) {
      const body = JSON.stringify(firstPayload);
      rows.push({ label: "イベント本文の見本", value: body.length > 650 ? body.slice(0, 650) + "…" : body });
    }
    if (Array.isArray(preview.json_payloads)) {
      const batchSize = Number.isInteger(spec.batch_size) && spec.batch_size > 0 ? spec.batch_size : 1;
      const memberCount = Math.min(batchSize, 3);
      const members = preview.json_payloads.slice(0, memberCount);
      const mode = stream.http_body ?? "array";
      const body = mode === "ndjson"
        ? members.map((item) => JSON.stringify(item)).join("\n") + "\n"
        : JSON.stringify(mode === "single" ? members[0] : members);
      if (body) {
        rows.push({
          label: "HTTPの本文例（" + mode + "、最大3件）",
          value: body.length > 650 ? body.slice(0, 650) + "…" : body,
        });
      }
    }
    return rows;
  }

  window.FactoryPresetConfig = {
    title: "配信プリセット",
    description: "イベントの項目、配送先名、レートと障害条件を組み立てます。見本を作っても外部には送信しません。",
    summarize,
    sections: [
      {
        title: "配信先とペース",
        description: "認証・TLS・QoS・通信タイムアウトは接続先の設定で管理します。ここでは接続先を参照するだけです。",
        fields: [
          field("connection_id", "配送先プロファイル", "connection", { default: "default" }),
          field("stream.topic_template", "トピック／配送先名", "text", {
            placeholder: "factory/{entity_id}/events",
            help: "空欄なら接続先の設定を使用します。MQTTトピックやKafkaトピック、NATS subject、AMQP routing keyに使えます。",
          }),
          field("rows", "元イベント数", "integer", { min: 1, max: 100000000, default: 30 }),
          field("target_rate", "目標件数／秒", "integer", {
            min: 0, max: 1000000, default: 10, help: "0でレート制限なし。宛先の処理能力に応じて調整してください。",
          }),
          field("batch_size", "1バッチの最大件数", "integer", { min: 1, max: 10000, default: 1000 }),
          field("initial_delay_seconds", "開始までの待ち時間（秒）", "number", { min: 0, max: 3600, step: 0.01 }),
          field("jitter_ms", "待ち時間のばらつき（ms）", "integer", { min: 0, max: 60000 }),
          field("burst_rows", "集中的に送る件数", "integer", {
            min: 0, max: 1000000, help: "0でバーストなし。",
          }),
          field("burst_pause_ms", "バースト後の休止（ms）", "integer", { min: 0, max: 3600000 }),
        ],
      },
      {
        title: "イベント本文と付加情報",
        fields: [
          field("stream.envelope", "再送・重複検証用のメタデータを付ける", "boolean", { default: true }),
          field("stream.metadata_key", "メタデータのキー", "text", {
            default: "_source",
            when: { path: "stream.envelope", equals: true },
            help: "本文のキー名と重複させないでください。record_key、sequence、run_keyを含みます。",
          }),
          field("stream.payload_template", "本文のJSONテンプレート", "json", {
            help: "空欄は生成項目をそのまま利用。メタデータを付ける場合はJSONオブジェクトを指定します。",
          }),
          field("stream.http_body", "HTTPの本文形式", "select", {
            default: "array",
            options: choices({ array: "配列でまとめて送る", single: "1件ずつ送る", ndjson: "NDJSON（1行1件）" }),
          }),
          field("stream.message_size_bytes", "本文サイズの下限（B）", "integer", {
            min: 0, max: 65536,
            help: "MQTTとローカル記録で利用できます。0で埋め草を付けません。",
          }),
          field("stream.duplicate_rate", "重複を追加する確率", "number", {
            min: 0, max: 1, step: 0.01,
            help: "0.05は約5%。MQTTとローカル記録で利用できます。",
          }),
        ],
      },
      {
        title: "再試行と実行上限",
        fields: [
          field("stream.delivery_attempts", "配送試行回数", "integer", {
            min: 1, max: 10, help: "空欄は接続先の値。初回を含みます。",
          }),
          field("stream.retry_backoff_ms", "再試行の初回待ち時間（ms）", "integer", {
            min: 0, max: 60000, help: "空欄は接続先の値。待ち時間は試行ごとに増えます。",
          }),
          field("start_sequence", "開始連番", "integer", { min: 0, max: 1000000000 }),
          field("max_duration_seconds", "実行時間の上限（秒）", "integer", { min: 1, max: 86400 }),
          field("max_output_mb", "出力量の上限（MiB）", "integer", { min: 1, max: 1048576 }),
        ],
      },
      ...generationSections(""),
      {
        title: "バッチ障害の再現",
        description: "指定バッチでの遅延や失敗を再現する実行条件です。本文見本では障害処理を起動しません。",
        fields: [
          field("faults.enabled", "障害を有効にする", "boolean", { default: false }),
          field("faults.stage", "障害を入れる位置", "select", {
            when: { path: "faults.enabled", equals: true },
            options: choices({ before_batch: "バッチ処理の前", after_write: "書き込みの後" }),
          }),
          field("faults.action", "障害の種類", "select", {
            when: { path: "faults.enabled", equals: true },
            options: choices({ none: "なし", fail: "バッチ失敗", delay: "遅延" }),
          }),
          field("faults.from_batch", "開始バッチ（1始まり）", "integer", {
            min: 1, max: 100000000, when: { path: "faults.enabled", equals: true },
          }),
          field("faults.every_batches", "何バッチごと", "integer", {
            min: 1, max: 100000000, when: { path: "faults.enabled", equals: true },
          }),
          field("faults.max_occurrences", "最大発生回数", "integer", {
            min: 0, max: 1000000, when: { path: "faults.enabled", equals: true },
          }),
          field("faults.delay_ms", "遅延時間（ms）", "integer", {
            min: 0, max: 60000, when: { path: "faults.action", equals: "delay" },
          }),
        ],
      },
    ],
  };
})();
