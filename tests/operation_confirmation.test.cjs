const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = readFileSync(join(__dirname, "../static/api-client.js"), "utf8");

function confirmationFixture(confirm) {
  const requests = [];
  const prompts = [];
  const context = vm.createContext({
    Headers,
    URL,
    window: {
      location: { origin: "http://localhost" },
      confirm(message) {
        prompts.push(message);
        return confirm;
      },
    },
    async fetch(path, settings) {
      requests.push({ path, settings });
      if (requests.length === 1) return Response.json({}, { status: 428 });
      if (path === "/api/operations/plan") {
        return Response.json({
          confirmation_token: "synthetic-token",
          summary: {
            operation: "delete",
            destination_name: "試験用データベース",
            destination_id: "database-id",
            destination_kind: "sqlite",
            revision: 7,
            table: "sample_table",
            rows: 1000,
          },
        });
      }
      return Response.json({ id: "synthetic-run" }, { status: 202 });
    },
  });
  vm.runInContext(source, context);
  const settings = {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Expected-Connection-Revision": "7" },
    body: JSON.stringify({ connection_id: "database-id", connection_revision: 7, sql: {} }),
  };
  return { requests, prompts, call: () => context.fetchWithOperationConfirmation("/api/runs", settings) };
}

test("428の後に接続先・版・SQL操作を1回確認し、同じ要求にトークンを付ける", async () => {
  const { requests, prompts, call } = confirmationFixture(true);

  assert.equal((await call()).status, 202);
  assert.equal(prompts.length, 1);
  for (const expected of ["既存行を削除", "試験用データベース / database-id", "版 7",
    "sample_table（接続先の既定スキーマ）", "1,000件", "連鎖処理"]) {
    assert.ok(prompts[0].includes(expected), expected);
  }
  const [initial, plan, confirmed] = requests;
  assert.equal(plan.path, "/api/operations/plan");
  assert.deepEqual(JSON.parse(plan.settings.body), {
    path: initial.path,
    payload: JSON.parse(initial.settings.body),
  });
  assert.equal(confirmed.path, initial.path);
  assert.equal(confirmed.settings.body, initial.settings.body);
  assert.equal(confirmed.settings.headers.get("X-Expected-Connection-Revision"), "7");
  assert.equal(confirmed.settings.headers.get("X-Operation-Confirmation"), "synthetic-token");
});

test("確認を取り消した際はトークン付き要求を送らない", async () => {
  const { requests, prompts, call } = confirmationFixture(false);

  await assert.rejects(call(), /操作を取り消しました/);
  assert.equal(prompts.length, 1);
  assert.deepEqual(requests.map(({ path }) => path), ["/api/runs", "/api/operations/plan"]);
});
