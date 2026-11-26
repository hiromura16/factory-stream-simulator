"use strict";

const capturePanel = document.querySelector("#capturePanel");
const captureList = document.querySelector("#captureList");
const captureStatus = document.querySelector("#captureStatus");
const captureDownload = document.querySelector("#captureDownload");
const captureLatest = document.querySelector("#captureLatest");
const capturePrevious = document.querySelector("#capturePrevious");
const captureNext = document.querySelector("#captureNext");
const capturePath = "/api/outbox/capture";
const pageSize = 25;
let pageBefore = null;
let previousPages = [];
let nextBefore = null;
let captureLoading = false;
let captureLoaded = false;

function captureQuery(before) {
  const params = new URLSearchParams({ limit: pageSize });
  if (before !== null) params.set("before", before);
  return "?" + params.toString();
}

function captureEntry(event) {
  const body = document.createElement("pre");
  body.textContent = "読み込み中…";
  const details = document.createElement("details");
  const summary = document.createElement("summary");
  summary.textContent = "本文を表示";
  details.append(summary, body);
  let fetched = false;
  let fetching = false;
  details.addEventListener("toggle", async () => {
    if (!details.open || fetching || fetched) return;
    fetching = true;
    body.textContent = "読み込み中…";
    try {
      const record = await api(capturePath + "/" + encodeURIComponent(event.id));
      body.textContent = record.payload;
      fetched = true;
    } catch (err) {
      body.textContent = "本文を取得できませんでした。閉じて開き直すと再試行します。";
    } finally {
      fetching = false;
    }
  });

  const item = document.createElement("li");
  const topic = document.createElement("strong");
  topic.textContent = event.topic;
  const meta = document.createElement("small");
  const date = new Date(event.created_at);
  const when = Number.isNaN(date.valueOf()) ? event.created_at : date.toLocaleString("ja-JP");
  meta.textContent = when + " · " + event.bytes + " B · " + event.profile_id;
  const key = document.createElement("code");
  key.textContent = event.record_key;
  item.append(topic, meta, key, details);
  return item;
}

async function loadCapturePage(before, history) {
  if (captureLoading) return;
  captureLoading = true;
  captureLatest.disabled = capturePrevious.disabled = captureNext.disabled = true;
  captureStatus.textContent = "記録を取得しています…";
  try {
    const result = await api(capturePath + captureQuery(before));
    captureList.replaceChildren(...result.events.map(captureEntry));
    pageBefore = before;
    previousPages = history;
    nextBefore = result.next_before;
    captureLoaded = true;
    captureStatus.textContent = result.events.length
      ? result.events.length + "件を表示しています。"
      : "ローカル記録がありません。接続先を「ローカル記録」にして少量のイベントを送信すると、ここで確認できます。";
    captureDownload.hidden = !result.events.length;
    if (result.events.length) {
      // The first displayed ID fixes the newest row even if new messages arrive.
      const pageUpperBound = result.events[0].id + 1;
      captureDownload.href = capturePath + "/download" + captureQuery(pageUpperBound);
    } else {
      captureDownload.removeAttribute("href");
    }
  } catch (err) {
    captureStatus.textContent = "記録を取得できませんでした。" + err.message;
  } finally {
    captureLoading = false;
    captureLatest.disabled = false;
    capturePrevious.disabled = !previousPages.length;
    captureNext.disabled = nextBefore === null;
  }
}

capturePanel.addEventListener("toggle", () => {
  if (capturePanel.open && !captureLoaded) loadCapturePage(null, []);
});
captureLatest.addEventListener("click", () => loadCapturePage(null, []));
capturePrevious.addEventListener("click", () => {
  if (previousPages.length)
    loadCapturePage(previousPages.at(-1), previousPages.slice(0, -1));
});
captureNext.addEventListener("click", () => {
  if (nextBefore !== null)
    loadCapturePage(nextBefore, [...previousPages, pageBefore]);
});
