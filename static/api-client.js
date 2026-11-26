function readPresetJson(text) {
  try {
    return JSON.parse(text);
  } catch (error) {
    const position = error.message.match(/position (\d+)/)?.[1];
    const location = position === undefined ? "" : `（${Number(position) + 1}文字目の付近）`;
    throw new Error("JSONの構文を確認してください" + location + "。末尾のカンマ、引用符、括弧に注意してください。");
  }
}

async function readApiJson(response) {
  const httpError = (message) => Object.assign(new Error(message), { status: response.status });
  let data;
  try {
    data = await response.json();
  } catch {
    const message = response.status >= 500
      ? "サーバー側でエラーが発生しました。実行履歴・接続先を確認してください。"
      : "アプリから設定の応答を受け取れませんでした。接続先の画面・認証を確認してください。";
    throw httpError(message + `（HTTP ${response.status}）`);
  }
  if (response.ok) return data;

  const detail = data?.detail;
  if (Array.isArray(detail)) {
    const issues = detail.slice(0, 6).map((item) => {
      const location = item.location || item.loc?.slice(1).join(" → ") || "設定";
      return location + "　" + (item.msg || "入力を確認してください。");
    });
    if (detail.length > 6) issues.push(`ほか${detail.length - 6}件。先に上の項目を直して再確認してください。`);
    throw httpError(issues.join("\n"));
  }
  throw httpError(typeof detail === "string" ? detail : `要求に失敗しました（HTTP ${response.status}）。`);
}

async function fetchWithOperationConfirmation(path, settings) {
  const response = await fetch(path, settings);
  if (response.status !== 428 || settings?.method !== "POST") return response;
  const action = new URL(path, window.location.origin);
  const enabled = ["/api/start", "/api/runs", "/api/table/prepare", "/api/outbox/retry"];
  if (action.origin !== window.location.origin || !enabled.includes(action.pathname)) {
    return response;
  }
  const payload = JSON.parse(settings.body);
  const planRequest = { path: action.pathname, payload };
  const revision = action.searchParams.get("profile_revision");
  if (revision !== null) planRequest.profile_revision = Number(revision);
  const plan = await readApiJson(await fetch("/api/operations/plan", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(planRequest),
  }));
  if (!plan.confirmation_token) throw new Error("接続先または設定が変わりました。内容を確認し直してください。");

  const {
    operation, destination_name, destination_id, destination_kind,
    revision: plannedRevision, table, rows,
  } = plan.summary;
  const operations = {
    create_table: "未作成のテーブルを作成",
    insert: "新しい行を追加",
    update: "既存行を更新",
    delete: "既存行を削除",
    upsert: "未登録行を追加し、該当する既存行を更新",
  };
  const destination = destination_name ? destination_name + " / " + destination_id : destination_id;
  const lines = [
    "操作：" + (Object.hasOwn(operations, operation) ? operations[operation] : operation),
    "接続先：" + destination + "（版 " + plannedRevision + "）",
  ];
  if (destination_kind) lines.push("接続の種類：" + destination_kind);
  if (table) {
    const tableName = payload.sql?.schema_name ? table : table + "（接続先の既定スキーマ）";
    lines.push("対象テーブル：" + tableName);
  }
  if (operation === "create_table") {
    lines.push("既存テーブルは変更しません。");
  } else if (rows !== undefined) {
    const countLabel = table ? "設定した生成行数：" : "件数：";
    lines.push(countLabel + rows.toLocaleString("ja-JP") + "件");
    if (table && ["update", "delete", "upsert"].includes(operation)) {
      lines.push("表示件数は設定値です。実際の更新・削除件数や連鎖処理の件数は実行結果で確認してください。");
    }
  }
  if (plan.summary.max_ticks !== undefined) {
    lines.push("ティック上限：" + (plan.summary.max_ticks || "上限なし"));
  }
  if (plan.summary.initial_samples !== undefined) {
    lines.push("初期サンプル：" + plan.summary.initial_samples);
  }
  if (!window.confirm(lines.join("\n") + "\n\nこの内容で実行しますか？")) {
    throw new Error("操作を取り消しました。");
  }
  const headers = new Headers(settings.headers);
  headers.set("X-Operation-Confirmation", plan.confirmation_token);
  return fetch(path, { ...settings, headers });
}

function showPreviewWarnings(path, data) {
  if (path !== "/api/preview" || !Array.isArray(data?.warnings)) return;
  const target = document.querySelector("#previewWarnings");
  if (!target) return;
  target.textContent = data.warnings.map(({ loc, msg }) => {
    const location = loc.slice(1).map((part) => Number.isInteger(part) ? String(part + 1) + "番目" : part);
    return [location.join(" → "), msg].join("　");
  }).join("\n");
  target.hidden = !data.warnings.length;
}
