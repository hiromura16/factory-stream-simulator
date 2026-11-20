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
  }
  append(...children) {
    for (const child of children) child.parentElement = this;
    this.children.push(...children);
  }
  replaceChildren(...children) {
    if (this.contains(this.document.activeElement)) this.document.activeElement = null;
    this.children = [];
    this.append(...children);
  }
  contains(node) { return node === this || this.children.some((child) => child.contains(node)); }
  focus() { this.document.activeElement = this; }
  setAttribute(name, value) {
    if (name === "data-run-id") this.dataset.runId = value;
  }
  addEventListener() {}
  querySelectorAll(selector) {
    const matches = (this.tagName === "SUMMARY" && selector === "summary")
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
  const document = {
    activeElement: null,
    addEventListener() {},
    createElement: (tag) => new Element(tag, document),
    querySelector: (id) => {
      if (!elements.has(id)) elements.set(id, new Element("div", document));
      return elements.get(id);
    },
  };
  const source = readFileSync(join(__dirname, "../static/app.js"), "utf8");
  // 起動処理だけを切り離し、製品の履歴更新関数をそのまま使う。
  const entry = source.lastIndexOf("\ninit().catch(");
  assert.ok(entry > 0);
  const context = vm.createContext({ document, window: { addEventListener() {} } });
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
  return { document, start, finish, refresh, details, detail };
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
