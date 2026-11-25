"use strict";

window.FactoryComparison = {
  mount({app, listPresets, currentSpec, preview, metrics}) {
    const panel = document.querySelector("#comparison");
    const find = (selector) => panel.querySelector(selector);
    const search = find("#comparisonSearch");
    const catalog = find("#comparisonCatalog");
    const onlyFavorites = find("#comparisonFavoritesOnly");
    const includeCurrent = find("#comparisonCurrent");
    const runButton = find("#comparisonRun");
    const stopButton = find("#comparisonStop");
    const differences = find("#comparisonDifferences");
    const status = find("#comparisonStatus");
    const results = find("#comparisonResults");
    const clearButton = find("#comparisonClear");
    const storageKey = "factory-comparison-favorites:" + app;
    const maxPresets = 3;
    const selected = new Set();
    let favorites = new Set();
    let busy = false;
    let stopRequested = false;
    let report = null;

    try {
      const saved = JSON.parse(localStorage.getItem(storageKey) || "[]");
      if (Array.isArray(saved)) favorites = new Set(saved.filter(validId));
    } catch {
      // ブラウザーの保存領域を使えない場合も、この画面内では利用できる。
    }

    function node(tag, label) {
      const element = document.createElement(tag);
      if (label !== undefined) element.textContent = label;
      return element;
    }

    function validId(id) {
      return typeof id === "string" && /^[A-Za-z0-9_-]{1,64}$/.test(id);
    }

    function normalize(value) {
      return String(value ?? "").normalize("NFKC").toLowerCase();
    }

    function presetName(preset) {
      return preset.spec.name || preset.name || preset.id;
    }

    function presetScenario(preset) {
      return (preset.spec.description || "").trim().split(/\r?\n\s*\r?\n/, 1)[0]
        .replace(/^【想定(?:する状況)?】\s*/, "");
    }

    function button(label, onClick) {
      const element = node("button", label);
      element.type = "button";
      element.addEventListener("click", onClick);
      return element;
    }

    function showInEditor(preset) {
      const nav = document.querySelector('.nav[data-tab="generate"]');
      const select = document.querySelector("#presetSelect");
      nav.click();
      for (let parent = select.closest("details"); parent; parent = parent.parentElement.closest("details")) {
        parent.open = true;
      }
      select.value = preset.id;
      select.dispatchEvent(new Event("change", {bubbles: true}));
      document.querySelector("#loadPreset").focus();
    }

    function favorite(preset, control) {
      if (favorites.has(preset.id)) favorites.delete(preset.id);
      else favorites.add(preset.id);
      try {
        localStorage.setItem(storageKey, JSON.stringify([...favorites]));
      } catch {
        status.textContent = "ブラウザーに保存できないため、再読込するとお気に入りが消えます。";
      }

      if (onlyFavorites.checked && !favorites.has(preset.id)) {
        renderCatalog();
        search.focus();
        return;
      }
      markFavorite(preset, control);
    }

    function markFavorite(preset, control) {
      control.setAttribute("aria-pressed", String(favorites.has(preset.id)));
      control.setAttribute("aria-label", "お気に入り：" + presetName(preset));
    }

    function renderSelection() {
      find("#comparisonCount").textContent = "ひな型 " + selected.size + " / " + maxPresets + " 件";
      runButton.disabled = busy || selected.size + Number(includeCurrent.checked) === 0;
      clearButton.disabled = busy || selected.size === 0;
      find("#comparisonSelection").replaceChildren(...[...selected].map((id) => node("li", id)));
      for (const box of catalog.querySelectorAll('input[type="checkbox"]')) {
        box.disabled = busy || (!box.checked && selected.size >= maxPresets);
      }
    }

    function renderCatalog() {
      const terms = normalize(search.value).trim().split(/\s+/).filter(Boolean);
      const presets = listPresets();
      const available = new Set(presets.map((preset) => preset.id));
      for (const id of selected) if (!available.has(id)) selected.delete(id);

      const matches = presets.filter((preset) => {
        if (onlyFavorites.checked && !favorites.has(preset.id)) return false;
        const haystack = normalize([preset.id, presetName(preset), preset.spec.description].join(" "));
        return terms.every((term) => haystack.includes(term));
      });

      find("#comparisonMatches").textContent = matches.length > 30
        ? matches.length + "件中、先頭30件を表示しています。検索で絞り込めます。"
        : matches.length + "件";
      catalog.replaceChildren();

      for (const preset of matches.slice(0, 30)) {
        const item = node("li");
        const label = node("label");
        const box = node("input");
        box.type = "checkbox";
        box.value = preset.id;
        box.checked = selected.has(preset.id);
        box.addEventListener("change", () => {
          if (box.checked) selected.add(preset.id);
          else selected.delete(preset.id);
          renderSelection();
        });

        const description = node("span");
        const name = node("strong", presetName(preset));
        const scenario = node("span", presetScenario(preset) || "用途の記載なし");
        scenario.className = "comparison-scenario";
        description.append(name, node("small", preset.id), scenario);
        label.append(box, description);
        const actions = node("div");
        actions.className = "comparison-actions";
        const pin = button("お気に入り", () => favorite(preset, pin));
        markFavorite(preset, pin);
        actions.append(pin, button("編集画面で選ぶ", () => showInEditor(preset)));
        item.append(label, actions);
        catalog.append(item);
      }
      renderSelection();
    }

    function summaries(data) {
      const spec = data.validated_spec;
      if (data.writes !== false || !spec || !Array.isArray(data.records)) {
        throw new Error("プレビューの結果を確認できませんでした。");
      }
      const generator = spec.generator || spec;
      return {
        ...metrics(spec, data),
        "見本レコード数": data.records.length,
        "異常ルール適用サンプル数": (data.anomaly_hits || []).filter((hits) => hits.length).length,
        "生成項目数": generator.fields?.length ?? null,
      };
    }

    function renderReport() {
      const display = results.querySelector("tbody");
      const heading = results.querySelector("thead");
      const head = node("tr");
      const metricHeading = node("th", "比較する項目");
      metricHeading.scope = "col";
      head.append(metricHeading);
      for (const entry of report.entries) {
        const th = node("th", entry.label);
        th.scope = "col";
        if (entry.id) th.append(node("small", entry.id));
        head.append(th);
      }
      heading.replaceChildren(head);
      display.replaceChildren();
      const fields = [...new Set(["プレビュー", ...report.entries.flatMap((entry) =>
        Object.keys(entry.values || {}))])];
      let differing = 0;
      for (const field of fields) {
        const values = report.entries.map((entry) => field === "プレビュー"
          ? entry.status : entry.values?.[field] ?? null);
        const compared = field === "プレビュー" ? values : values.filter(
          (_value, index) => report.entries[index].status === "確認済み",
        );
        const changed = new Set(compared).size > 1;
        if (field !== "プレビュー" && changed) differing += 1;
        if (differences.checked && field !== "プレビュー" && !changed) continue;
        const row = node("tr");
        if (changed) row.className = "comparison-changed";
        const label = node("th", field);
        label.scope = "row";
        row.append(label, ...values.map((value) => node("td", value ?? "—")));
        display.append(row);
      }
      const reviewed = report.entries.filter((entry) => entry.status === "確認済み").length;
      find("#comparisonDelta").textContent = reviewed < 2
        ? "差分の表示には、確認済みの見本が2件以上必要です。"
        : "差がある項目 " + differing + " 件";
      results.hidden = false;
    }

    async function compare() {
      if (busy) return;
      const items = listPresets().filter((preset) => selected.has(preset.id));
      const queue = [];
      if (includeCurrent.checked) {
        try {
          queue.push({id: null, label: "編集中の設定", spec: currentSpec()});
        } catch {
          queue.push({id: null, label: "編集中の設定", spec: null});
        }
      }
      for (const preset of items) {
        queue.push({id: preset.id, label: presetName(preset), spec: preset.spec});
      }
      if (!queue.length) return;

      busy = true;
      stopRequested = false;
      renderSelection();
      includeCurrent.disabled = true;
      stopButton.hidden = false;
      results.hidden = true;
      const entries = [];
      try {
        for (const item of queue) {
          const entry = {id: item.id, label: item.label, status: "未実施"};
          entries.push(entry);
          if (stopRequested) continue;
          status.textContent = entries.length + " / " + queue.length + " 件目の見本を確認中";
          try {
            if (!item.spec) throw new Error("invalid-form");
            entry.values = summaries(await preview(item.spec));
            entry.status = "確認済み";
          } catch {
            entry.status = "要確認";
          }
        }
        report = {createdAt: new Date().toISOString(), entries};
        differences.checked = false;
        differences.disabled = entries.filter((entry) => entry.status === "確認済み").length < 2;
        renderReport();
        status.textContent = entries.filter((entry) => entry.status === "確認済み").length +
          " / " + queue.length + " 件の見本を確認しました。" +
          (stopRequested ? "残りの比較を中止しました。" : "");
      } finally {
        busy = false;
        includeCurrent.disabled = false;
        stopButton.disabled = false;
        stopButton.hidden = true;
        renderSelection();
      }
    }

    function download(extension) {
      if (!report || busy) return;
      // レポートには設定全体や接続情報、生成された本文、自由記述の名前は含めない。
      const data = {
        version: 1, application: app, checked_at: report.createdAt,
        cases: report.entries.map(({id, status, values}) =>
          ({preset_id: validId(id) ? id : null, status, metrics: values ?? {}})),
      };
      const content = extension === "json" ? JSON.stringify(data, null, 2) + "\n" : makeCSV(data);
      const type = extension === "json" ? "application/json" : "text/csv";
      const url = URL.createObjectURL(new Blob([content], {type: type + ";charset=utf-8"}));
      const link = node("a");
      link.href = url;
      link.download = app + "-comparison." + extension;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    }

    function makeCSV(data) {
      const rows = [["ひな型ID", "プレビュー", "比較する項目", "値"]];
      for (const entry of data.cases) {
        const id = entry.preset_id || "編集中の設定";
        rows.push([id, entry.status, "", ""]);
        for (const [metric, value] of Object.entries(entry.metrics)) {
          if (value !== null) rows.push([id, entry.status, metric, value]);
        }
      }
      return "\uFEFF" + rows.map((row) => row.map((cell) => {
        let value = String(cell);
        if (typeof cell === "string" && /^[\s\u0000-\u001f]*[=+\-@]/.test(value)) value = "'" + value;
        return '"' + value.replaceAll('"', '""') + '"';
      }).join(",")).join("\r\n") + "\r\n";
    }

    document.querySelector('.nav[data-tab="comparison"]').addEventListener("click", renderCatalog);
    search.addEventListener("input", renderCatalog);
    onlyFavorites.addEventListener("change", renderCatalog);
    includeCurrent.addEventListener("change", renderSelection);
    differences.addEventListener("change", renderReport);
    runButton.addEventListener("click", compare);
    clearButton.addEventListener("click", () => {
      selected.clear();
      renderCatalog();
      search.focus();
    });
    stopButton.addEventListener("click", () => {
      stopRequested = true;
      stopButton.disabled = true;
      status.textContent = "実行中の見本確認が終わり次第中止します。";
    });
    find("#comparisonJSON").addEventListener("click", () => download("json"));
    find("#comparisonCSV").addEventListener("click", () => download("csv"));
  },
};
