"use strict";
const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

test("4つのイベント例は既存の接続先を維持し、秘密値や送信を追加しない", () => {
  const source = readFileSync(join(__dirname, "../static/app.js"), "utf8");
  const context = vm.createContext({
    structuredClone,
    document: { querySelector: () => ({}), addEventListener() {} },
    window: { addEventListener() {} },
    fetch() { throw new Error("例の選択だけでHTTP通信した"); },
    defaults: {
      connection_id: "default", stream: { envelope: true },
      parameters: { start_time: "2020-01-01T00:00:00Z" },
    },
  });
  vm.runInContext(source.slice(0, source.lastIndexOf("\ninit().catch(")), context);
  const examples = vm.runInContext(`JSON.stringify(Object.keys(streamScenarios).map(
    (id) => scenarioSpec(id, defaults, "explicit-choice", "new-run-" + id)
  ))`, context);
  const models = JSON.parse(examples);
  assert.equal(models.length, 4);
  assert.deepEqual(models.map(x => x.fields[2].name),
    ["value", "temperature_c", "progress_pct", "severity"]);
  assert.ok(models.every(x => x.connection_id === "explicit-choice" &&
    x.connection_revision === null && x.rows === 30 && x.stream.envelope));
  assert.equal(models[3].anomalies[0].probability, 0.2);
  assert.deepEqual(context.defaults.stream, { envelope: true });
});

test("同じ接続IDでも版が変われば旧プレビューで送信せず、解決後も自動再送しない", async () => {
  const source = readFileSync(join(__dirname, "../static/app.js"), "utf8");
  const panel = {};
  const context = vm.createContext({
    structuredClone,
    document: {
      querySelector: () => panel,
      addEventListener() {},
    },
    window: { addEventListener() {} },
  });
  panel.querySelectorAll = () => [];
  vm.runInContext(source.slice(0, source.lastIndexOf("\ninit().catch(")), context);
  const apiClient = readFileSync(join(__dirname, "../static/api-client.js"), "utf8");
  vm.runInContext(apiClient, context);
  let attempts = 0;
  let refreshes = 0;
  context.fetch = async (path, settings) => {
    assert.equal(path, "/api/runs");
    const spec = JSON.parse(settings.body);
    attempts++;
    assert.equal(spec.connection_revision, 2);
    assert.equal(settings.headers["X-Expected-Connection-Revision"], "2");
    return Response.json({ detail: "接続先が変更されました。" }, { status: 409 });
  };
  context.refresh = async () => {
    refreshes++;
    vm.runInContext('state.connections[0].revision = 3', context);
  };
  vm.runInContext(`
    state.spec = { connection_id: "fixed", connection_revision: null };
    state.connections = [{ id: "fixed", revision: 1 }];
    state.previewedDestination = streamActionSnapshot();
  `, context);
  assert.ok(vm.runInContext("isPreviewCurrent(streamActionSnapshot())", context));
  vm.runInContext("state.connections[0].revision = 2", context);
  assert.ok(!vm.runInContext("isPreviewCurrent(streamActionSnapshot())", context));
  vm.runInContext("state.previewedDestination = streamActionSnapshot()", context);
  await assert.rejects(
    vm.runInContext('guardedStreamAction("/api/runs", streamActionSnapshot(), api, refresh)', context),
    /プレビューし直して/,
  );
  assert.equal(attempts, 1);
  assert.equal(refreshes, 1);
  assert.ok(panel.hidden);
  assert.equal(vm.runInContext("state.previewedDestination", context), null);
  assert.ok(!vm.runInContext("isPreviewCurrent(streamActionSnapshot())", context));
});

function editorFixture() {
  class Element {
    constructor() {
      this.children = [];
      this.listeners = {};
    }
    append(...children) { this.children.push(...children); }
    replaceChildren() { this.children = []; }
    addEventListener(name, handler) { this.listeners[name] = handler; }
    setAttribute() {}
    querySelectorAll() { return []; }
    find(text) {
      if (this.textContent === text) return this;
      return this.children.map((child) => child.find(text)).find(Boolean);
    }
  }
  const source = readFileSync(join(__dirname, "../static/app.js"), "utf8");
  const nodes = new Map();
  const context = vm.createContext({
    structuredClone,
    document: {
      createElement: () => new Element(),
      addEventListener() {},
      querySelector(id) {
        if (!nodes.has(id)) nodes.set(id, new Element());
        return nodes.get(id);
      },
    },
    window: { addEventListener() {} },
  });
  const run = (expression) => vm.runInContext(expression, context);
  run(source.slice(0, source.lastIndexOf("\ninit().catch(")));
  run(`
    state.spec = {
      connection_id: "test",
      fields: [{name: "first"}, {name: "value"}],
      anomalies: [{name: "test anomaly", field: "value"}],
    };
    state.connections = [{id: "test", revision: 1}];
    state.schemas = {run: {$defs: {FieldRule: {properties: {}}, AnomalyRule: {}}}};
    control = () => document.createElement("input");
    renderObject = () => {};
    defaultValue = () => ({});
    previewResult = () => { state.previewRenderCount = (state.previewRenderCount || 0) + 1; };
  `);
  return {context, run, nodes};
}

test("属性と異常の操作ボタンが表示済みプレビューを無効にする", async () => {
  for (const [renderer, button] of [
    ["renderFields", "↓"],
    ["renderFields", "複製"],
    ["renderFields", "削除"],
    ["renderFields", "＋ イベント属性を追加"],
    ["renderAnomalies", "削除"],
    ["renderAnomalies", "＋ 異常ルールを追加"],
  ]) {
    const {context, run, nodes} = editorFixture();
    run(`${renderer}(document.querySelector("#editor"));
      state.previewedDestination = streamActionSnapshot();
      document.querySelector("#previewPanel").hidden = false;`);
    let calls = 0;
    context.send = () => { calls++; };
    run("guardedStreamAction = send");
    nodes.get("#editor").find(button).listeners.click();
    assert.equal(nodes.get("#previewPanel").hidden, true, button);
    await assert.rejects(run("startStream()"), /プレビューしてから送信/);
    assert.equal(calls, 0, button);
  }
});

test("通知のないモデル変更でも進行中の応答と表示済み本文を再利用しない", async () => {
  for (const mutation of [
    "state.spec.fields.reverse()",
    "state.spec.anomalies[0].value = 10",
  ]) {
    const {context, run} = editorFixture();
    let resolve;
    let calls = 0;
    context.send = (path) => {
      calls++;
      assert.equal(path, "/api/preview");
      return new Promise((done) => { resolve = done; });
    };
    run("guardedStreamAction = send");
    const pending = run("previewStream()");
    run(mutation);
    resolve({connection_revision: 1});
    await pending;
    assert.equal(run("state.previewRenderCount"), undefined);
    assert.equal(run("state.previewedDestination"), null);
    const current = run("previewStream()");
    resolve({connection_revision: 1});
    await current;
    assert.equal(run("state.previewRenderCount"), 1);
    run("state.spec.fields[0].name = 'unseen'");
    await assert.rejects(run("startStream()"), /プレビューしてから送信/);
    assert.equal(calls, 2);
  }
});
