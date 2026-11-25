// 設定画面の入口。APIのスキーマから編集欄を作り、接続・生成・履歴の操作をサーバーへ渡す。
"use strict";
const $ =
  /* 指定したセレクターに最初に一致するDOM要素を返す。一致しなければnull。 */
  (s) => document.querySelector(s),
  clone =
    /* 設定を構造化複製し、編集が保存済みの元オブジェクトへ波及するのを避ける。 */
    (v) => structuredClone(v);
// 選択例はデータ生成だけを定義し、ブローカーは利用者が別途選ぶ。
const streamScenarios = {
  equipment: ["設備稼働イベント", "LINE01", "RUN", "STOP", "value", 42],
  temperature: ["温度センサーイベント", "TEMP01", "NORMAL", "HIGH", "temperature_c", 23.5],
  process: ["工程進捗イベント", "PROCESS01", "IN_PROGRESS", "DELAYED", "progress_pct", 42],
  alarm: ["アラームイベント", "ALARM01", "WARNING", "CRITICAL", "severity", 2],
};
const scenarioDescriptions = {
  equipment: "設備のデータを収集する場面です。稼働中（RUN）の状態と計測値を持つメッセージを作ります。",
  temperature: "温度測定を収集する場面です。センサーIDと摂氏温度を持つメッセージを作ります。",
  process: "製造工程の進み具合を集める場面です。工程の状態と進捗率を持つメッセージを作ります。",
  alarm: "設備の警報を監視する場面です。警告（WARNING）を基本とし、一部を重大（CRITICAL）に置き換えます。",
};
const quickAnomaly = "クイックスタートの異常";

const state = {
  info: null,
  schemas: null,
  spec: null,
  connections: [],
  presets: [],
  profile: null,
  current: null,
  specRevision: 0,
  previewedDestination: null,
};
let uid = 0;
const el =
  /* タグと属性からDOM要素を作る。on接頭辞はイベント登録に使い、本文はHTMLとして解釈しない。 */
  (tag, attrs = {}, text = "") => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") n.className = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v);
  }
  if (text) n.textContent = text;
  return n;
};
// 通知欄の文面を差し替え、失敗通知だけにエラー表示のクラスを付ける。
function notify(text, error = false) {
  $("#notice").textContent = text;
  $("#notice").className = error ? "error" : "";
}
// 本文なしはGET、ありはJSON POSTで同一画面のAPIを呼ぶ。JSONを返し、HTTP失敗は詳細付き例外に変換する。
async function api(path, body, headers = {}) {
  const r = await fetch(
    path,
    body === undefined
      ? {}
      : {
          method: "POST",
          headers: { "Content-Type": "application/json", ...headers },
          body: JSON.stringify(body),
        },
  );
  const value = await r.json();
  if (!r.ok) {
    const error = new Error(
      typeof value.detail === "string"
        ? value.detail
        : JSON.stringify(value.detail || value),
    );
    error.status = r.status;
    throw error;
  }
  return value;
}
const action =
  /* ボタンを操作関数へ接続し、実行中の再操作防止と通知を共通化する。 */
  (id, fn) =>
  $(id).addEventListener("click", /* クリック既定動作を止め、処理中は押下不可にする。失敗は通知し、成否にかかわらず再度有効にする。 */ async (e) => {
    e.preventDefault();
    const b = e.currentTarget;
    b.disabled = true;
    try {
      await fn();
    } catch (err) {
      notify(err.message, true);
    } finally {
      b.disabled = false;
    }
  });
// 指定IDのタブと対応するナビ項目だけを選択状態にし、切替前のヘルプを閉じる。
function tab(id) {
  document
    .querySelectorAll(".tab")
    .forEach(/* 実際のタブ要素はDOMのIDで選択状態を判定する。 */ (n) => n.classList.toggle("active", n.id === id));
  document
    .querySelectorAll(".nav")
    .forEach(/* ナビ項目はdata-tabで選択先との一致を判定する。 */ (n) => n.classList.toggle("active", n.dataset.tab === id));
  hideTip();
}
// スキーマ内のローカル参照をルートの定義から解決する。参照でなければ元を返す。
function deref(schema, root) {
  return schema.$ref ? root.$defs[schema.$ref.split("/").pop()] : schema;
}
// 参照を解決し、明示既定値、固定値、null許容、型に応じてフォーム初期値を組み立てる。
function defaultValue(schema, root) {
  schema = deref(schema, root);
  if ("default" in schema) return clone(schema.default);
  if (schema.const !== undefined) return schema.const;
  if (schema.anyOf) {
    const choice = schema.anyOf.find(/* 複数候補からnull型を探し、任意項目が未設定で開始できるようにする。 */ (v) => v.type === "null");
    return choice ? null : defaultValue(schema.anyOf[0], root);
  }
  if (schema.type === "object")
    return Object.fromEntries(
      Object.entries(schema.properties || {}).map(/* オブジェクトの各プロパティ名と、再帰的に確定した初期値の組を返す。 */ ([k, v]) => [
        k,
        defaultValue(v, root),
      ]),
    );
  if (schema.type === "array") return [];
  if (schema.enum) return schema.enum[0];
  return schema.type === "boolean"
    ? false
    : schema.type === "integer" || schema.type === "number"
      ? 0
      : "";
}
// 折りたたみ可能な見出し・説明・入力領域を作り、外枠と追加先を別に返す。
function block(title, description, open = true) {
  const box = el("details", { class: "card" });
  box.open = open;
  box.append(el("summary", {}, title));
  if (description) box.append(el("p", { class: "muted" }, description));
  const body = el("div", { class: "grid" });
  box.append(body);
  return [box, body];
}
// スキーマの型やフィールド名に応じた入力要素を作り、妥当な変更をsetへ渡す。制約と補足を表示する。
function control(name, schema, value, set, root) {
  const outer = el("div", {
    class: "control hint",
    "data-help": schema.description || schema.title || name,
  });
  let shape = deref(schema, root);
  const id = "input-" + ++uid,
    label = el("label", { for: id }, schema.title || name);
  label.append(
    el(
      "span",
      {
        class: "help",
        tabindex: "0",
        "aria-label": (schema.title || name) + "の説明",
        "aria-describedby": "tooltip",
      },
      "?",
    ),
  );
  outer.append(label);
  const variants = schema.anyOf?.map(/* 複合型の各候補を解決し、参照先の型も描画方式の判定に使う。 */ (v) => deref(v, root));
  const obj = variants?.find(/* 複合型に入力欄を持つオブジェクト候補があるか判定する。 */ (v) => v.type === "object" && v.properties);
  if (obj) {
    const check = el("input", { type: "checkbox", id });
    check.checked = value !== null && value !== undefined;
    const checklabel = el("label", { class: "checklabel" });
    checklabel.append(check, document.createTextNode("条件を有効にする"));
    outer.append(checklabel);
    const inner = el("div", { class: "grid" });
    outer.append(inner);
    /* 任意の入れ子条件を再描画する。有効化時は未設定値を初期化し、無効化時はモデルへnullを返す。 */ function draw() {
      inner.replaceChildren();
      if (check.checked) {
        if (value == null) value = defaultValue(obj, root);
        set(value);
        renderObject(inner, obj, value, root);
      } else {
        value = null;
        set(null);
      }
    }
    check.addEventListener("change", draw);
    draw();
    outer.classList.add("subsection");
    return outer;
  }
  if (shape.type === "object" && shape.properties) {
    outer.classList.add("subsection");
    const inner = el("div", { class: "grid" });
    outer.append(inner);
    renderObject(inner, shape, value, root);
    return outer;
  }
  if (name === "connection_id") {
    const input = el("select", { id });
    for (const p of state.connections)
      input.append(el("option", { value: p.id }, p.name + " · " + p.kind));
    if (!state.connections.some(/* 編集中の接続IDが登録一覧にあるか確認する。なければ入力値を消さず未登録として表示する。 */ (p) => p.id === value))
      input.append(el("option", { value }, value + " (未登録)"));
    input.value = value;
    input.addEventListener("change", /* 接続先の変更時に、表示名ではなく選択されたプロファイルIDを記録する。 */ () => set(input.value));
    outer.append(input);
    return outer;
  }
  let input;
  const isJson =
    shape.type === "array" ||
    shape.type === "object" ||
    (!shape.type && !shape.enum && !schema.anyOf) ||
    variants?.some(/* 複合型に配列候補があればJSON入力欄として扱う。 */ (v) => v.type === "array");
  if (shape.enum) {
    input = el("select", { id });
    for (const v of shape.enum)
      input.append(
        el(
          "option",
          { value: String(v) },
          name === "kind"
            ? state.info.connection_help[v]?.label || v
            : ["database_auth", "file_auth"].includes(name)
              ? name === "database_auth" &&
                state.profile?.kind === "sqlserver" &&
                v === "password"
                ? "SQL Server 認証"
                : authLabels[v] || v
              : String(v),
        ),
      );
    input.value = String(value ?? shape.default ?? shape.enum[0]);
    input.addEventListener("change", /* 列挙選択の値を文字列として編集中のモデルへ渡す。 */ () => set(input.value));
  } else if (shape.type === "boolean") {
    input = el("input", { id, type: "checkbox" });
    input.checked = Boolean(value);
    input.addEventListener("change", /* チェック状態を文字列ではなく真偽値として保存する。 */ () => set(input.checked));
  } else if (isJson) {
    input = el("textarea", {
      id,
      rows: name === "parameters" || name.includes("template") ? "6" : "3",
      spellcheck: "false",
    });
    input.value = JSON.stringify(
      value === undefined ? defaultValue(schema, root) : value,
      null,
      2,
    );
    input.addEventListener("input", /* 有効なJSONだけをモデルに反映する。不正な編集中テキストは残し、フォーム側で送信を止める。 */ () => {
      try {
        const next = JSON.parse(input.value);
        input.setCustomValidity("");
        set(next);
      } catch {
        input.setCustomValidity("JSONの構文を確認してください");
      }
    });
    outer.append(
      el(
        "span",
        { class: "json-hint" },
        'JSONで編集 · 文字列は " "、空値は null',
      ),
    );
  } else if (name === "description") {
    input = el("textarea", { id, rows: "6" });
    input.value = value ?? "";
    input.maxLength = 1000;
    input.addEventListener("input", /* 説明欄の入力を加工せず編集モデルへ反映する。 */ () => set(input.value));
  } else if (["ssh_private_key", "connection_string"].includes(name)) {
    input = el("textarea", {
      id,
      rows: "4",
      spellcheck: "false",
      autocomplete: "off",
    });
    input.value = value ?? "";
    input.placeholder = "空欄は同じ接続先の保存済み値を維持";
    input.addEventListener("input", /* 複数行の認証入力を取り込み、空欄を明示の空文字ではなくnullにする。 */ () => set(input.value || null));
  } else {
    const numeric = shape.type === "integer" || shape.type === "number";
    const secret =
      shape.format === "password" ||
      schema.format === "password" ||
      variants?.some(/* 複合型候補にもパスワード形式が含まれるか調べる。 */ (v) => v.format === "password");
    input = el("input", {
      id,
      type: secret ? "password" : numeric ? "number" : "text",
      autocomplete: secret ? "new-password" : "off",
    });
    if (numeric) {
      input.step = shape.type === "integer" ? "1" : "any";
      for (const [k, a] of [
        ["minimum", "min"],
        ["maximum", "max"],
      ])
        if (shape[k] !== undefined) input[a] = shape[k];
    }
    if (shape.minLength) input.minLength = shape.minLength;
    if (shape.maxLength) input.maxLength = shape.maxLength;
    input.value = value ?? "";
    input.addEventListener("input", /* 秘密欄・複合型・数値で変換規則を分ける。複合型はJSONにならない入力も文字列として維持する。 */ () => {
      let v = input.value;
      if (secret) {
        set(v || null);
        return;
      }
      if (variants) {
        if (v === "") {
          set(null);
          return;
        }
        try {
          v = JSON.parse(v);
        } catch {}
      } else if (numeric) v = Number(v);
      set(v);
    });
    if (secret) input.placeholder = "空欄は保存済みの値を維持";
  }
  outer.append(input);
  return outer;
}
// 表示対象の各プロパティを描画し、モデルで未設定の項目だけ初期値を補う。
function renderObject(container, schema, model, root, exclude = []) {
  for (const [name, prop] of Object.entries(schema.properties || {})) {
    if (exclude.includes(name)) continue;
    if (!(name in model)) model[name] = defaultValue(prop, root);
    container.append(
      control(name, prop, model[name], /* 個別コントロールの更新を対応するモデルのプロパティへ書き戻す。 */ (v) => (model[name] = v), root),
    );
  }
}
// 同じ接続先を維持し、別実行として安全に試せる小さな合成イベントを用意する。
function scenarioSpec(id, defaults, connection, runKey, at = new Date().toISOString()) {
  const [name, entity, status, abnormal, metric, value] = streamScenarios[id];
  const spec = clone(defaults);
  Object.assign(spec, {
    name, run_key: runKey, rows: 30, target_rate: 5,
    batch_size: 5, connection_id: connection, connection_revision: null,
    parameters: { ...spec.parameters, start_time: at },
    description: scenarioDescriptions[id] + "\n\n合成イベント30件。送信前に接続先、トピック、本文を確認します。",
    fields: [
      { name: "entity_id", generator: "constant", value: entity },
      { name: "status", generator: "constant", value: status },
      { name: metric, data_type: "number", generator: "constant", value },
      { name: "event_time", data_type: "datetime", generator: "timestamp",
        start: "$start_time", step: 1, group_size: 1 },
    ],
    anomalies: [{
      name: quickAnomaly, field: "status", operation: "set",
      value: abnormal, probability: id === "alarm" ? 0.2 : 0,
    }],
  });
  return spec;
}

// 宛先・送信件数・レート・トピックを先に表示し、イベント定義は折りたたむ。
function renderStreamRun(root, target, advancedOpen) {
  const spec = state.spec;
  const [transport, controls] = block(
    "基本設定",
    "保存済みのブローカーとトピックを選びます。ローカル記録では外部へ送信しません。",
  );
  const selected = state.connections.find((item) => item.id === spec.connection_id);
  const topic = selected?.topic ?? "";
  controls.append(el(
    "p", { class: "muted" },
    selected
      ? "配信先: " + selected.name + " · " +
        (selected.kind === "mqtt"
          ? selected.host + (selected.port ? ":" + selected.port : "")
          : selected.kind) + " · 版 " + selected.revision
      : "保存済みの配信先を選んでください。",
  ));
  controls.append(control(
    "connection_id", { ...root.properties.connection_id, title: "ブローカー / 配信先" },
    spec.connection_id, (value) => {
      spec.connection_id = value;
      spec.connection_revision = null;
      renderRun();
      $("#runEditor select")?.focus();
    }, root,
  ));
  const fields = {
    rows: "送信件数（重複分を除く）",
    target_rate: "目標送信レート（メッセージ / 秒）",
  };
  for (const [key, title] of Object.entries(fields))
    controls.append(control(key, { ...root.properties[key], title }, spec[key],
      (value) => { spec[key] = value; }, root));
  const streamSchema = deref(root.properties.stream, root);
  const topicField = streamSchema.properties.topic_template;
  controls.append(control("topic_template", {
    ...topicField,
    title: "トピック / テンプレート",
    description: topicField.description + (topic ? " 空欄の場合の接続先トピック: " + topic : ""),
  }, spec.stream.topic_template, (value) => { spec.stream.topic_template = value; }, root));
  target.append(transport);

  const [advanced, body] = block(
    "詳細設定", "属性、本文のサイズ、重複率、再試行、異常や障害の条件を編集します。", advancedOpen,
  );
  advanced.id = "streamAdvanced";
  body.style.display = "block";
  const [common, general] = block("実行の上限・ペース・再現性", "", false);
  renderObject(general, root, spec, root, [
    "version", "connection_revision", "connection_id", "task", "rows", "target_rate",
    "parameters", "fields", "anomalies", "faults", "sql", "files", "stream",
  ]);
  const [parameters, params] = block("共有パラメーター", "", false);
  params.append(control("parameters", root.properties.parameters, spec.parameters,
    (value) => { spec.parameters = value; }, root));
  const [attrs, attrBody] = block("イベント定義 / イベント属性", "", false);
  attrBody.style.display = "block";
  renderFields(attrBody);
  const [bodyOptions, bodyControls] = block("本文形式 / 配送オプション", "", false);
  renderObject(bodyControls, streamSchema, spec.stream, root, ["topic_template"]);
  const [anomaly, anomalyBody] = block("異常率・異常イベントのルール", "", false);
  anomaly.id = "streamAnomalies";
  anomalyBody.style.display = "block";
  renderAnomalies(anomalyBody);
  const [fault, faultBody] = block("配送障害のシミュレーション", "", false);
  renderObject(faultBody, deref(root.properties.faults, root), spec.faults, root);
  body.append(common, parameters, attrs, bodyOptions, anomaly, fault);
  target.append(advanced);
}

// 編集入力が無効でも、進行中のプレビューを旧条件のまま表示しない。
function invalidatePreview() {
  state.specRevision++;
  state.previewedDestination = null;
  $("#previewPanel").hidden = true;
}

// 先頭に4つの操作例を並べ、クリックは設定の差し替えだけに限定する。
function renderQuickstart() {
  $("#quickstart").hidden = state.info.kind !== "stream";
  if (state.info.kind !== "stream") return;
  const target = $("#quickstartChoices");
  for (const [id, [name]] of Object.entries(streamScenarios)) {
    const button = el("button", { type: "button" }, name);
    button.addEventListener("click", () => {
      const next = "event-" + Date.now().toString(36) + "-" +
        crypto.getRandomValues(new Uint32Array(1))[0].toString(36);
      state.spec = scenarioSpec(id, state.info.defaults, state.spec.connection_id, next);
      renderRun();
      $("#quickstartScenario").textContent = scenarioDescriptions[id];
      notify(name + "を選択しました。接続先とトピックを確認してから送信してください。");
    });
    target.append(button);
  }
}

// 共通条件・生成列・出力方式・異常条件を、現在のサービスと設定に合わせて再描画する。
function renderRun() {
  const root = state.schemas.run,
    target = $("#runEditor");
  const advancedOpen = $("#streamAdvanced")?.open ?? false;
  target.replaceChildren();
  invalidatePreview();
  if (state.info.kind === "stream") return renderStreamRun(root, target, advancedOpen);
  const [common, body] = block(
    "01 / 実行条件",
    "生成量と速度、再現性を決めます。接続は保存済みのプロファイルを選択します。",
  );
  renderObject(body, root, state.spec, root, [
    "version",
    "connection_revision",
    "task",
    "parameters",
    "fields",
    "anomalies",
    "faults",
    "sql",
    "files",
    "stream",
  ]);
  target.append(common);
  const [param, pbody] = block(
    "02 / 共有パラメーター",
    "同じ値を複数の生成ルールから $名前 で参照できます。",
  );
  pbody.append(
    control(
      "parameters",
      root.properties.parameters,
      state.spec.parameters,
      /* JSON入力で検証済みのパラメーター集合を実行設定に戻す。 */ (v) => (state.spec.parameters = v),
      root,
    ),
  );
  pbody.firstChild.style.gridColumn = "1 / -1";
  target.append(param);
  const [fields, fbody] = block(
    "03 / 自由なデータ項目",
    "上から順に生成。他の項目を参照する場合は、参照元を先に置きます。",
  );
  fbody.style.display = "block";
  renderFields(fbody);
  target.append(fields);
  const key = { sql: "sql", files: "files", stream: "stream" }[state.info.kind];
  const [output, obody] = block(
    "04 / " + root.properties[key].title,
    root.properties[key].description,
  );
  renderObject(obody, deref(root.properties[key], root), state.spec[key], root);
  target.append(output);
  const [ab, ag] = block(
    "05 / データ異常の注入",
    "正常データへ、期間・割合・条件を指定して異常を重ねます。",
    false,
  );
  ag.style.display = "block";
  renderAnomalies(ag);
  target.append(ab);
  const [fb, fg] = block(
    "06 / 処理障害のシミュレーション",
    "この実行だけに障害や遅延を注入します。意図的にfailedで終了する設定があります。",
    false,
  );
  renderObject(
    fg,
    deref(root.properties.faults, root),
    state.spec.faults,
    root,
  );
  target.append(fb);
}
// 生成項目を順序どおりカード表示し、並べ替え・複製・追加を編集モデルに反映できるようにする。
function renderFields(parent) {
  parent.replaceChildren();
  const root = state.schemas.run,
    schema = root.$defs.FieldRule;
  state.spec.fields.forEach(/* 項目と配列位置を結び付け、基本入力・詳細入力・順序変更の操作を持つカードを作る。 */ (field, index) => {
    const card = el("div", { class: "field-card", "data-field-index": index }),
      head = el("div", { class: "field-head" });
    for (const key of ["name", "data_type", "generator"])
      head.append(
        control(
          key,
          schema.properties[key],
          field[key],
          /* 個別カードで基本項目を変更したとき、同じフィールドオブジェクトへ書き戻す。 */ (v) => {
            field[key] = v;
          },
          root,
        ),
      );
    const buttons = el("div", { class: "field-actions" });
    for (const [label, help, fn] of [
      [
        "↑",
        "項目を1つ上へ移動します",
        /* 先頭でない場合だけ直前の項目と交換する。評価順に影響するため配列そのものを更新する。 */ () => {
          if (index)
            [state.spec.fields[index - 1], state.spec.fields[index]] = [
              field,
              state.spec.fields[index - 1],
            ];
        },
      ],
      [
        "↓",
        "項目を1つ下へ移動します",
        /* 末尾でない場合だけ直後の項目と交換する。 */ () => {
          if (index < state.spec.fields.length - 1)
            [state.spec.fields[index + 1], state.spec.fields[index]] = [
              field,
              state.spec.fields[index + 1],
            ];
        },
      ],
      [
        "複製",
        "この項目と詳細条件を複製します",
        /* 設定全体を複製して別名を付け、元の項目の直後へ挿入する。 */ () => {
          const copy = clone(field);
          copy.name = field.name + "_copy";
          state.spec.fields.splice(index + 1, 0, copy);
        },
      ],
      [
        "削除",
        "このデータ項目を削除します",
        /* 全項目がなくならないよう最後の1件は残し、対象位置の項目を削除する。 */ () => {
          if (state.spec.fields.length > 1) state.spec.fields.splice(index, 1);
        },
      ],
    ]) {
      const b = el("button", { type: "button", "data-help": help }, label);
      b.addEventListener("click", /* カード操作後に一覧を作り直し、変更後の位置で次の操作を受け付ける。 */ () => {
        fn();
        invalidatePreview();
        renderFields(parent);
      });
      buttons.append(b);
    }
    head.append(buttons);
    card.append(head);
    const detail = el("details");
    detail.append(
      el("summary", {}, "詳細条件 · 分布 / 書式 / 参照 / NULL / 条件分岐"),
    );
    const grid = el("div", { class: "grid" });
    renderObject(grid, schema, field, root, ["name", "data_type", "generator"]);
    detail.append(grid);
    card.append(detail);
    parent.append(card);
  });
  const add = el(
    "button",
    { type: "button", id: "addField" },
    "＋ イベント属性を追加",
  );
  add.addEventListener("click", /* スキーマ既定値から例示用の項目を末尾に追加し、一覧を再描画する。 */ () => {
    const value = defaultValue(schema, root);
    value.name = "custom_" + (state.spec.fields.length + 1);
    value.value = "sample";
    state.spec.fields.push(value);
    invalidatePreview();
    renderFields(parent);
  });
  parent.append(add);
}
// 異常ルールを実行順に表示し、追加・削除を現在の実行設定に結び付ける。
function renderAnomalies(parent) {
  parent.replaceChildren();
  const root = state.schemas.run,
    schema = root.$defs.AnomalyRule;
  state.spec.anomalies.forEach(/* ルールの位置を見出しに示し、スキーマに従う編集欄と削除ボタンを描画する。 */ (rule, index) => {
    const card = el("div", { class: "field-card" });
    const head = el("div", { class: "section-head" });
    head.append(el("h3", {}, "異常ルール " + (index + 1)));
    const remove = el("button", { type: "button" }, "削除");
    remove.addEventListener("click", /* 選択した位置の異常ルールを削除し、見出しの番号を振り直す。 */ () => {
      state.spec.anomalies.splice(index, 1);
      invalidatePreview();
      renderAnomalies(parent);
    });
    head.append(remove);
    card.append(head);
    const grid = el("div", { class: "grid" });
    renderObject(grid, schema, rule, root);
    card.append(grid);
    parent.append(card);
  });
  const add = el(
    "button",
    { type: "button", id: "addAnomaly" },
    "＋ 異常ルールを追加",
  );
  add.addEventListener("click", /* 妥当な対象列を優先順で選び、範囲と値の例を持つ異常ルールを追加する。 */ () => {
    const value = defaultValue(schema, root);
    value.field =
      state.spec.fields.find(/* 簡単な例を作れるよう、valueという名前の既存項目を最優先する。 */ (f) => f.name === "value")?.name ||
      state.spec.fields.find(/* valueがなければ主キー以外の項目を探す。 */ (f) => !f.primary_key)?.name ||
      state.spec.fields[0].name;
    value.value = 999;
    value.from_row = 20;
    value.to_row = 39;
    state.spec.anomalies.push(value);
    invalidatePreview();
    renderAnomalies(parent);
  });
  parent.append(add);
}
// ブラウザーの入力制約を検査し、不正欄の折りたたみを開いて理由を表示し処理を中断する。
function validateForm(selector, showError = true) {
  const form = $(selector);
  for (const input of form.querySelectorAll("input,textarea,select")) {
    if (!input.checkValidity()) {
      if (showError) {
        for (let details = input.closest("details"); details;
          details = details.parentElement.closest("details")) {
          details.open = true;
        }
        input.reportValidity();
      }
      throw new Error("入力内容を確認してください。");
    }
  }
}
// フォームを検証した後に現在の実行設定を複製して返す。送信側の加工は編集中モデルから分離する。
function runSpec(showError = true) {
  validateForm("#runForm", showError);
  return clone(state.spec);
}
// 属性や異常ルールの配列順も含め、送るJSON全体を比較する。
function canonicalRunSpec(spec) {
  return JSON.stringify(spec, (_key, value) =>
    value && typeof value === "object" && !Array.isArray(value)
      ? Object.fromEntries(Object.keys(value).sort().map((key) => [key, value[key]]))
      : value,
  );
}

// ブラウザーが表示している配信先の版をリクエストに結び付ける。
function streamActionSnapshot() {
  const spec = runSpec();
  const profile = state.connections.find((item) => item.id === spec.connection_id);
  if (!profile || !Number.isSafeInteger(profile.revision) || profile.revision < 1)
    throw new Error("保存済みの配信先を選んでください。");
  spec.connection_revision = profile.revision;
  return {
    spec,
    version: state.specRevision,
    signature: canonicalRunSpec(spec),
    headers: { "X-Expected-Connection-Revision": String(profile.revision) },
  };
}

// 編集や接続の版変更があれば、古いプレビューを送信の承認として使わない。
function isPreviewCurrent(snapshot) {
  return sameStreamSnapshot(state.previewedDestination, snapshot);
}

// 両方の経路で同じ判定を使い、変更通知を取りこぼしても送信しない。
function sameStreamSnapshot(expected, current) {
  return expected?.version === current.version && expected.signature === current.signature;
}

// サーバー側で接続先が変わった場合は再取得するだけで、自動再送はしない。
async function guardedStreamAction(path, snapshot, send = api, refresh = refreshConnections) {
  try {
    return await send(path, snapshot.spec, snapshot.headers);
  } catch (error) {
    if (error.status !== 409) throw error;
    invalidatePreview();
    try {
      await refresh();
    } catch {
      throw new Error("配信先を再取得できません。接続先を確認し、プレビューし直してください。");
    }
    throw new Error("配信先が更新されました。表示された接続先を確認し、プレビューし直してください。");
  }
}

// 最新条件と一致するプレビュー応答だけを表示・保存する。
async function previewStream() {
  const snapshot = streamActionSnapshot();
  const data = await guardedStreamAction("/api/preview", snapshot);
  // 入力イベントを取りこぼした変更や編集中の無効な値でも旧結果を表示しない。
  if (snapshot.version !== state.specRevision ||
      data.connection_revision !== snapshot.spec.connection_revision) return;
  const latest = streamActionSnapshot();
  if (!sameStreamSnapshot(snapshot, latest)) return;
  previewResult(data);
  state.previewedDestination = snapshot;
}

// 明示的な押下でも、表示済みの本文と同じ条件でなければ送信しない。
async function startStream() {
  const snapshot = streamActionSnapshot();
  if (!isPreviewCurrent(snapshot))
    throw new Error("現在の配信先と条件でプレビューしてから送信してください。");
  return guardedStreamAction("/api/runs", snapshot);
}

const fieldsByKind = {
  sqlserver: ["host", "port", "database", "username", "password", "ssl_mode"],
  oracle: [
    "host",
    "port",
    "service_name",
    "sid",
    "username",
    "password",
    "ssl_mode",
  ],
  postgresql: ["host", "port", "database", "username", "password", "ssl_mode"],
  mysql: ["host", "port", "database", "username", "password", "ssl_mode"],
  mariadb: ["host", "port", "database", "username", "password", "ssl_mode"],
  sqlite: ["sqlite_path"],
  local: ["directory"],
  s3: [
    "endpoint_url",
    "bucket",
    "prefix",
    "region",
    "access_key",
    "secret_key",
    "session_token",
    "ssl_mode",
  ],
  mqtt: [
    "host",
    "port",
    "username",
    "password",
    "ssl_mode",
    "topic",
    "qos",
    "mqtt_version",
    "client_id",
    "keepalive",
    "retain",
    "delivery_attempts",
    "retry_backoff_ms",
  ],
  http: [
    "url",
    "http_method",
    "auth_mode",
    "username",
    "password",
    "bearer_token",
    "api_key",
    "api_key_header",
    "headers",
    "content_type",
    "ssl_mode",
    "delivery_attempts",
    "retry_backoff_ms",
  ],
  capture: [],
};
// 保存済みプロファイルと既定値から編集状態を作る。表示専用のリビジョンや設定済み情報は送信モデルに含めない。
function editConnection(profile) {
  const root = state.schemas.connection;
  state.profile = { ...defaultValue(root, root), ...clone(profile) };
  for (const key of ["revision", "configured_secrets", "configured_headers"])
    delete state.profile[key];
  $("#connectionTitle").textContent = profile.name || "新しい接続先";
  $("#secretState").textContent =
    "保存済み認証情報: " +
    ((profile.configured_secrets || []).join(", ") || "なし") +
    " / 保存済み追加ヘッダー: " +
    ((profile.configured_headers || []).join(", ") || "なし") +
    "。値は読み戻しません。";
  renderConnection();
  renderConnections();
}
const authByKind = {
  sqlserver: [
    "password",
    "windows_password",
    "kerberos",
    "entra_service_principal",
    "entra_managed_identity",
    "access_token",
  ],
  oracle: ["password", "external", "access_token"],
  postgresql: [
    "password",
    "kerberos",
    "client_certificate",
    "external",
    "access_token",
  ],
  mysql: ["password", "client_certificate", "external"],
  mariadb: ["password", "client_certificate", "external"],
};
const methodsByKind = {
  sqlserver: ["host", "dsn", "raw"],
  oracle: ["host", "dsn", "raw"],
  postgresql: ["host", "service", "unix_socket", "raw"],
  mysql: ["host", "unix_socket", "raw"],
  mariadb: ["host", "unix_socket", "raw"],
};
const driversByKind = {
  sqlserver: ["auto", "pymssql", "pyodbc"],
  oracle: ["auto", "oracledb_thin", "oracledb_thick"],
  postgresql: ["auto", "psycopg"],
  mysql: ["auto", "pymysql"],
  mariadb: ["auto", "pymysql"],
};
const authLabels = {
  password: "ユーザー / パスワード",
  windows_password: "Windows ドメイン資格情報",
  kerberos: "Kerberos 統合認証",
  client_certificate: "TLS クライアント証明書",
  external: "外部 / OS 認証",
  entra_service_principal: "Entra サービスプリンシパル",
  entra_managed_identity: "Entra Managed Identity",
  access_token: "取得済みアクセストークン",
  ssh_key: "SSH 秘密鍵",
  anonymous: "匿名FTP",
};
Object.assign(fieldsByKind, {
  sqlserver: [
    "driver",
    "database_auth",
    "connection_method",
    "host",
    "port",
    "database",
    "dsn",
    "connection_string",
    "odbc_driver",
    "domain",
    "username",
    "password",
    "db_access_token",
    "ssl_mode",
    "driver_options",
  ],
  oracle: [
    "driver",
    "database_auth",
    "connection_method",
    "host",
    "port",
    "service_name",
    "sid",
    "dsn",
    "connection_string",
    "username",
    "password",
    "db_access_token",
    "config_dir",
    "wallet_location",
    "wallet_password",
    "tls_ca_file",
    "ssl_mode",
    "driver_options",
  ],
  postgresql: [
    "driver",
    "database_auth",
    "connection_method",
    "host",
    "port",
    "database",
    "dsn",
    "connection_string",
    "unix_socket",
    "username",
    "password",
    "db_access_token",
    "tls_ca_file",
    "tls_cert_file",
    "tls_key_file",
    "tls_key_password",
    "ssl_mode",
    "driver_options",
  ],
  mysql: [
    "driver",
    "database_auth",
    "connection_method",
    "host",
    "port",
    "database",
    "connection_string",
    "unix_socket",
    "username",
    "password",
    "tls_ca_file",
    "tls_cert_file",
    "tls_key_file",
    "tls_key_password",
    "ssl_mode",
    "driver_options",
  ],
  mariadb: [
    "driver",
    "database_auth",
    "connection_method",
    "host",
    "port",
    "database",
    "connection_string",
    "unix_socket",
    "username",
    "password",
    "tls_ca_file",
    "tls_cert_file",
    "tls_key_file",
    "tls_key_password",
    "ssl_mode",
    "driver_options",
  ],
  nfs: ["directory", "nfs_expected_source"],
  smb: [
    "host",
    "port",
    "share",
    "directory",
    "file_auth",
    "domain",
    "username",
    "password",
    "smb_encrypt",
  ],
  ftp: [
    "host",
    "port",
    "directory",
    "file_auth",
    "username",
    "password",
    "ssl_mode",
    "ftp_tls_mode",
    "ftp_passive",
    "ftp_encoding",
    "tls_ca_file",
    "tls_cert_file",
    "tls_key_file",
    "tls_key_password",
  ],
  sftp: [
    "host",
    "port",
    "directory",
    "file_auth",
    "username",
    "password",
    "ssh_private_key",
    "ssh_key_password",
    "ssh_key_file",
    "ssh_host_key_policy",
    "ssh_host_key_sha256",
    "ssh_known_hosts",
  ],
  kafka: [
    "bootstrap_servers",
    "host",
    "port",
    "topic",
    "kafka_sasl_mechanism",
    "username",
    "password",
    "ssl_mode",
    "tls_ca_file",
    "tls_cert_file",
    "tls_key_file",
    "tls_key_password",
    "delivery_attempts",
    "retry_backoff_ms",
  ],
  amqp: [
    "host",
    "port",
    "topic",
    "amqp_virtual_host",
    "amqp_exchange",
    "amqp_declare_queue",
    "username",
    "password",
    "ssl_mode",
    "tls_ca_file",
    "tls_cert_file",
    "tls_key_file",
    "tls_key_password",
    "delivery_attempts",
    "retry_backoff_ms",
  ],
  nats: [
    "host",
    "port",
    "topic",
    "username",
    "password",
    "nats_token",
    "nats_credentials_file",
    "nats_jetstream",
    "ssl_mode",
    "tls_ca_file",
    "tls_cert_file",
    "tls_key_file",
    "tls_key_password",
    "delivery_attempts",
    "retry_backoff_ms",
  ],
  websocket: [
    "url",
    "auth_mode",
    "username",
    "password",
    "bearer_token",
    "api_key",
    "api_key_header",
    "headers",
    "websocket_ack",
    "websocket_subprotocols",
    "ssl_mode",
    "tls_ca_file",
    "tls_cert_file",
    "tls_key_file",
    "tls_key_password",
    "delivery_attempts",
    "retry_backoff_ms",
  ],
});
// 接続種別ごとに候補と項目を絞り込み、選べない認証・ドライバー候補は一覧の既定へ補正する。
function renderConnection() {
  const root = state.schemas.connection,
    form = $("#connectionForm");
  form.replaceChildren();
  form.className = "grid";
  const props = clone(root.properties);
  props.kind.enum = state.info.connection_kinds;
  props.kind.description =
    state.info.connection_help[state.profile.kind]?.description ||
    props.kind.description;
  for (const [key, choices] of Object.entries({
    database_auth: authByKind[state.profile.kind],
    connection_method: methodsByKind[state.profile.kind],
    driver: driversByKind[state.profile.kind],
  })) {
    if (choices) {
      props[key].enum = choices;
      if (!choices.includes(state.profile[key]))
        state.profile[key] = choices[0];
    }
  }
  const fileAuth = {
    smb: ["password", "kerberos"],
    ftp: ["password", "anonymous"],
    sftp: ["password", "ssh_key"],
  }[state.profile.kind];
  if (fileAuth) {
    props.file_auth.enum = fileAuth;
    if (!fileAuth.includes(state.profile.file_auth))
      state.profile.file_auth = fileAuth[0];
  }
  const explanation = el(
    "p",
    { class: "note connection-explanation" },
    state.info.connection_help[state.profile.kind]?.description || "",
  );
  explanation.style.gridColumn = "1 / -1";
  form.append(explanation);
  const keys = [
    "id",
    "name",
    "kind",
    ...(fieldsByKind[state.profile.kind] || []),
    "timeout_seconds",
    "clear_secrets",
  ];
  for (const key of keys) {
    const c = control(
      key,
      props[key],
      state.profile[key],
      /* プロファイルに入力値を反映する。種別変更時だけ関連する方式の値を再初期化し描画し直す。 */ (v) => {
        state.profile[key] = v;
        if (key === "kind") {
          for (const name of ["driver", "database_auth", "connection_method"])
            state.profile[name] = defaultValue(props[name], root);
          renderConnection();
        }
      },
      root,
    );
    form.append(c);
  }
}

// 接続一覧を現在の編集対象の強調とリビジョン表示付きで再構築する。
function renderConnections() {
  $("#connectionList").replaceChildren();
  for (const p of state.connections) {
    const b = el("button", {
      class: "profile" + (state.profile?.id === p.id ? " active" : ""),
    });
    b.append(
      el("b", {}, p.name),
      el(
        "span",
        { class: "muted" },
        p.kind + " · " + p.id + " · rev " + p.revision,
      ),
    );
    b.addEventListener("click", /* 押された一覧項目を編集対象とし、サーバー保存はまだ行わない。 */ () => editConnection(p));
    $("#connectionList").append(b);
  }
}
// APIから接続一覧を再取得し、接続カード、再送先、実行フォームの候補を更新する。
async function refreshConnections() {
  state.connections = (await api("/api/connections")).connections;
  renderConnections();
  for (const select of [$("#retryConnection")]) {
    select.replaceChildren();
    state.connections.forEach(/* 再送用セレクターへ、表示名と送信用IDを持つ選択肢を追加する。 */ (p) =>
      select.append(el("option", { value: p.id }, p.name)),
    );
  }
  if (state.spec) renderRun();
}
// 今選ばれたプリセットの説明を反映し、なければ編集方法の案内を表示する。
function updatePresetDetails() {
  const item = state.presets.find(/* 選択欄の値と一致するプリセットを、表示名ではなくIDで探す。 */ (p) => p.id === $("#presetSelect").value);
  const parts = (item?.spec.description || "").trim().split(/\r?\n\s*\r?\n/);
  const scenario = parts.shift()?.replace(/^【想定(?:する状況)?】\s*/, "").trim();
  $("#presetScenario").textContent = scenario || "このひな型には状況の説明がありません。";
  $("#presetDetails").textContent = parts.join("\n\n");
  $("#presetDetailsPanel").hidden = parts.length === 0;
}
// 最新のプリセット一覧を取得し、存在する限り以前の選択を保つ。
async function refreshPresets() {
  state.presets = (await api("/api/presets")).presets;
  const select = $("#presetSelect"),
    previous = select.value;
  select.replaceChildren();
  state.presets.forEach(/* プリセットを表示名とIDで識別できる選択肢として追加する。 */ (p) =>
    select.append(el("option", { value: p.id }, p.name + " · " + p.id)),
  );
  if (state.presets.some(/* 更新前のIDが新一覧に残っているか確認する。 */ (p) => p.id === previous)) select.value = previous;
  updatePresetDetails();
}
// 検証済みフォームをJSONへ変換する。履歴の接続リビジョンと再送指定はプリセットへ持ち込まない。
function showJson() {
  const v = runSpec();
  v.connection_revision = null;
  v.task = "generate";
  $("#presetJson").value = JSON.stringify(v, null, 2);
}
// 入力欄のJSONを解析し、プレビューAPIが検証した設定を返す。構文・検証失敗は呼出側へ伝える。
async function parsePreset(parsed = JSON.parse($("#presetJson").value)) {
  return (await api("/api/preview", parsed)).validated_spec;
}
// 値を整形JSONとしてブラウザーからダウンロードし、不要になったオブジェクトURLを解放する。
function download(value, name) {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(value, null, 2) + "\n"], {
      type: "application/json",
    }),
  );
  const a = el("a", { href: url, download: name });
  a.click();
  setTimeout(/* ダウンロード開始後、遅延して一時URLを解放する。 */ () => URL.revokeObjectURL(url), 1000);
}
// プレビュー応答をJSONと行表に表示し、欠落値と明示的な値を区別する。書込なしの表示は応答を基に決定する。
function previewResult(data) {
  $("#previewPanel").hidden = false;
  $("#previewPanel .badge").hidden = data.writes !== false;
  $("#previewNote").textContent = data.note || "接続先の処理結果";
  $("#previewJson").textContent = JSON.stringify(data, null, 2);
  const messages = $("#previewMessages");
  messages.replaceChildren();
  for (const message of data.stream_messages?.slice(0, 3) ?? []) {
    const sample = el("div", { class: "message-sample" });
    sample.append(
      el("h4", {}, "メッセージ " + message.sequence + " · " + message.bytes + " B"),
      el("p", {}, "トピック: " + (message.topic || "接続先の既定値（未確認）") +
        (message.duplicate ? " · 同じ本文を1回追加送信" : "")),
      el("pre", {}, JSON.stringify(JSON.parse(message.payload), null, 2)),
    );
    messages.append(sample);
  }
  const area = $("#previewTable");
  area.replaceChildren();
  if (data.records?.length) {
    const table = el("table"),
      tr = el("tr");
    const names = [...new Set(data.records.flatMap(/* 全サンプル行のキーを集計し、一部の行だけが持つ項目も列に含める。 */ (row) => Object.keys(row)))];
    tr.append(el("th", {}, "シーケンス"), el("th", {}, "適用した異常"));
    names.forEach(/* 各データ項目の名前をヘッダーセルとして追加する。 */ (k) => tr.append(el("th", {}, k)));
    table.append(tr);
    data.records.forEach(/* サンプル位置と異常名を値の行に対応付け、欠落を別表記で表示する。 */ (row, index) => {
      const r = el("tr");
      r.append(
        el("td", {}, String(data.sample_sequences?.[index] ?? index)),
        el("td", {}, (data.anomaly_hits?.[index] || []).join(" / ") || "正常"),
      );
      for (const name of names) {
        const v = row[name];
        r.append(
          el(
            "td",
            {},
            v === undefined
              ? "〈欠落〉"
              : typeof v === "object"
                ? JSON.stringify(v)
                : String(v),
          ),
        );
      }
      table.append(r);
    });
    area.append(table);
  }
  $("#previewPanel").scrollIntoView({ behavior: "smooth", block: "nearest" });
}
// 実行履歴から状態・進捗・出力を示すカードを作り、状態に合う操作だけを提示する。
function jobCard(run) {
  const c = el("div", { class: "card" });
  const h = el("div", { class: "section-head" });
  h.append(
    el("h3", {}, run.spec.name || run.id),
    el("span", { class: "badge" }, run.status),
  );
  c.append(h);
  c.append(
    el(
      "p",
      { class: "muted" },
      run.id + " · " + run.created_at + " · " + run.spec.connection_id,
    ),
  );
  const stats = el("div", { class: "stats" });
  for (const [key, label] of [
    ["processed", "処理済み"],
    ["events_per_second", "件 / 秒"],
    ["inserted", "追加"],
    ["updated", "更新"],
    ["files", "ファイル"],
    ["delivered", "配送済み"],
  ])
    if (run.stats[key] !== undefined) {
      const item = el("span", { class: "muted" }, label);
      item.append(el("b", {}, Number(run.stats[key]).toLocaleString()));
      stats.append(item);
    }
  c.append(stats);
  const progress = el("div", { class: "job-progress" });
  progress.append(
    el("div", {
      style:
        "width:" +
        Math.min(
          100,
          (100 * (run.stats.processed || 0)) /
            (run.spec.rows || run.spec.cycles || 1),
        ) +
        "%",
    }),
  );
  c.append(progress);
  if (run.error) c.append(el("p", { class: "danger" }, run.error));
  if (["running", "stopping"].includes(run.status)) {
    const b = el("button", { class: "danger" }, "停止");
    b.addEventListener("click", /* 停止APIを呼び出し、受理後に履歴を更新する。失敗しても画面操作を続けられるよう通知する。 */ async () => {
      try {
        await api("/api/runs/" + run.id + "/stop", {});
        await refreshHistory();
      } catch (e) {
        notify(e.message, true);
      }
    });
    c.append(b);
  }
  if (run.spec.version === 2) {
    const b = el("button", { class: "ghost" }, "この設定を編集");
    b.addEventListener("click", /* 保存済みv2設定を新しい生成編集の起点にする。旧リビジョンや再送指定のまま実行しない。 */ () => {
      state.spec = clone(run.spec);
      state.spec.connection_revision = null;
      state.spec.task = "generate";
      renderRun();
      tab("generate");
    });
    c.append(b);
  }
  if (
    state.info.kind === "files" &&
    run.outputs?.some(
      /* ファイル生成の出力に画像候補があるかを識別し、画像リンクの出し分けに使う。 */ (v) => typeof v === "object" && /\.(png|jpg)$/.test(v.path),
    )
  ) {
    const a = el(
      "a",
      {
        href: "/api/runs/" + run.id + "/image",
        target: "_blank",
        rel: "noopener",
      },
      "生成画像を表示",
    );
    c.append(a);
  }
  const detail = el("details", { "data-run-id": run.id });
  detail.append(el("summary", {}, "実行設定と詳細"));
  detail.append(el("pre", {}, JSON.stringify(run, null, 2)));
  c.append(detail);
  return c;
}
// 同じ領域・実行IDの開閉を引き継ぎ、別の実行や表示領域には波及させない。
function replaceJobCards(container, runs) {
  const openIds = new Set(
    Array.from(
      container.querySelectorAll("details[data-run-id][open]"),
      (detail) => detail.dataset.runId,
    ),
  );
  const focused = document.activeElement;
  const focusedId = focused?.tagName === "SUMMARY" && container.contains(focused)
    ? focused.parentElement.dataset.runId
    : undefined;
  let nextFocus;
  const cards = runs.map((run) => {
    const card = jobCard(run);
    const detail = card.querySelector("details");
    detail.open = openIds.has(run.id);
    if (focusedId === run.id) nextFocus = detail.querySelector("summary");
    return card;
  });
  container.replaceChildren(...cards);
  // キーボード操作中は、差し替え後の同じ実行の見出しへ戻す。
  nextFocus?.focus({ preventScroll: true });
}
let requestedHistory = 0;
let renderedHistory = 0;
// 実行一覧と現在の実行を取得し、終了遷移を通知する。ストリームでは再送待ち集計も更新する。
async function refreshHistory() {
  const request = ++requestedHistory;
  const runs = (await api("/api/runs")).runs;
  // 手動更新とポーリングの応答が逆転しても、表示済みの新しい状態を戻さない。
  if (request < renderedHistory) return;
  renderedHistory = request;
  // 応答を待っている間の操作も反映できるよう、開閉状態は描画直前に読む。
  replaceJobCards($("#historyList"), runs);
  const current = runs.find(/* 実行中または停止処理中の一覧項目を現在の実行として選ぶ。 */ (r) => ["running", "stopping"].includes(r.status));
  const currentJob = $("#currentJob");
  currentJob.hidden = !current;
  replaceJobCards(currentJob, current ? [current] : []);
  if (current) {
    state.current = current.id;
  } else if (state.current) {
    state.current = null;
    notify("実行が終了しました。結果は実行履歴で確認できます。");
  }
  if (state.info.kind === "stream") {
    const out = await api("/api/outbox");
    if (request < renderedHistory) return;
    $("#outboxSummary").textContent = JSON.stringify(
      { counts: out.counts, legacy_pending: out.legacy_pending },
      null,
      2,
    );
  }
}
const tooltip = $("#tooltip");
let tipTarget = null;
// 浮動ヘルプを非表示にし、表示対象を記憶する参照も消す。
function hideTip() {
  tooltip.hidden = true;
  tipTarget = null;
}
// 対象のヘルプ文を浮動表示と固定欄へ反映し、画面端に収まる座標を計算する。
function showTip(target) {
  if (!target || !target.dataset.help) return;
  tipTarget = target;
  tooltip.textContent = target.dataset.help;
  $("#contextHelp").textContent = target.dataset.help;
  tooltip.hidden = false;
  const r = target.getBoundingClientRect(),
    w = tooltip.offsetWidth,
    h = tooltip.offsetHeight;
  tooltip.style.left =
    Math.max(12, Math.min(innerWidth - w - 12, r.left)) + "px";
  tooltip.style.top =
    Math.max(
      12,
      r.bottom + h + 12 < innerHeight ? r.bottom + 8 : r.top - h - 8,
    ) + "px";
}
document.addEventListener("mouseover", /* マウス直下のヘルプ対象が変わったときに表示を切り替え、対象外では閉じる。 */ (e) => {
  const target = e.target.closest("[data-help]");
  if (target !== tipTarget) showTip(target);
  if (!target) hideTip();
});
document.addEventListener("focusin", /* キーボードで移動したフォーカスの最寄りのヘルプ対象を表示する。 */ (e) =>
  showTip(e.target.closest("[data-help]")),
);
document.addEventListener("focusout", hideTip);
document.addEventListener("keydown", /* Escape入力で開いているヘルプを閉じる。 */ (e) => {
  if (e.key === "Escape") hideTip();
});
window.addEventListener(
  "scroll",
  /* スクロール時にフォーカス中の対象が画面内ならヘルプ位置を更新し、外なら閉じる。 */ () => {
    const focused = document.activeElement?.closest("[data-help]");
    if (focused) {
      const bounds = focused.getBoundingClientRect();
      if (bounds.bottom > 0 && bounds.top < innerHeight) showTip(focused);
      else hideTip();
    } else hideTip();
  },
  true,
);
// API情報とスキーマを読み、初期画面・操作イベント・履歴ポーリングを順に組み立てる。
async function init() {
  [state.info, state.schemas] = await Promise.all([
    api("/api/info"),
    api("/api/schemas"),
  ]);
  state.spec = clone(state.info.defaults);
  $("#title").textContent = state.info.title;
  document.title = state.info.title + " · Factory Stream Simulator";
  $("#health").textContent = "ONLINE · " + state.info.kind.toUpperCase();
  await Promise.all([refreshConnections(), refreshPresets()]);
  editConnection(state.connections[0]);
  window.FactoryComparison.mount({
    app: "stream-simulator",
    listPresets: () => state.presets,
    currentSpec: () => runSpec(false),
    preview: (candidate) => api("/api/preview", candidate),
    metrics: (spec, data) => ({
      "元イベントの件数": spec.rows,
      "本文サイズの下限（B）": spec.stream.message_size_bytes ?? null,
      "見本の最大サイズ（B）": data.stream_messages?.length ? Math.max(...data.stream_messages.map((row) => row.bytes)) : null,
      "重複率": spec.stream.duplicate_rate ?? null,
      "重複する見本の数": data.stream_messages?.filter((row) => row.duplicate).length ?? null,
      "目標件数（件／秒）": spec.target_rate,
    }),
  });
  renderQuickstart();
  for (const event of ["input", "change"])
    $("#runForm").addEventListener(event, invalidatePreview);
  $("#sqlActions").hidden = state.info.kind !== "sql";
  $("#outboxPanel").hidden = state.info.kind !== "stream";
  $("#destinationAdvice").textContent =
    state.info.kind === "files"
      ? "構成例: ローカルの /landing に生成し、独立した取り込み処理でLakehouseへ転送します。クラウドへの直接投入を試す場合はS3互換プロファイルを追加します。ファイル名とSHA256を記録した完了マニフェストを取り込みの目印にできます。"
      : state.info.kind === "stream"
        ? "MQTTは設備通信、Kafkaはイベントログ、AMQPはキュー配送、NATSは軽量配信、WebSocketは常時接続、HTTPは受信API、キャプチャは外部送信なしの記録です。各方式の説明と配送確認の境界は選択欄のヘルプに表示します。"
        : "SQL Server以外にOracle / PostgreSQL / MySQL / MariaDB / SQLiteを選べます。既存テーブルへの書き込みには列名・型・主キーを一致させてください。";
  document.querySelectorAll(".nav").forEach(/* 全ナビ要素を、それぞれのタブ選択と履歴更新へ接続する。 */ (n) =>
    n.addEventListener("click", /* ナビで選んだタブを開く。履歴を開く場合だけ最新状態を非同期取得する。 */ () => {
      tab(n.dataset.tab);
      if (n.dataset.tab === "history")
        refreshHistory().catch(/* 履歴取得エラーを画面に通知し、未処理のPromise拒否にしない。 */ (e) => notify(e.message, true));
    }),
  );
  $("#presetSelect").addEventListener("change", updatePresetDetails);
  action("#loadPreset", /* 選択済みプリセットを複製して編集に読み込み、保存用IDを同期する。サーバーには保存しない。 */ async () => {
    const p = state.presets.find(/* 選択されたプリセットのIDを使ってインメモリー一覧から元データを探す。 */ (p) => p.id === $("#presetSelect").value);
    if (p) {
      state.spec = clone(p.spec);
      state.spec.connection_revision = null;
      renderRun();
      $("#presetId").value = p.id;
      notify("プリセットを読み込みました。");
    }
  });
  action("#resetRun", /* 編集中の生成設定をサービス既定値の複製へ戻して再描画する。 */ () => {
    state.spec = clone(state.info.defaults);
    renderRun();
    notify("実行設定を初期値に戻しました。");
  });
  action("#toPreset", /* 現在のフォームからプリセット用JSONを用意し、プリセット画面を開く。 */ () => {
    showJson();
    $("#presetId").value = "";
    $("#presetDisplayName").value = "";
    $("#presetPurpose").value = "";
    tab("presets");
    $("#presetId").focus();
  });
  action("#refreshJson", /* 表示中のJSONを現在のフォームの検証済み設定で更新する。 */ () => {
    showJson();
    notify("画面の設定をJSONに反映しました。");
  });
  action("#applyJson", /* 編集JSONをサーバーで検証した後にフォームへ反映し、生成画面へ戻す。 */ async () => {
    state.spec = await parsePreset();
    renderRun();
    notify("JSONを検証し、画面へ反映しました。");
    tab("generate");
  });
  action("#savePreset", /* IDを検査し、サーバー検証済みの設定を保存する。成功後にフォームと一覧を同期する。 */ async () => {
    const id = $("#presetId").value;
    if (!/^[A-Za-z0-9_-]{1,64}$/.test(id))
      throw new Error(
        "プリセットIDを英数字・下線・ハイフンで指定してください。",
      );
    const draft = JSON.parse($("#presetJson").value);
    const displayName = $("#presetDisplayName").value.trim();
    const purpose = $("#presetPurpose").value.trim();
    if (displayName) draft.name = displayName;
    if (purpose) draft.description = purpose;
    const spec = await parsePreset(draft);
    await api("/api/presets/" + id, spec);
    $("#presetJson").value = JSON.stringify(spec, null, 2);
    state.spec = spec;
    renderRun();
    await refreshPresets();
    $("#presetSelect").value = id;
    updatePresetDetails();
    notify("プリセット " + id + " を保存しました。");
  });
  action("#exportPreset", /* JSONを検証してからダウンロードし、空の名前には既定値を使う。 */ async () =>
    download(await parsePreset(), ($("#presetId").value || "preset") + ".json"),
  );
  $("#importPreset").addEventListener("change", /* 選択ファイルをサイズ制限内で読み、検証済み設定を表示する。ファイル名は保存候補IDへ変換し、自動保存はしない。 */ async (e) => {
    try {
      const file = e.target.files[0];
      if (!file) return;
      if (file.size > 2 * 1024 * 1024)
        throw new Error("JSONは2MiB以下にしてください。");
      $("#presetJson").value = await file.text();
      state.spec = await parsePreset();
      $("#presetId").value =
        file.name
          .replace(/\.json$/i, "")
          .replace(/[^A-Za-z0-9_-]/g, "-")
          .slice(0, 64) || "imported";
      renderRun();
      notify(
        "JSONを読み込み、画面へ反映しました。保存するとプリセットとして残せます。",
      );
    } catch (err) {
      notify(err.message, true);
    }
  });
  action("#preview", async () => {
    if (state.info.kind !== "stream") {
      previewResult(await api("/api/preview", runSpec()));
      return;
    }
    await previewStream();
  });
  action("#start", async () => {
    const run = state.info.kind === "stream"
      ? await startStream()
      : await api("/api/runs", runSpec());
    state.current = run.id;
    notify("送信を受け付けました。実行ID: " + run.id);
    await refreshHistory();
  });
  for (const [id, path] of [
    ["#inspectTable", "inspect"],
    ["#showDdl", "ddl"],
    ["#prepareTable", "prepare"],
  ])
    action(id, /* 各SQL操作に対応するAPIへ実行設定を渡す。検査・DDL表示・表準備は選ばれた操作に従う。 */ async () =>
      previewResult(await api("/api/table/" + path, runSpec())),
    );
  action("#newConnection", /* 現在時刻から仮IDを作り、許可種別の先頭で新規接続の編集画面を開く。保存前に通信はしない。 */ () =>
    editConnection({
      id: "connection-" + Date.now().toString(36),
      name: "新しい接続先",
      kind: state.info.connection_kinds[0],
    }),
  );
  action("#saveConnection", /* 接続フォームを検証して保存し、返されたリビジョンと接続一覧を表示に反映する。 */ async () => {
    validateForm("#connectionForm");
    const saved = await api("/api/connections", state.profile);
    await refreshConnections();
    editConnection(saved);
    notify("接続プロファイルを保存しました。rev " + saved.revision);
  });
  action("#testConnection", /* 現在の編集内容ではなく指定IDの保存済み設定で接続試験し、その結果を通知する。 */ async () => {
    const result = await api(
      "/api/connections/" + encodeURIComponent(state.profile.id) + "/test",
      {},
    );
    notify(
      "保存済みの接続設定でテストしました。\n" +
        JSON.stringify(result, null, 2),
    );
  });
  action("#exportConnection", /* サーバーのエクスポート応答を受け取り、指定接続IDのJSONファイルとしてダウンロードする。 */ async () =>
    download(
      await api(
        "/api/connections/" + encodeURIComponent(state.profile.id) + "/export",
      ),
      state.profile.id + "-connection.json",
    ),
  );
  action("#refreshHistory", refreshHistory);
  action("#retryOutbox", /* 件数範囲を検査し、選択した接続先の未配送分を再送する実行を開始して履歴を更新する。 */ async () => {
    const limit = Number($("#retryLimit").value);
    if (!Number.isInteger(limit) || limit < 1 || limit > 1000000)
      throw new Error("再送件数は1〜1000000にしてください。");
    const run = await api("/api/outbox/retry", {
      connection_id: $("#retryConnection").value,
      limit,
      batch_size: 100,
    });
    state.current = run.id;
    await refreshHistory();
    notify("未配送分の再送を開始しました。");
  });
  action("#uploadConnectionFile", /* 選んだ接続用ファイルをサイズ制限内でBase64化して送信し、保存された名前と権限を表示する。 */ async () => {
    const file = $("#connectionFile").files[0];
    if (!file) throw new Error("接続用ファイルを選んでください。");
    if (file.size > 1024 * 1024)
      throw new Error("1ファイル1MiB以下にしてください。");
    const bytes = new Uint8Array(await file.arrayBuffer());
    let text = "";
    for (const byte of bytes) text += String.fromCharCode(byte);
    const name = $("#connectionFileName").value || file.name;
    const result = await api("/api/connection-files", {
      name,
      content_base64: btoa(text),
    });
    $("#connectionFileResult").textContent =
      result.name +
      " (" +
      result.bytes +
      " bytes / mode " +
      result.permissions +
      ")";
    notify(
      "接続用ファイルを保存しました。プロファイルの対応する欄に " +
        name +
        " を指定してください。",
    );
  });
  await refreshHistory();
  showJson();
  setInterval(/* 実行中または履歴表示中だけ、定期的に最新の履歴を取得する。 */ () => {
    if (state.current || $("#history").classList.contains("active"))
      refreshHistory().catch(/* 定期更新の一時的な失敗を握りつぶし、次回のポーリングで回復できるようにする。 */ () => {});
  }, 2500);
}
init().catch(/* 初期化に失敗したときは詳細を通知し、稼働中の表示を読み込み失敗へ切り替える。 */ (err) => {
  notify(err.message, true);
  $("#health").textContent = "読み込み失敗";
});
