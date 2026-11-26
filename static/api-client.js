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
  let data;
  try {
    data = await response.json();
  } catch {
    const message = response.status >= 500
      ? "サーバー側でエラーが発生しました。実行履歴・接続先を確認してください。"
      : "アプリから設定の応答を受け取れませんでした。接続先の画面・認証を確認してください。";
    throw new Error(message + `（HTTP ${response.status}）`);
  }
  if (response.ok) return data;

  const detail = data?.detail;
  if (Array.isArray(detail)) {
    const issues = detail.slice(0, 6).map((item) => {
      const location = item.location || item.loc?.slice(1).join(" → ") || "設定";
      return location + "　" + (item.msg || "入力を確認してください。");
    });
    if (detail.length > 6) issues.push(`ほか${detail.length - 6}件。先に上の項目を直して再確認してください。`);
    throw new Error(issues.join("\n"));
  }
  throw new Error(typeof detail === "string" ? detail : `要求に失敗しました（HTTP ${response.status}）。`);
}
