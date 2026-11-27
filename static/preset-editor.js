(() => {
  "use strict";

  const apiBase = "/api/preset-editor";
  const prefix = "factory-preset-editor-v1:" + location.pathname;
  const hasOwn = (object, key) => Object.hasOwn(object, key);
  const clone = (value) => value === undefined ? undefined : structuredClone(value);
  const format = (value) => JSON.stringify(value, null, 2);
  const object = (value) => value !== null && typeof value === "object" && !Array.isArray(value);
  const keys = (path) => Array.isArray(path) ? [...path] : path.split(".");
  const get = (value, path) => keys(path).reduce((parent, key) => parent?.[key], value);
  const forbidden = new Set(["__proto__", "prototype", "constructor"]);
  const secrets = new Set([
    "accesstoken", "apikey", "authorization", "bearertoken", "clientsecret", "connectionstring",
    "keytab", "passphrase", "password", "privatekey", "refreshtoken", "saslpassword",
    "secret", "secretaccesskey", "smbpassword", "sslkeypassword", "token", "webhooksecret",
    "awssecretaccesskey",
  ]);
  const editorKey = (key) => key.toLowerCase().replace(/[^a-z0-9]/g, "");
  const hasSecretKey = (value) => value !== null && typeof value === "object" &&
    Object.entries(value).some(([key, entry]) => secrets.has(editorKey(key)) || hasSecretKey(entry));

  function set(value, path, replacement) {
    const parts = keys(path);
    if (!parts.length || parts.some((key) => forbidden.has(key))) return;
    const last = parts.pop();
    let parent = value;
    for (const part of parts) {
      if (!object(parent[part]) && !Array.isArray(parent[part])) parent[part] = {};
      parent = parent[part];
    }
    if (replacement === undefined) {
      if (Array.isArray(parent)) parent.splice(Number(last), 1);
      else delete parent[last];
    } else {
      parent[last] = clone(replacement);
    }
  }

  function equal(a, b) {
    if (a === b) return true;
    if (Array.isArray(a) && Array.isArray(b))
      return a.length === b.length && a.every((value, index) => equal(value, b[index]));
    if (!object(a) || !object(b)) return false;
    return Object.keys(a).length === Object.keys(b).length &&
      Object.keys(a).every((key) => hasOwn(b, key) && equal(a[key], b[key]));
  }

  function differences(a, b, path = [], result = []) {
    if (equal(a, b) || result.length >= 150) return result;
    if (object(a) && object(b)) {
      for (const key of new Set([...Object.keys(a), ...Object.keys(b)])) {
        differences(a[key], b[key], [...path, key], result);
        if (result.length >= 150) break;
      }
    } else {
      result.push({ path, before: a, after: b });
    }
    return result;
  }

  function visible(field, context, defaults) {
    if (!field.when) return true;
    const actual = get(context, field.when.path) ?? defaults.get(field.when.path);
    const expected = field.when.includes ?? field.when.equals;
    const a = Array.isArray(actual) ? actual : [actual];
    const b = Array.isArray(expected) ? expected : [expected];
    return a.some((value) => b.includes(value));
  }

  function element(tag, className, content) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (content !== undefined) node.textContent = content;
    return node;
  }

  function button(label, callback, className = "") {
    const node = element("button", className, label);
    node.type = "button";
    if (callback) node.addEventListener("click", callback);
    return node;
  }

  async function request(path = "", method = "GET", payload, revision) {
    const headers = { Accept: "application/json" };
    if (payload !== undefined || method === "DELETE") headers["Content-Type"] = "application/json";
    if (revision) headers["If-Match"] = '"' + revision + '"';
    const response = await fetch(path.startsWith("/api/") ? path : apiBase + path, {
      method, headers, cache: "no-store",
      body: payload === undefined ? undefined : JSON.stringify(payload),
    });
    const data = await response.json().catch(() => null);
    if (response.ok && data !== null) return data;
    const detail = data?.detail;
    throw Object.assign(
      new Error(typeof detail === "string" ? detail : "要求に失敗しました（HTTP " + response.status + "）。"),
      { status: response.status, issues: Array.isArray(detail) ? detail : [] },
    );
  }

  function storage(area, key, value) {
    try {
      const store = window[area];
      if (value === undefined) return JSON.parse(store.getItem(prefix + ":" + key) || "null");
      if (value === null) store.removeItem(prefix + ":" + key);
      else store.setItem(prefix + ":" + key, JSON.stringify(value));
      return true;
    } catch {
      return false;
    }
  }

  let mounted;
  window.FactoryPresetEditor = {
    configure(hooks) {
      if (mounted) return mounted;
      const root = document.getElementById("presetEditor");
      const config = window.FactoryPresetConfig;
      if (!root || !config) throw new Error("プリセット編集画面の設定を読み込めませんでした。");
      mounted = mount(root, config, hooks);
      return mounted;
    },
    open(spec, item) {
      return mounted?.open(spec, item);
    },
    activate() {
      mounted?.activate();
    },
  };

  function mount(root, config, hooks) {
    root.innerHTML =
      '<div class="pe-heading"><div><h3 id="pe-title"></h3><p id="pe-description"></p></div>' +
      '<div class="pe-actions"><button type="button" id="pe-capture">実行画面の設定を読み込む</button>' +
      '<button type="button" id="pe-import-open">JSONを読み込む</button>' +
      '<input type="file" id="pe-import" accept="application/json,.json" hidden></div></div>' +
      '<p id="pe-message" class="pe-message" aria-live="polite" role="status" hidden></p>' +
      '<ol id="pe-issues" class="pe-issues" hidden></ol>' +
      '<fieldset id="pe-lock" class="pe-layout"><legend class="pe-visually-hidden">プリセット編集</legend>' +
      '<div class="pe-library" aria-label="プリセット一覧"><div class="pe-library-header"><h4>プリセット</h4>' +
      '<button type="button" id="pe-refresh">再読み込み</button></div>' +
      '<label>検索<input id="pe-search" type="search" placeholder="名前・ID・タグ"></label>' +
      '<div class="pe-filters"><label>種類<select id="pe-source"><option value="">すべて</option>' +
      '<option value="user">保存済み</option><option value="bundled">同梱</option><option value="favorite">お気に入り</option>' +
      '</select></label><label>並べ替え<select id="pe-sort"><option value="name">名前</option>' +
      '<option value="updated">更新日時</option><option value="recent">最近開いた順</option></select></label></div>' +
      '<ul id="pe-list" class="pe-list" aria-label="検索結果"></ul></div>' +
      '<div class="pe-workspace"><header class="pe-workspace-top">' +
      '<div><strong id="pe-origin"></strong><span id="pe-state" aria-live="polite"></span></div>' +
      '<div class="pe-actions"><button type="button" id="pe-undo">元に戻す</button>' +
      '<button type="button" id="pe-redo">やり直す</button>' +
      '<button type="button" id="pe-revert-fields" hidden>無効な入力を戻す</button></div></header>' +
      '<nav class="pe-modes" aria-label="表示切替"><button type="button" data-pe-mode="gui">GUI編集</button>' +
      '<button type="button" data-pe-mode="json">JSON</button><button type="button" data-pe-mode="diff">差分・比較</button></nav>' +
      '<div id="pe-gui"><div id="pe-details" class="pe-section pe-fields"></div>' +
      '<form id="pe-form" novalidate></form></div>' +
      '<div id="pe-json-mode" hidden><label for="pe-json">プリセットJSON</label>' +
      '<textarea id="pe-json" rows="22" class="pe-code" spellcheck="false"></textarea>' +
      '<div class="pe-actions"><button type="button" id="pe-apply-json">GUIに反映</button>' +
      '<button type="button" id="pe-format-json">整形</button><button type="button" id="pe-revert-json" hidden>最後に有効だったJSONに戻す</button></div></div>' +
      '<div id="pe-diff-mode" hidden><div class="pe-actions">' +
      '<label>比較するプリセット<select id="pe-compare"></select></label>' +
      '<button type="button" id="pe-compare-open">比較</button>' +
      '<button type="button" id="pe-compare-reset">編集中の元と比較</button>' +
      '<button type="button" id="pe-rebase-draft" hidden>最新の保存版を基準にする</button></div><div id="pe-diff"></div></div>' +
      '<section id="pe-summary" class="pe-section" aria-label="設定の要約" hidden></section>' +
      '<section id="pe-preview-result" class="pe-section" tabindex="-1" aria-label="プレビュー結果" hidden></section>' +
      '<div class="pe-footer"><div class="pe-actions">' +
      '<button type="button" id="pe-validate">検証</button><button type="button" id="pe-preview">プレビュー</button>' +
      '<button type="button" id="pe-use">実行画面へ反映</button><button type="button" id="pe-export">JSONを書き出す</button></div>' +
      '<label class="pe-checklabel"><input id="pe-compact" type="checkbox" checked>JSON書き出しで既定値を省略</label>' +
      '<div class="pe-actions"><button type="button" id="pe-save" class="primary">上書き保存</button>' +
      '<button type="button" id="pe-save-copy">別名で保存</button><button type="button" id="pe-clone">複製して編集</button>' +
      '<button type="button" id="pe-snapshot">元の版を別名で保存</button><button type="button" id="pe-delete" class="pe-danger">削除</button></div>' +
      '<p>保存・検証・プレビューで処理は開始しません。</p></div>' +
      '<details class="pe-section"><summary>AIや他のツールで使う</summary>' +
      '<p>連携用JSONに含まれるものは現在の設定、対応するOpenAPIのURL、保存なしで使える検証・プレビュー手順です。</p>' +
      '<div class="pe-actions"><button type="button" id="pe-ai">AI連携用JSONを書き出す</button>' +
      '<a href="/docs">Swagger UI</a><a href="/help/templates.html">テンプレートの書き方</a></div></details></div></fieldset>' +
      '<dialog id="pe-save-dialog" aria-labelledby="pe-save-title"><form method="dialog">' +
      '<h4 id="pe-save-title">別名で保存</h4><label>ID<input name="id" required maxlength="64" pattern="[A-Za-z0-9_\\-]+"></label>' +
      '<label>表示名<input name="name" required maxlength="120"></label>' +
      '<p>すでに使われているIDは変更してください。既存のプリセットは上書きされません。</p>' +
      '<div class="pe-actions"><button value="cancel" formnovalidate>キャンセル</button>' +
      '<button value="save" class="primary">保存する</button></div></form></dialog>';

    const id = (name) => document.getElementById("pe-" + name);
    const state = {
      list: [], connections: [], draft: null, original: null, tags: [], originalTags: [],
      origin: null, candidate: "", older: [], newer: [], preview: null, comparison: null,
      conflict: null, rawDirty: false, invalidFields: new Map(), mode: "gui", busy: false, active: false,
      favorites: new Set(storage("localStorage", "favorite") || []),
      recent: storage("localStorage", "recent") || [],
    };
    let sequence = 0;
    const defaultsFor = (fields) => new Map(fields.map((field) => [field.path, field.default]));
    const defaults = defaultsFor(config.sections.flatMap((section) => section.fields));
    id("title").textContent = config.title;
    id("description").textContent = config.description || "";

    function announce(message, kind = "") {
      id("message").textContent = message;
      id("message").hidden = !message;
      id("message").dataset.kind = kind;
    }

    function showIssues(issues = []) {
      const list = id("issues");
      list.replaceChildren();
      for (const issue of issues.slice(0, 25)) {
        const raw = Array.isArray(issue.loc) ? issue.loc.filter((key) => key !== "body" && key !== "spec") : [];
        const path = raw.map(String).join(".");
        const title = issue.location || raw.join(" → ") || "設定";
        const row = element("li");
        const label = button(title, () => {
          setMode("gui");
          const control = [...root.querySelectorAll("[data-pe-path]")]
            .find((node) => node.dataset.pePath === path);
          if (control) {
            const detail = control.closest("details");
            if (detail) detail.open = true;
            control.scrollIntoView({ block: "center" });
            control.focus();
          } else {
            setMode("json");
            id("json").focus();
          }
        });
        row.append(label, document.createTextNode(" " + (issue.msg || "入力を確認してください。")));
        list.append(row);
      }
      list.hidden = !list.childElementCount;
    }

    function dirty() {
      return state.rawDirty || state.invalidFields.size > 0 || !equal(state.draft, state.original) || !equal(state.tags, state.originalTags);
    }

    function remember() {
      if (!state.draft || !dirty() || hasSecretKey(state.draft)) {
        storage("sessionStorage", "draft", null);
        return;
      }
      storage("sessionStorage", "draft", {
        draft: state.draft, original: state.original, tags: state.tags, originalTags: state.originalTags,
        origin: state.origin, candidate: state.candidate, mode: state.mode,
        search: id("search").value, source: id("source").value, sort: id("sort").value,
      });
    }

    function update() {
      const hasDraft = !!state.draft;
      const user = state.origin?.source === "user";
      id("origin").textContent = state.origin
        ? (user ? "保存済み · " : "同梱 · ") + state.origin.id
        : "新規プリセット";
      id("state").textContent = hasDraft ? (dirty() ? "未保存の変更あり" : "変更なし") : "プリセットを選択してください";
      id("state").dataset.dirty = String(dirty());
      id("revert-json").hidden = !state.rawDirty;
      id("rebase-draft").hidden = !state.conflict;
      id("revert-fields").hidden = !state.invalidFields.size;
      for (const name of ["validate", "preview", "use", "export", "ai", "save-copy", "clone"]) id(name).disabled = !hasDraft;
      id("save").disabled = !user || !dirty();
      id("save-copy").classList.toggle("primary", !user);
      id("delete").disabled = !user;
      id("snapshot").disabled = !state.origin;
      id("undo").disabled = !state.older.length;
      id("redo").disabled = !state.newer.length;
      updateSummary();
    }

    function invalidatePreview() {
      state.preview = null;
      id("preview-result").hidden = true;
    }

    function snapshot() {
      return { draft: clone(state.draft), tags: [...state.tags] };
    }

    function commit(next, tags = state.tags, redraw = true, resetRaw = true) {
      if (equal(next, state.draft) && equal(tags, state.tags)) return;
      if (hasSecretKey(next)) throw new Error("認証情報は接続プロファイルに設定してください。");
      state.older.push(snapshot());
      state.older = state.older.slice(-40);
      state.newer = [];
      state.draft = next;
      state.tags = [...tags];
      invalidatePreview();
      if (resetRaw) refreshJson();
      if (redraw) renderForm();
      showIssues();
      update();
      remember();
    }

    function change(path, value, redraw) {
      const next = clone(state.draft);
      set(next, path, value);
      commit(next, state.tags, redraw);
    }

    function refreshJson() {
      id("json").value = state.draft ? format(state.draft) : "";
      state.rawDirty = false;
    }

    function fromJson(text) {
      const value = typeof readPresetJson === "function" ? readPresetJson(text) : JSON.parse(text);
      if (!object(value)) throw new Error("プリセットのJSONは { } で囲まれたオブジェクトです。");
      if (hasSecretKey(value)) throw new Error("認証情報は接続プロファイルに設定してください。");
      return value;
    }

    function acceptJson() {
      if (!state.rawDirty) return;
      state.invalidFields.clear();
      commit(fromJson(id("json").value), state.tags, false, false);
      state.rawDirty = false;
      update();
      remember();
    }

    function setMode(mode, fromSource = false) {
      if (!fromSource && state.mode === "json" && mode !== "json") {
        try {
          acceptJson();
        } catch (error) {
          announce(error.message, "error");
          return;
        }
      }
      state.mode = mode;
      id("gui").hidden = mode !== "gui";
      id("json-mode").hidden = mode !== "json";
      id("diff-mode").hidden = mode !== "diff";
      for (const control of root.querySelectorAll("[data-pe-mode]"))
        control.setAttribute("aria-pressed", String(control.dataset.peMode === mode));
      if (mode === "diff") renderDiff();
      if (mode === "gui") renderForm();
      remember();
    }

    function profileOptions() {
      return state.connections.map(({ id, name }) => ({ value: id, label: name ? name + " · " + id : id }));
    }

    function options(field, value) {
      return (field.type === "connection" ? profileOptions() : field.options || []).map((option) =>
        object(option) ? option : { value: option, label: String(option) },
      ).concat(value !== undefined && value !== null &&
        !(field.type === "connection" ? profileOptions() : field.options || []).some((option) =>
          equal(object(option) ? option.value : option, value),
        ) && field.type !== "multiselect" ? [{ value, label: String(value) }] : []);
    }

    function tagValues(value) {
      return [...new Set(value.split(/[,、\n]/).map((entry) => entry.trim()).filter(Boolean))];
    }

    function control(field, path, actual, onChange) {
      if (field.type === "table") return renderRows(field, path, Array.isArray(actual) ? actual : []);
      const slot = element("div", "pe-field" + (field.type === "json" || field.type === "textarea" ? " pe-wide" : ""));
      const label = element("label", "", field.label);
      const fieldPath = path.join(".");
      const value = actual === undefined && typeof field.default !== "function" ? field.default : actual;
      let input;
      let readValue;
      let redraw = false;
      const type = field.type;
      if (type === "multiselect") {
        slot.append(element("span", "pe-field-label", field.label));
        const values = Array.isArray(value) ? value : [];
        const choices = options(field);
        const group = element("div", "pe-multiselect");
        group.setAttribute("role", "group");
        group.setAttribute("aria-label", field.label);
        for (const option of choices) {
          const row = element("label", "pe-checklabel");
          const box = element("input");
          box.type = "checkbox";
          box.checked = values.some((entry) => equal(entry, option.value));
          box.addEventListener("change", () => onChange(box.checked
            ? [...values, option.value]
            : values.filter((entry) => !equal(entry, option.value)), true));
          row.append(box, document.createTextNode(option.label));
          group.append(row);
        }
        slot.append(group);
      } else {
        if (type === "select" || type === "connection") {
          const choices = options(field, value);
          input = element("select");
          const empty = element("option", "", "未指定");
          empty.value = "";
          input.append(empty);
          choices.forEach((choice, index) => {
            const node = element("option", "", choice.label);
            node.value = String(index);
            input.append(node);
          });
          const index = choices.findIndex((choice) => equal(choice.value, value));
          input.value = index >= 0 ? String(index) : "";
          readValue = () => input.value === "" ? undefined : choices[Number(input.value)].value;
          redraw = true;
        } else if (type === "boolean") {
          input = element("input");
          input.type = "checkbox";
          input.checked = Boolean(value ?? field.default);
          readValue = () => input.checked;
          redraw = true;
          slot.classList.add("pe-boolean");
        } else if (type === "json" || type === "textarea") {
          input = element("textarea", type === "json" ? "pe-code" : "");
          input.rows = type === "json" ? 3 : 4;
          input.value = type === "json" ? (value === undefined ? "" : format(value)) : (value ?? "");
          readValue = () => type === "json" ? (input.value.trim() ? JSON.parse(input.value) : undefined) : input.value;
        } else {
          input = element("input");
          input.type = type === "number" || type === "integer" ? "number" : "text";
          input.value = Array.isArray(value) ? value.join(", ") : (value ?? "");
          if (field.placeholder) input.placeholder = field.placeholder;
          if (field.min !== undefined) input.min = field.min;
          if (field.max !== undefined) input.max = field.max;
          if (field.maxLength !== undefined) input.maxLength = field.maxLength;
          if (input.type === "number") input.step = field.step ?? (type === "integer" ? 1 : "any");
          readValue = () => input.type === "number"
            ? (input.value === "" ? undefined : input.valueAsNumber)
            : (type === "string-list" ? tagValues(input.value) : input.value);
          if (typeof field.suggestions === "function" && input.type === "text") {
            const data = element("datalist");
            data.id = "pe-suggestions-" + ++sequence;
            for (const value of field.suggestions(state.draft) || []) {
              const option = element("option");
              option.value = value;
              data.append(option);
            }
            input.setAttribute("list", data.id);
            slot.append(data);
          }
        }
        input.id = "pe-control-" + ++sequence;
        if (path.length) input.dataset.pePath = path.join(".");
        label.htmlFor = input.id;
        slot.append(label, input);
        if (state.invalidFields.has(fieldPath)) {
          const invalid = state.invalidFields.get(fieldPath);
          input.value = invalid.value;
          input.setCustomValidity(invalid.message);
        }
        const syncInput = (report) => {
          input.setCustomValidity("");
          try {
            if (!input.checkValidity()) throw new Error(input.validationMessage);
            const next = readValue();
            if (typeof next === "number" && !Number.isFinite(next)) throw new Error("数値を入力してください。");
            if (hasSecretKey(next)) throw new Error("認証情報は接続プロファイルに設定してください。");
            state.invalidFields.delete(fieldPath);
            onChange(next, redraw);
          } catch (error) {
            const message = error instanceof SyntaxError ? "JSONの構文を確認してください。" : error.message;
            state.invalidFields.set(fieldPath, { value: input.value, message });
            input.setCustomValidity(message);
            if (report) input.reportValidity();
          }
          update();
          remember();
        };
        if (!redraw) input.addEventListener("input", () => syncInput(false));
        input.addEventListener("change", () => syncInput(true));
      }
      if (field.help) {
        const help = element("small", "pe-field-help", field.help);
        help.id = "pe-help-" + sequence;
        if (input) input.setAttribute("aria-describedby", help.id);
        slot.append(help);
      }
      return slot;
    }

    function renderRows(field, path, rows) {
      const section = element("section", "pe-row-editor pe-wide");
      const editRows = (next) => {
        if ([...state.invalidFields.keys()].some((key) => key.startsWith(path.join(".") + "."))) {
          announce("行を変更する前に、無効な入力を修正するか「無効な入力を戻す」を選んでください。", "error");
          return;
        }
        change(path, next, true);
      };
      const header = element("div", "pe-library-header");
      header.append(element("h5", "", field.label), button("追加", () => {
        const value = typeof field.default === "function" ? field.default(rows, state.draft) : field.default || {};
        editRows([...rows, clone(value)]);
      }));
      section.append(header);
      if (field.help) section.append(element("p", "pe-field-help", field.help));
      if (!rows.length) section.append(element("p", "pe-muted", "まだ項目がありません。"));
      const columnDefaults = defaultsFor(field.columns || []);
      rows.forEach((row, index) => {
        const card = element("div", "pe-row");
        const rowHead = element("div", "pe-library-header");
        const controls = element("div", "pe-actions");
        const move = (direction) => {
          const next = [...rows];
          [next[index], next[index + direction]] = [next[index + direction], next[index]];
          editRows(next);
        };
        const up = button("上へ", () => move(-1));
        up.disabled = index === 0;
        const down = button("下へ", () => move(1));
        down.disabled = index === rows.length - 1;
        controls.append(up, down, button("複製", () => {
          const copy = clone(row);
          if (typeof copy?.name === "string") {
            const names = new Set(rows.map((item) => item?.name));
            let version = copy.name + "_copy";
            for (let i = 2; names.has(version); i++) version = copy.name + "_copy_" + i;
            copy.name = version;
          }
          editRows([...rows.slice(0, index + 1), copy, ...rows.slice(index + 1)]);
        }), button("削除", () => editRows(rows.filter((_, at) => at !== index))));
        rowHead.append(element("strong", "", String(index + 1) + " · " + (row?.name || row?.field || row?.address || field.label)), controls);
        const fields = element("div", "pe-fields");
        for (const column of field.columns || []) {
          if (!visible(column, row, columnDefaults)) continue;
          const cell = [...path, String(index), ...keys(column.path)];
          fields.append(control(column, cell, get(row, column.path), (next, redraw) => change(cell, next, redraw)));
        }
        card.append(rowHead, fields);
        section.append(card);
      });
      return section;
    }

    function renderForm() {
      const form = id("form");
      const focusedPath = document.activeElement?.dataset?.pePath;
      const opened = new Set([...form.querySelectorAll("details[open]")].map((node) => node.dataset.section));
      form.replaceChildren();
      const details = id("details");
      details.replaceChildren();
      if (!state.draft) return;
      const common = [
        { path: "name", type: "text", label: "表示名", maxLength: 120 },
        { path: "description", type: "textarea", label: "想定する状況と確認点" },
      ];
      for (const field of common)
        details.append(control(field, [field.path], state.draft[field.path], (next) => change([field.path], next, false)));
      details.append(control({ type: "string-list", label: "タグ", help: "検索に使うタグをカンマで区切ります。" },
        [], state.tags, (next) => commit(clone(state.draft), next, false)));
      config.sections.forEach((section, index) => {
        const fields = section.fields.filter((field) => visible(field, state.draft, defaults));
        if (!fields.length) return;
        const panel = element("details", "pe-section");
        panel.dataset.section = String(index);
        panel.open = opened.size ? opened.has(String(index)) : index === 0;
        panel.append(element("summary", "", section.title));
        if (section.description) panel.append(element("p", "pe-muted", section.description));
        const inputs = element("div", "pe-fields");
        for (const field of fields)
          inputs.append(control(field, keys(field.path), get(state.draft, field.path),
            (next, redraw) => change(keys(field.path), next, redraw)));
        panel.append(inputs);
        form.append(panel);
      });
      if (focusedPath) root.querySelectorAll("[data-pe-path]").forEach((input) => {
        if (input.dataset.pePath === focusedPath) input.focus({ preventScroll: true });
      });
    }

    function updateSummary() {
      const panel = id("summary");
      panel.replaceChildren();
      let rows = [];
      if (state.draft && config.summarize) {
        try {
          rows = config.summarize(state.draft, state.preview);
        } catch {
          rows = [];
        }
      }
      panel.hidden = !Array.isArray(rows) || !rows.length;
      if (panel.hidden) return;
      const list = element("dl", "pe-summary");
      for (const row of rows) {
        if (row?.value === undefined || row.value === null || row.value === "") continue;
        list.append(element("dt", "", row.label), element("dd", "", typeof row.value === "object" ? format(row.value) : row.value));
      }
      panel.append(element("h4", "", "設定の要約・見積り"), list);
    }

    function renderLibrary() {
      const query = id("search").value.trim().toLowerCase().split(/\s+/).filter(Boolean);
      const source = id("source").value;
      const list = id("list");
      const compare = id("compare");
      const previous = compare.value;
      const items = state.list.filter((item) =>
        (source === "favorite" ? state.favorites.has(item.id) : (!source || source === item.source)) &&
        query.every((token) => [item.name, item.id, item.description, ...item.tags].join(" ").toLowerCase().includes(token)),
      );
      const sort = id("sort").value;
      const recent = (key) => {
        const at = state.recent.indexOf(key);
        return at < 0 ? Infinity : at;
      };
      items.sort((a, b) => {
        const primary = sort === "recent" ? recent(a.id) - recent(b.id) :
          sort === "updated" ? String(b.updated_at || "").localeCompare(String(a.updated_at || "")) : 0;
        return primary || a.name.localeCompare(b.name, "ja");
      });
      list.replaceChildren();
      compare.replaceChildren(element("option", "", "比較先を選択"));
      compare.firstElementChild.value = "";
      for (const item of state.list) {
        const option = element("option", "", item.name + " · " + item.id);
        option.value = item.id;
        compare.append(option);
      }
      if (state.list.some((item) => item.id === previous)) compare.value = previous;
      for (const item of items) {
        const row = element("li", state.origin?.id === item.id ? "pe-selected" : "");
        const open = button(item.name, () => run(async () => {
          if (!confirmDiscard()) return;
          await loadItem(item.id);
        }), "pe-open");
        if (state.origin?.id === item.id) open.setAttribute("aria-current", "true");
        const qualifier = (item.source === "user" ? "保存済み" : "同梱") + " · " + item.id;
        open.append(element("small", "", qualifier));
        if (item.tags.length) open.append(element("small", "pe-item-tags", item.tags.join(" / ")));
        const starred = state.favorites.has(item.id);
        const favorite = button(starred ? "★" : "☆", () => {
          if (starred) state.favorites.delete(item.id);
          else state.favorites.add(item.id);
          storage("localStorage", "favorite", [...state.favorites]);
          renderLibrary();
        }, "pe-star");
        favorite.setAttribute("aria-label", item.name + (starred ? "をお気に入りから外す" : "をお気に入りに追加"));
        favorite.setAttribute("aria-pressed", String(starred));
        row.append(open, favorite);
        list.append(row);
      }
      if (!items.length) list.append(element("li", "pe-empty", state.list.length ? "一致するプリセットがありません。" : "表示できるプリセットがありません。"));
    }

    function renderDiff() {
      const panel = id("diff");
      panel.replaceChildren();
      if (!state.draft) return;
      const baseline = state.comparison?.spec || state.original;
      const heading = state.comparison
        ? state.comparison.name + " と編集中の設定"
        : "開いたときの設定と編集中の設定";
      panel.append(element("h4", "", heading));
      const changes = differences(baseline, state.draft);
      if (!changes.length) panel.append(element("p", "pe-muted", "設定JSONに差分はありません。"));
      for (const { path, before, after } of changes) {
        const entry = element("article", "pe-change");
        const row = element("div", "pe-library-header");
        row.append(element("strong", "", path.join(" → ") || "設定全体"));
        if (path.length) row.append(button(state.comparison ? "比較元の値を使う" : "この変更を戻す", () => {
          change(path, before, true);
          renderDiff();
        }));
        const values = element("div", "pe-diff-values");
        for (const [label, value] of [["比較元", before], ["編集中", after]]) {
          const box = element("div");
          box.append(element("span", "pe-muted", label), element("pre", "", value === undefined ? "項目なし" : format(value)));
          values.append(box);
        }
        entry.append(row, values);
        panel.append(entry);
      }
      if (changes.length === 150) panel.append(element("p", "pe-muted", "先頭150件を表示しています。"));
      if (!equal(state.tags, state.originalTags)) panel.append(element("p", "", "タグも変更されています。"));
    }

    function reset(spec, item, candidate = "") {
      if (hasSecretKey(spec)) throw new Error("認証情報を除いてから読み込んでください。");
      state.origin = item ? {
        id: item.id, name: item.name, source: item.source, revision: item.revision, updated_at: item.updated_at,
      } : null;
      state.draft = clone(spec);
      state.original = clone(spec);
      state.tags = item?.tags ? [...item.tags] : [];
      state.originalTags = [...state.tags];
      state.candidate = candidate || item?.id || "";
      state.older = [];
      state.newer = [];
      state.invalidFields.clear();
      state.comparison = null;
      state.conflict = null;
      invalidatePreview();
      refreshJson();
      renderForm();
      renderLibrary();
      showIssues();
      update();
      setMode("gui", true);
      remember();
    }

    function confirmDiscard() {
      return !dirty() || window.confirm("未保存の変更があります。変更を破棄して続けますか？");
    }

    async function loadItem(key) {
      const item = await request("/" + encodeURIComponent(key));
      state.recent = [key, ...state.recent.filter((entry) => entry !== key)].slice(0, 30);
      storage("localStorage", "recent", state.recent);
      reset(item.spec, item);
      announce(item.secrets_removed ? "旧プリセット内の認証項目を除いて開きました。" : item.name + "を開きました。");
    }

    async function refresh() {
      const [catalog, connections] = await Promise.all([
        request(), request(hooks.connectionUrl).catch(() => ({})),
      ]);
      state.list = catalog.presets;
      state.connections = (connections.profiles || connections.connections || []).map(({ id, name }) => ({ id, name }));
      renderLibrary();
      if (state.draft) renderForm();
    }

    function checkDraft() {
      acceptJson();
      if (state.mode === "json") renderForm();
      const invalid = root.querySelector("#pe-gui input:invalid, #pe-gui textarea:invalid, #pe-gui select:invalid");
      if (invalid || state.invalidFields.size) {
        const path = invalid?.dataset.pePath;
        setMode("gui", true);
        const current = [...root.querySelectorAll("[data-pe-path]")].find((node) => node.dataset.pePath === path);
        const detail = current?.closest("details");
        if (detail) detail.open = true;
        current?.reportValidity();
        throw new Error("無効な入力を修正するか、「無効な入力を戻す」を選んでください。");
      }
      if (!state.draft) throw new Error("プリセットを選択してください。");
      if (hasSecretKey(state.draft)) throw new Error("認証情報は接続プロファイルに設定してください。");
      return state.draft;
    }

    async function validate(compact = false) {
      const result = await request("/validate", "POST", { spec: checkDraft(), tags: state.tags });
      return compact ? result.compact_spec : result.spec;
    }

    function slug(value, fallback = "preset") {
      return String(value || "").normalize("NFKD").toLowerCase().replace(/[^a-z0-9_-]+/g, "-")
        .replace(/^-+|-+$/g, "").slice(0, 64) || fallback;
    }

    function unusedId(base) {
      const names = new Set(state.list.map(({ id }) => id));
      if (!names.has(base)) return base;
      let index = 2;
      while (names.has(base.slice(0, 59) + "-" + index)) index++;
      return base.slice(0, 59) + "-" + index;
    }

    function saveDialog(defaultId, defaultName, title) {
      const dialog = id("save-dialog");
      const form = dialog.querySelector("form");
      form.elements.namedItem("id").value = defaultId;
      form.elements.namedItem("name").value = defaultName.slice(0, 120);
      id("save-title").textContent = title;
      dialog.returnValue = "";
      return new Promise((resolve) => {
        dialog.addEventListener("close", () => resolve(dialog.returnValue === "save" ? {
          id: form.elements.namedItem("id").value.trim(), name: form.elements.namedItem("name").value.trim(),
        } : null), { once: true });
        dialog.showModal();
        form.elements.namedItem("id").focus();
        form.elements.namedItem("id").select();
      });
    }

    async function copy(asSnapshot = false) {
      const source = asSnapshot ? state.original : checkDraft();
      const tags = asSnapshot ? state.originalTags : state.tags;
      const base = slug(state.origin?.id || state.candidate || source.name);
      const stamp = new Date().toISOString().slice(0, 19).replace(/[^0-9]/g, "");
      const suffix = asSnapshot ? "-backup-" + stamp : (state.origin ? "-copy" : "");
      const target = unusedId(base.slice(0, 64 - suffix.length) + suffix);
      const naming = await saveDialog(target,
        (source.name || "プリセット") + (asSnapshot ? "（バックアップ）" : ""), asSnapshot ? "元の版を別名で保存" : "別名で保存");
      if (!naming) return;
      if (!naming.name) throw new Error("表示名を入力してください。");
      const result = await request("", "POST", { id: naming.id, spec: { ...source, name: naming.name }, tags });
      if (!asSnapshot) reset(result.spec, result);
      await afterSave();
      announce(result.id + "として保存しました。");
    }

    async function afterSave() {
      try {
        await Promise.all([refresh(), hooks.refresh?.()]);
      } catch {
        announce("保存しました。一覧を再読み込みして反映を確認できます。");
      }
    }

    async function run(task) {
      if (state.busy) return;
      state.busy = true;
      id("lock").disabled = true;
      root.setAttribute("aria-busy", "true");
      showIssues();
      try {
        await task();
      } catch (error) {
        announce(error.message || "操作に失敗しました。", "error");
        showIssues(error.issues);
        if (error.status === 412 && state.origin) {
          try {
            state.conflict = await request("/" + encodeURIComponent(state.origin.id));
            state.comparison = state.conflict;
            setMode("diff", true);
          } catch {
            // A competing deletion may remove the comparison target.
          }
        }
      } finally {
        state.busy = false;
        id("lock").disabled = false;
        root.setAttribute("aria-busy", "false");
        update();
      }
    }

    function exportFile(name, data) {
      const url = URL.createObjectURL(new Blob([format(data) + "\n"], { type: "application/json" }));
      const link = element("a");
      link.href = url;
      link.download = name;
      document.body.append(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    }

    function renderPreview(data) {
      const panel = id("preview-result");
      panel.replaceChildren(element("h4", "", "生成データの見本"));
      const records = Array.isArray(data.records) ? data.records : [];
      const cols = [...new Set(records.flatMap((record) => object(record) ? Object.keys(record) : []))];
      if (cols.length) {
        const wrap = element("div", "pe-table-scroll");
        wrap.tabIndex = 0;
        wrap.setAttribute("role", "region");
        wrap.setAttribute("aria-label", "プレビュー表");
        const grid = element("table");
        const head = grid.createTHead().insertRow();
        const tableBody = grid.createTBody();
        for (const name of cols) head.append(element("th", "", name));
        for (const record of records) {
          const row = tableBody.insertRow();
          for (const name of cols) {
            const value = record?.[name];
            row.append(element("td", "", value === null ? "null" : typeof value === "object" ? format(value) : (value ?? "—")));
          }
        }
        wrap.append(grid);
        panel.append(wrap);
      }
      for (const warning of data.warnings || []) panel.append(element("p", "pe-warning", warning?.message || warning));
      const raw = element("details");
      raw.append(element("summary", "", "見本のJSON"));
      const { validated_spec, compact_spec, ...output } = data;
      raw.append(element("pre", "pe-code", format(output)));
      panel.append(raw);
      panel.hidden = false;
      panel.focus();
    }

    const actions = {
      capture: () => {
        if (!confirmDiscard()) return;
        reset(hooks.capture(), null);
        announce("現在の実行設定を読み込みました。");
      },
      refresh,
      "apply-json": () => {
        acceptJson();
        setMode("gui");
        announce("JSONを編集欄に反映しました。");
      },
      "format-json": () => {
        acceptJson();
        refreshJson();
        announce("JSONを整形しました。");
      },
      "revert-fields": () => {
        state.invalidFields.clear();
        renderForm();
        remember();
        announce("無効な入力を最後に反映した値に戻しました。");
      },
      "revert-json": () => {
        refreshJson();
        remember();
        announce("最後に有効だったJSONに戻しました。");
      },
      undo: () => {
        if (!state.older.length) return;
        state.newer.push(snapshot());
        restoreSnapshot(state.older.pop());
      },
      redo: () => {
        if (!state.newer.length) return;
        state.older.push(snapshot());
        restoreSnapshot(state.newer.pop());
      },
      validate: async () => {
        await validate();
        announce("検証に合格しました。");
      },
      preview: async () => {
        const safe = await validate();
        const data = await request("/api/preview", "POST", safe);
        if (data.writes !== false) throw new Error("読み取り専用のプレビューを確認できませんでした。");
        state.preview = data;
        renderPreview(data);
        announce("見本を表示しました。");
      },
      use: async () => {
        const valid = await validate();
        hooks.apply(valid);
        announce("実行画面へ反映しました。");
      },
      save: async () => {
        if (state.origin?.source !== "user" || !dirty()) return;
        const spec = checkDraft();
        const result = await request("/" + encodeURIComponent(state.origin.id), "PUT", { spec, tags: state.tags }, state.origin.revision);
        reset(result.spec, result);
        await afterSave();
        announce(result.id + "を更新しました。");
      },
      "save-copy": () => copy(),
      snapshot: () => copy(true),
      clone: () => {
        const spec = clone(checkDraft());
        const tags = [...state.tags];
        const base = slug(state.origin?.id || state.candidate || spec.name);
        const key = unusedId(base.slice(0, 59) + "-copy");
        spec.name = (spec.name || "プリセット").slice(0, 112) + "（コピー）";
        reset(spec, null, key);
        state.original = null;
        state.tags = tags;
        renderForm();
        update();
        remember();
        announce("複製しました。別名で保存するまで一覧には追加されません。");
      },
      delete: async () => {
        const item = state.origin;
        if (item?.source !== "user" || !window.confirm("「" + (item.name || item.id) + "」を保存済み一覧から削除しますか？")) return;
        await request("/" + encodeURIComponent(item.id), "DELETE", undefined, item.revision);
        reset(state.draft, null, item.id);
        state.original = null;
        remember();
        await afterSave();
        announce("削除しました。開いていた内容は別名で保存できます。");
      },
      export: async () => {
        const spec = await validate(id("compact").checked);
        exportFile(slug(state.origin?.id || state.candidate || state.draft.name) + ".json", spec);
      },
      ai: async () => {
        const spec = await validate(true);
        exportFile(slug(state.origin?.id || state.candidate || state.draft.name) + "-ai.json", {
          format: "factory.preset-editor.v1", application: config.title,
          openapi: new URL("/openapi.json", location.origin).href,
          json_schema: hooks.connectionUrl === "/api/profiles"
            ? { path: "/api/info", pointer: "/schemas/spec" }
            : { path: "/api/schemas", pointer: "/run" },
          safety: "接続プロファイルIDだけを参照します。検証・見本の確認で生成開始や外部送信を呼ばないでください。",
          validation: { method: "POST", path: apiBase + "/validate", body: { spec, tags: state.tags } },
          preview: { method: "POST", path: "/api/preview", body_from: "validation.body.spec" },
        });
      },
      "compare-open": async () => {
        if (!id("compare").value) return;
        state.comparison = await request("/" + encodeURIComponent(id("compare").value));
        renderDiff();
      },
      "compare-reset": () => {
        state.comparison = null;
        renderDiff();
      },
      "rebase-draft": () => {
        if (!state.conflict || !window.confirm("最新の保存版を基準にします。画面での編集は残ります。既存を変更するにはこの後に上書き保存してください。")) return;
        const latest = state.conflict;
        state.origin = { id: latest.id, name: latest.name, source: latest.source, revision: latest.revision };
        state.original = clone(latest.spec);
        state.originalTags = [...latest.tags];
        state.comparison = null;
        state.conflict = null;
        renderDiff();
        remember();
        announce("最新の版を基準にしました。差分を確認してから上書きできます。");
      },
    };

    function restoreSnapshot(snapshot) {
      state.draft = snapshot.draft;
      state.invalidFields.clear();
      state.tags = snapshot.tags;
      invalidatePreview();
      refreshJson();
      renderForm();
      renderDiff();
      update();
      remember();
    }

    root.addEventListener("submit", (event) => {
      if (event.target === id("form")) event.preventDefault();
    });
    for (const [name, handler] of Object.entries(actions)) id(name).addEventListener("click", () => run(handler));
    for (const mode of root.querySelectorAll("[data-pe-mode]"))
      mode.addEventListener("click", () => setMode(mode.dataset.peMode));
    id("json").addEventListener("input", () => {
      state.rawDirty = true;
      invalidatePreview();
      try {
        const text = id("json").value;
        const draft = fromJson(text);
        state.invalidFields.clear();
        commit(draft, state.tags, false, false);
        state.rawDirty = false;
        announce("");
      } catch (error) {
        announce(error.message + " 下書きには最後に有効だったJSONが残ります。", "error");
      }
      update();
      remember();
    });
    id("import-open").addEventListener("click", () => id("import").click());
    id("import").addEventListener("change", (event) => run(async () => {
      const file = event.target.files?.[0];
      event.target.value = "";
      if (!file || !confirmDiscard()) return;
      if (file.size > 2 * 1024 * 1024) throw new Error("JSONは2MiB以下にしてください。");
      const raw = fromJson(await file.text());
      const spec = raw.format === "factory.preset-editor.v1" ? raw.validation?.body?.spec : raw;
      if (!object(spec)) throw new Error("プリセットJSONが見つかりません。");
      const valid = await request("/validate", "POST", { spec });
      reset(valid.spec, null, slug(file.name.replace(/\.json$/i, "")));
      state.original = null;
      update();
      remember();
      announce("JSONを読み込みました。");
    }));
    for (const name of ["search", "source", "sort"]) id(name).addEventListener("input", () => {
      renderLibrary();
      remember();
    });
    window.addEventListener("beforeunload", (event) => {
      if (dirty()) {
        event.preventDefault();
        event.returnValue = "";
      }
    });
    root.addEventListener("keydown", (event) => {
      if (!(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== "s" || !state.draft) return;
      event.preventDefault();
      run(state.origin?.source === "user" ? actions.save : actions["save-copy"]);
    });

    const draft = storage("sessionStorage", "draft");
    let initial = null;
    try {
      initial = hooks.initial ? hooks.initial() : hooks.capture();
    } catch {
      // The execution form can be incomplete. The catalog remains available.
    }
    reset(initial, null);
    if (draft && object(draft.draft) && !hasSecretKey(draft.draft)) {
      Object.assign(state, {
        draft: draft.draft, original: draft.original, tags: draft.tags || [], originalTags: draft.originalTags || [],
        origin: draft.origin, candidate: draft.candidate || "",
      });
      id("search").value = draft.search || "";
      id("source").value = draft.source || "";
      id("sort").value = draft.sort || "name";
      refreshJson();
      renderForm();
      update();
      setMode(["gui", "json", "diff"].includes(draft.mode) ? draft.mode : "gui", true);
      announce("このタブで編集中だった下書きを復元しました。");
    }

    return {
      activate() {
        if (!state.active) {
          state.active = true;
          run(refresh);
        }
      },
      open(value, item) {
        if (!confirmDiscard()) return false;
        if (item?.id) {
          run(async () => {
            if (!state.active) {
              await refresh();
              state.active = true;
            }
            await loadItem(item.id);
          });
        } else {
          reset(value, null);
          this.activate();
        }
        return true;
      },
    };
  }
})();
