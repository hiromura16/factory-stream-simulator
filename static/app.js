"use strict";
const $ = (s) => document.querySelector(s),
  clone = (v) => structuredClone(v);
const state = {
  info: null,
  schemas: null,
  spec: null,
  connections: [],
  presets: [],
  profile: null,
  current: null,
};
let uid = 0;
const el = (tag, attrs = {}, text = "") => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") n.className = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v);
  }
  if (text) n.textContent = text;
  return n;
};
function notify(text, error = false) {
  $("#notice").textContent = text;
  $("#notice").className = error ? "error" : "";
}
async function api(path, body) {
  const r = await fetch(
    path,
    body === undefined
      ? {}
      : {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
  );
  const value = await r.json();
  if (!r.ok)
    throw new Error(
      typeof value.detail === "string"
        ? value.detail
        : JSON.stringify(value.detail || value),
    );
  return value;
}
const action = (id, fn) =>
  $(id).addEventListener("click", async (e) => {
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
function tab(id) {
  document
    .querySelectorAll(".tab")
    .forEach((n) => n.classList.toggle("active", n.id === id));
  document
    .querySelectorAll(".nav")
    .forEach((n) => n.classList.toggle("active", n.dataset.tab === id));
  hideTip();
}
function deref(schema, root) {
  return schema.$ref ? root.$defs[schema.$ref.split("/").pop()] : schema;
}
function defaultValue(schema, root) {
  schema = deref(schema, root);
  if ("default" in schema) return clone(schema.default);
  if (schema.const !== undefined) return schema.const;
  if (schema.anyOf) {
    const choice = schema.anyOf.find((v) => v.type === "null");
    return choice ? null : defaultValue(schema.anyOf[0], root);
  }
  if (schema.type === "object")
    return Object.fromEntries(
      Object.entries(schema.properties || {}).map(([k, v]) => [
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
function block(title, description, open = true) {
  const box = el("details", { class: "card" });
  box.open = open;
  box.append(el("summary", {}, title));
  if (description) box.append(el("p", { class: "muted" }, description));
  const body = el("div", { class: "grid" });
  box.append(body);
  return [box, body];
}
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
  const variants = schema.anyOf?.map((v) => deref(v, root));
  const obj = variants?.find((v) => v.type === "object" && v.properties);
  if (obj) {
    const check = el("input", { type: "checkbox", id });
    check.checked = value !== null && value !== undefined;
    const checklabel = el("label", { class: "checklabel" });
    checklabel.append(check, document.createTextNode("条件を有効にする"));
    outer.append(checklabel);
    const inner = el("div", { class: "grid" });
    outer.append(inner);
    function draw() {
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
    if (!state.connections.some((p) => p.id === value))
      input.append(el("option", { value }, value + " (未登録)"));
    input.value = value;
    input.addEventListener("change", () => set(input.value));
    outer.append(input);
    return outer;
  }
  let input;
  const isJson =
    shape.type === "array" ||
    shape.type === "object" ||
    (!shape.type && !shape.enum && !schema.anyOf) ||
    variants?.some((v) => v.type === "array");
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
    input.addEventListener("change", () => set(input.value));
  } else if (shape.type === "boolean") {
    input = el("input", { id, type: "checkbox" });
    input.checked = Boolean(value);
    input.addEventListener("change", () => set(input.checked));
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
    input.addEventListener("input", () => {
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
    input.addEventListener("input", () => set(input.value));
  } else if (["ssh_private_key", "connection_string"].includes(name)) {
    input = el("textarea", {
      id,
      rows: "4",
      spellcheck: "false",
      autocomplete: "off",
    });
    input.value = value ?? "";
    input.placeholder = "空欄は同じ接続先の保存済み値を維持";
    input.addEventListener("input", () => set(input.value || null));
  } else {
    const numeric = shape.type === "integer" || shape.type === "number";
    const secret =
      shape.format === "password" ||
      schema.format === "password" ||
      variants?.some((v) => v.format === "password");
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
    input.addEventListener("input", () => {
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
function renderObject(container, schema, model, root, exclude = []) {
  for (const [name, prop] of Object.entries(schema.properties || {})) {
    if (exclude.includes(name)) continue;
    if (!(name in model)) model[name] = defaultValue(prop, root);
    container.append(
      control(name, prop, model[name], (v) => (model[name] = v), root),
    );
  }
}
function renderRun() {
  const root = state.schemas.run,
    target = $("#runEditor");
  target.replaceChildren();
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
      (v) => (state.spec.parameters = v),
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
function renderFields(parent) {
  parent.replaceChildren();
  const root = state.schemas.run,
    schema = root.$defs.FieldRule;
  state.spec.fields.forEach((field, index) => {
    const card = el("div", { class: "field-card", "data-field-index": index }),
      head = el("div", { class: "field-head" });
    for (const key of ["name", "data_type", "generator"])
      head.append(
        control(
          key,
          schema.properties[key],
          field[key],
          (v) => {
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
        () => {
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
        () => {
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
        () => {
          const copy = clone(field);
          copy.name = field.name + "_copy";
          state.spec.fields.splice(index + 1, 0, copy);
        },
      ],
      [
        "削除",
        "このデータ項目を削除します",
        () => {
          if (state.spec.fields.length > 1) state.spec.fields.splice(index, 1);
        },
      ],
    ]) {
      const b = el("button", { type: "button", "data-help": help }, label);
      b.addEventListener("click", () => {
        fn();
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
    "＋ データ項目を追加",
  );
  add.addEventListener("click", () => {
    const value = defaultValue(schema, root);
    value.name = "custom_" + (state.spec.fields.length + 1);
    value.value = "sample";
    state.spec.fields.push(value);
    renderFields(parent);
  });
  parent.append(add);
}
function renderAnomalies(parent) {
  parent.replaceChildren();
  const root = state.schemas.run,
    schema = root.$defs.AnomalyRule;
  state.spec.anomalies.forEach((rule, index) => {
    const card = el("div", { class: "field-card" });
    const head = el("div", { class: "section-head" });
    head.append(el("h3", {}, "異常ルール " + (index + 1)));
    const remove = el("button", { type: "button" }, "削除");
    remove.addEventListener("click", () => {
      state.spec.anomalies.splice(index, 1);
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
  add.addEventListener("click", () => {
    const value = defaultValue(schema, root);
    value.field =
      state.spec.fields.find((f) => f.name === "value")?.name ||
      state.spec.fields.find((f) => !f.primary_key)?.name ||
      state.spec.fields[0].name;
    value.value = 999;
    value.from_row = 20;
    value.to_row = 39;
    state.spec.anomalies.push(value);
    renderAnomalies(parent);
  });
  parent.append(add);
}
function validateForm(selector) {
  const form = $(selector);
  for (const input of form.querySelectorAll("input,textarea,select")) {
    if (!input.checkValidity()) {
      input.closest("details")?.setAttribute("open", "");
      input.reportValidity();
      throw new Error("入力内容を確認してください。");
    }
  }
}
function runSpec() {
  validateForm("#runForm");
  return clone(state.spec);
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
      (v) => {
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
    b.addEventListener("click", () => editConnection(p));
    $("#connectionList").append(b);
  }
}
async function refreshConnections() {
  state.connections = (await api("/api/connections")).connections;
  renderConnections();
  for (const select of [$("#retryConnection")]) {
    select.replaceChildren();
    state.connections.forEach((p) =>
      select.append(el("option", { value: p.id }, p.name)),
    );
  }
  if (state.spec) renderRun();
}
function updatePresetDetails() {
  const item = state.presets.find((p) => p.id === $("#presetSelect").value);
  $("#presetDetails").textContent =
    item?.spec.description || "各設定は読み込み後に自由に変更できます。";
}
async function refreshPresets() {
  state.presets = (await api("/api/presets")).presets;
  const select = $("#presetSelect"),
    previous = select.value;
  select.replaceChildren();
  state.presets.forEach((p) =>
    select.append(el("option", { value: p.id }, p.name + " · " + p.id)),
  );
  if (state.presets.some((p) => p.id === previous)) select.value = previous;
  updatePresetDetails();
}
function showJson() {
  const v = runSpec();
  v.connection_revision = null;
  v.task = "generate";
  $("#presetJson").value = JSON.stringify(v, null, 2);
}
async function parsePreset() {
  const parsed = JSON.parse($("#presetJson").value);
  return (await api("/api/preview", parsed)).validated_spec;
}
function download(value, name) {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(value, null, 2) + "\n"], {
      type: "application/json",
    }),
  );
  const a = el("a", { href: url, download: name });
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function previewResult(data) {
  $("#previewPanel").hidden = false;
  $("#previewPanel .badge").hidden = data.writes !== false;
  $("#previewNote").textContent = data.note || "接続先の処理結果";
  $("#previewJson").textContent = JSON.stringify(data, null, 2);
  const area = $("#previewTable");
  area.replaceChildren();
  if (data.records?.length) {
    const table = el("table"),
      tr = el("tr");
    const names = [...new Set(data.records.flatMap((row) => Object.keys(row)))];
    tr.append(el("th", {}, "シーケンス"), el("th", {}, "適用した異常"));
    names.forEach((k) => tr.append(el("th", {}, k)));
    table.append(tr);
    data.records.forEach((row, index) => {
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
    b.addEventListener("click", async () => {
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
    b.addEventListener("click", () => {
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
      (v) => typeof v === "object" && /\.(png|jpg)$/.test(v.path),
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
  const detail = el("details");
  detail.append(el("summary", {}, "実行設定と詳細"));
  detail.append(el("pre", {}, JSON.stringify(run, null, 2)));
  c.append(detail);
  return c;
}
async function refreshHistory() {
  const runs = (await api("/api/runs")).runs;
  $("#historyList").replaceChildren(...runs.map(jobCard));
  const current = runs.find((r) => ["running", "stopping"].includes(r.status));
  $("#currentJob").hidden = !current;
  if (current) {
    state.current = current.id;
    $("#currentJob").replaceChildren(jobCard(current));
  } else if (state.current) {
    state.current = null;
    notify("実行が終了しました。結果は実行履歴で確認できます。");
  }
  if (state.info.kind === "stream") {
    const out = await api("/api/outbox");
    $("#outboxSummary").textContent = JSON.stringify(
      { counts: out.counts, legacy_pending: out.legacy_pending },
      null,
      2,
    );
  }
}
const tooltip = $("#tooltip");
let tipTarget = null;
function hideTip() {
  tooltip.hidden = true;
  tipTarget = null;
}
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
document.addEventListener("mouseover", (e) => {
  const target = e.target.closest("[data-help]");
  if (target !== tipTarget) showTip(target);
  if (!target) hideTip();
});
document.addEventListener("focusin", (e) =>
  showTip(e.target.closest("[data-help]")),
);
document.addEventListener("focusout", hideTip);
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") hideTip();
});
window.addEventListener(
  "scroll",
  () => {
    const focused = document.activeElement?.closest("[data-help]");
    if (focused) {
      const bounds = focused.getBoundingClientRect();
      if (bounds.bottom > 0 && bounds.top < innerHeight) showTip(focused);
      else hideTip();
    } else hideTip();
  },
  true,
);
async function init() {
  [state.info, state.schemas] = await Promise.all([
    api("/api/info"),
    api("/api/schemas"),
  ]);
  state.spec = clone(state.info.defaults);
  $("#title").textContent = state.info.title;
  document.title = state.info.title + " · Data Source Studio";
  $("#health").textContent = "ONLINE · " + state.info.kind.toUpperCase();
  await Promise.all([refreshConnections(), refreshPresets()]);
  editConnection(state.connections[0]);
  $("#sqlActions").hidden = state.info.kind !== "sql";
  $("#outboxPanel").hidden = state.info.kind !== "stream";
  $("#destinationAdvice").textContent =
    state.info.kind === "files"
      ? "構成例: ローカルの /landing に生成し、独立した取り込み処理でLakehouseへ転送します。クラウドへの直接投入を試す場合はS3互換プロファイルを追加します。ファイル名とSHA256を記録した完了マニフェストを取り込みの目印にできます。"
      : state.info.kind === "stream"
        ? "MQTTは設備通信、Kafkaはイベントログ、AMQPはキュー配送、NATSは軽量配信、WebSocketは常時接続、HTTPは受信API、キャプチャは外部送信なしの記録です。各方式の説明と配送確認の境界は選択欄のヘルプに表示します。"
        : "SQL Server以外にOracle / PostgreSQL / MySQL / MariaDB / SQLiteを選べます。既存テーブルへの書き込みには列名・型・主キーを一致させてください。";
  document.querySelectorAll(".nav").forEach((n) =>
    n.addEventListener("click", () => {
      tab(n.dataset.tab);
      if (n.dataset.tab === "history")
        refreshHistory().catch((e) => notify(e.message, true));
    }),
  );
  $("#presetSelect").addEventListener("change", updatePresetDetails);
  action("#loadPreset", async () => {
    const p = state.presets.find((p) => p.id === $("#presetSelect").value);
    if (p) {
      state.spec = clone(p.spec);
      state.spec.connection_revision = null;
      renderRun();
      $("#presetId").value = p.id;
      notify("プリセットを読み込みました。");
    }
  });
  action("#resetRun", () => {
    state.spec = clone(state.info.defaults);
    renderRun();
    notify("実行設定を初期値に戻しました。");
  });
  action("#toPreset", () => {
    showJson();
    tab("presets");
  });
  action("#refreshJson", () => {
    showJson();
    notify("画面の設定をJSONに反映しました。");
  });
  action("#applyJson", async () => {
    state.spec = await parsePreset();
    renderRun();
    notify("JSONを検証し、画面へ反映しました。");
    tab("generate");
  });
  action("#savePreset", async () => {
    const id = $("#presetId").value;
    if (!/^[A-Za-z0-9_-]{1,64}$/.test(id))
      throw new Error(
        "プリセットIDを英数字・下線・ハイフンで指定してください。",
      );
    const spec = await parsePreset();
    await api("/api/presets/" + id, spec);
    state.spec = spec;
    renderRun();
    await refreshPresets();
    $("#presetSelect").value = id;
    notify("プリセット " + id + " を保存しました。");
  });
  action("#exportPreset", async () =>
    download(await parsePreset(), ($("#presetId").value || "preset") + ".json"),
  );
  $("#importPreset").addEventListener("change", async (e) => {
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
  action("#preview", async () =>
    previewResult(await api("/api/preview", runSpec())),
  );
  action("#start", async () => {
    const run = await api("/api/runs", runSpec());
    state.current = run.id;
    notify("生成を開始しました。実行ID: " + run.id);
    await refreshHistory();
  });
  for (const [id, path] of [
    ["#inspectTable", "inspect"],
    ["#showDdl", "ddl"],
    ["#prepareTable", "prepare"],
  ])
    action(id, async () =>
      previewResult(await api("/api/table/" + path, runSpec())),
    );
  action("#newConnection", () =>
    editConnection({
      id: "connection-" + Date.now().toString(36),
      name: "新しい接続先",
      kind: state.info.connection_kinds[0],
    }),
  );
  action("#saveConnection", async () => {
    validateForm("#connectionForm");
    const saved = await api("/api/connections", state.profile);
    await refreshConnections();
    editConnection(saved);
    notify("接続プロファイルを保存しました。rev " + saved.revision);
  });
  action("#testConnection", async () => {
    const result = await api(
      "/api/connections/" + encodeURIComponent(state.profile.id) + "/test",
      {},
    );
    notify(
      "保存済みの接続設定でテストしました。\n" +
        JSON.stringify(result, null, 2),
    );
  });
  action("#exportConnection", async () =>
    download(
      await api(
        "/api/connections/" + encodeURIComponent(state.profile.id) + "/export",
      ),
      state.profile.id + "-connection.json",
    ),
  );
  action("#refreshHistory", refreshHistory);
  action("#retryOutbox", async () => {
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
  action("#uploadConnectionFile", async () => {
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
  setInterval(() => {
    if (state.current || $("#history").classList.contains("active"))
      refreshHistory().catch(() => {});
  }, 2500);
}
init().catch((err) => {
  notify(err.message, true);
  $("#health").textContent = "読み込み失敗";
});
