"use strict";
const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

// 履歴の描画が使うDOM操作だけを実装し、サーバーや外部パッケージなしで検証する。
class Element {
  constructor(tag, document) {
    this.document = document;
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.dataset = {};
    this.open = false;
    this.scrollTop = 0;
    this.scrollLeft = 0;
  }
  get firstElementChild() { return this.children[0] ?? null; }
  get nextElementSibling() {
    const siblings = this.parentElement?.children;
    return siblings?.[siblings.indexOf(this) + 1] ?? null;
  }
  get isConnected() { return this.parentElement?.isConnected ?? this.connected ?? false; }
  remove() {
    if (!this.parentElement) return;
    if (this.contains(this.document.activeElement)) this.document.activeElement = null;
    const siblings = this.parentElement.children;
    siblings.splice(siblings.indexOf(this), 1);
    this.parentElement = undefined;
  }
  insertBefore(child, before) {
    child.remove();
    const index = before ? this.children.indexOf(before) : this.children.length;
    assert.ok(index >= 0);
    this.children.splice(index, 0, child);
    child.parentElement = this;
  }
  append(...children) {
    for (const child of children) this.insertBefore(child, null);
  }
  replaceChildren(...children) {
    for (const child of Array.from(this.children)) child.remove();
    this.append(...children);
  }
  contains(node) { return node === this || this.children.some((child) => child.contains(node)); }
  focus() { this.document.activeElement = this; }
  getBoundingClientRect() { return this.bounds ?? { top: 0, bottom: 0 }; }
  getClientRects() { return this.parentElement?.getClientRects().length === 0 || this.hidden ? [] : [{}]; }
  setAttribute(name, value) {
    if (name === "data-run-id") this.dataset.runId = value;
  }
  addEventListener() {}
  querySelectorAll(selector) {
    const matches = (this.tagName === "SUMMARY" && selector === "summary")
      || (this.tagName === "PRE" && selector === "pre")
      || (this.tagName === "DETAILS" && (selector === "details"
        || (selector === "details[data-run-id][open]"
          && this.dataset.runId !== undefined && this.open)));
    return [
      ...(matches ? [this] : []),
      ...this.children.flatMap((child) => child.querySelectorAll(selector)),
    ];
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0]; }
}

function fixture() {
  const elements = new Map();
  const listeners = new Map();
  const document = {
    activeElement: null,
    selection: null,
    getSelection() { return this.selection; },
    addEventListener(type, callback) { listeners.set(type, callback); },
    createElement: (tag) => new Element(tag, document),
    querySelector: (id) => {
      if (!elements.has(id)) {
        const node = new Element("div", document);
        node.connected = true;
        elements.set(id, node);
      }
      return elements.get(id);
    },
  };
  const source = readFileSync(join(__dirname, "../static/app.js"), "utf8");
  // 起動処理だけを切り離し、製品の履歴更新関数をそのまま使う。
  const entry = source.lastIndexOf("\ninit().catch(");
  assert.ok(entry > 0);
  let now = 0;
  const context = vm.createContext({
    document, window: { addEventListener() {} }, performance: { now: () => now },
  });
  vm.runInContext(source.slice(0, entry), context);
  const pending = [];
  context.fetch = async (path) => {
    assert.equal(path, "/api/runs");
    return new Promise((resolve) => {
      pending.push((runs) => resolve({ ok: true, json: async () => ({ runs }) }));
    });
  };
  vm.runInContext('state.info = {kind: "sql"};', context);
  const start = () => vm.runInContext("refreshHistory()", context);
  const finish = (runs, index = 0) => pending.splice(index, 1)[0](runs);
  const refresh = async (...runs) => {
    const request = start();
    finish(runs);
    await request;
  };
  const details = (area) => document.querySelector(area).querySelectorAll("details");
  const detail = (area, id) => details(area).find((node) => node.dataset.runId === id);
  const bringBack = (area) => {
    context.container = document.querySelector(area);
    vm.runInContext("restoreJobPanes(container)", context);
  };
  const clearSelection = () => {
    document.selection = null;
    listeners.get("selectionchange")();
  };
  const anchor = () => vm.runInContext('readingJobAnchor($("#historyList"))?.id', context);
  const showViewport = () => Object.assign(context.window, { scrollY: 500, innerHeight: 1050 });
  const dispatch = (type, event) => listeners.get(type)(event);
  const setNow = (value) => { now = value; };
  return { document, start, finish, refresh, details, detail, bringBack, clearSelection,
    anchor, showViewport, dispatch, setNow };
}

function run(id, processed = 0, status = "completed") {
  return {
    id, status, created_at: "2000-01-01",
    spec: { name: id, rows: 10, connection_id: "fixture" },
    stats: { processed },
  };
}

test("履歴は並び替えと進捗更新後も同じ実行だけ開く", async () => {
  const { refresh, detail } = fixture();
  await refresh(run("alpha"), run("beta"));
  assert.equal(detail("#historyList", "alpha").open, false);
  detail("#historyList", "alpha").open = true;
  await refresh(run("beta"), run("alpha", 7));
  assert.equal(detail("#historyList", "alpha").open, true);
  assert.equal(detail("#historyList", "beta").open, false);
  assert.equal(JSON.parse(detail("#historyList", "alpha").children[1].textContent).stats.processed, 7);
});

test("更新要求の待機中に閉じて別の実行を開くと、応答後もその状態を保つ", async () => {
  const { refresh, start, finish, detail } = fixture();
  await refresh(run("alpha"), run("beta"));
  detail("#historyList", "alpha").open = true;
  const request = start();
  detail("#historyList", "alpha").open = false;
  detail("#historyList", "beta").open = true;
  finish([run("alpha"), run("beta")]);
  await request;
  assert.equal(detail("#historyList", "alpha").open, false);
  assert.equal(detail("#historyList", "beta").open, true);
});

test("履歴と稼働中は独立し、新しい実行へ旧状態を引き継がない", async () => {
  const { refresh, detail, details } = fixture();
  await refresh(run("alpha", 1, "running"));
  detail("#currentJob", "alpha").open = true;
  await refresh(run("alpha", 2, "stopping"));
  assert.equal(detail("#currentJob", "alpha").open, true);
  assert.equal(detail("#historyList", "alpha").open, false);
  await refresh(run("alpha", 3));
  assert.equal(details("#currentJob").length, 0);
  await refresh(run("beta", 0, "running"), run("alpha", 3));
  assert.equal(detail("#currentJob", "beta").open, false);
  assert.equal(detail("#historyList", "beta").open, false);
});


test("以前の応答は新しい進捗・開閉・キーボードフォーカスを戻さない", async () => {
  const { document, refresh, start, finish, detail } = fixture();
  await refresh(run("alpha", 1));
  const before = detail("#historyList", "alpha");
  before.open = true;
  before.querySelector("summary").focus();
  const older = start();
  const newer = start();
  finish([run("alpha", 8)], 1);
  await newer;
  const after = detail("#historyList", "alpha");
  assert.equal(after.open, true);
  assert.equal(document.activeElement, after.querySelector("summary"));
  finish([run("alpha", 2), run("beta")]);
  await older;
  assert.equal(detail("#historyList", "alpha"), after);
  assert.equal(detail("#historyList", "beta"), undefined);
  assert.equal(JSON.parse(after.children[1].textContent).stats.processed, 8);
});

test("JSONのスクロールとフォーカスは同じ表示領域と実行にだけ戻す", async () => {
  const { document, refresh, detail } = fixture();
  await refresh(run("alpha", 1, "running"));
  const old = detail("#historyList", "alpha");
  old.open = true;
  const pane = old.querySelector("pre");
  pane.scrollTop = 180;
  pane.scrollLeft = 27;
  pane.focus();
  await refresh(run("new"), run("alpha", 2, "running"));
  const current = detail("#historyList", "alpha").querySelector("pre");
  assert.equal(current.scrollTop, 180);
  assert.equal(current.scrollLeft, 27);
  assert.equal(document.activeElement, current);
  assert.equal(JSON.parse(current.textContent).stats.processed, 2);
  assert.equal(detail("#currentJob", "alpha").querySelector("pre").scrollTop, 0);
  assert.equal(detail("#historyList", "new").querySelector("pre").scrollTop, 0);
  await refresh(run("new"));
  assert.equal(document.activeElement, null);
  assert.equal(detail("#historyList", "new").open, false);
});

test("非表示中の更新は閲覧位置を上書きせず、戻ってから0へ移動できる", async () => {
  const { document, refresh, detail, bringBack } = fixture();
  await refresh(run("alpha", 1));
  const container = document.querySelector("#historyList");
  const old = detail("#historyList", "alpha");
  old.open = true;
  old.querySelector("pre").scrollTop = 120;
  await refresh(run("alpha", 2));
  container.hidden = true;
  await refresh(run("alpha", 3));
  // ブラウザーが非表示中に座標を書き戻せない状態を模擬する。
  detail("#historyList", "alpha").querySelector("pre").scrollTop = 0;
  container.hidden = false;
  bringBack("#historyList");
  assert.equal(detail("#historyList", "alpha").querySelector("pre").scrollTop, 120);
  detail("#historyList", "alpha").querySelector("pre").scrollTop = 0;
  await refresh(run("alpha", 4));
  assert.equal(detail("#historyList", "alpha").querySelector("pre").scrollTop, 0);
});

test("選択中の本文を保ち、別の実行を描きながら解除時だけ最新JSONを表示する", async () => {
  const { document, refresh, detail, details, clearSelection } = fixture();
  await refresh(run("alpha", 1), run("beta", 1));
  const beta = detail("#historyList", "beta");
  beta.open = true;
  const pane = beta.querySelector("pre");
  document.selection = {
    isCollapsed: false, rangeCount: 1,
    getRangeAt: () => ({ intersectsNode: (node) => node === pane }),
  };
  await refresh(run("beta", 2), run("new", 1), run("alpha"));
  await refresh(run("beta", 3), run("new", 2), run("alpha"));
  assert.equal(details("#historyList")[0], beta);
  assert.equal(detail("#historyList", "beta").querySelector("pre"), pane);
  assert.equal(JSON.parse(pane.textContent).stats.processed, 1);
  assert.equal(JSON.parse(detail("#historyList", "new").querySelector("pre").textContent).stats.processed, 2);
  clearSelection();
  assert.equal(JSON.parse(pane.textContent).stats.processed, 3);
});


test("マウスで読んだ二番目のJSONを優先し、移動や時間切れ後は曖昧な枠へ飛ばない", async () => {
  const { refresh, detail, anchor, showViewport, dispatch, setNow } = fixture();
  await refresh(run("alpha"), run("beta"));
  const panes = ["alpha", "beta"].map((id, i) => {
    const node = detail("#historyList", id);
    node.open = true;
    const pane = node.querySelector("pre");
    pane.bounds = { top: 30 + 840 * i, bottom: 530 + 840 * i };
    pane.scrollTop = 120;
    return pane;
  });
  showViewport();
  assert.equal(anchor(), undefined);
  const wheel = { target: { closest: () => panes[1] }, clientX: 480, clientY: 910 };
  dispatch("wheel", wheel);
  assert.equal(anchor(), "beta");
  dispatch("pointermove", { clientX: 480, clientY: 910 });
  assert.equal(anchor(), "beta");
  dispatch("pointermove", { clientX: 481, clientY: 910 });
  assert.equal(anchor(), undefined);
  dispatch("wheel", wheel);
  setNow(4999);
  assert.equal(anchor(), "beta");
  setNow(5000);
  assert.equal(anchor(), undefined);
  panes[0].scrollTop = 0;
  assert.equal(anchor(), "beta");
});
