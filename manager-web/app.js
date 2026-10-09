"use strict";
let session,
  busy = false,
  offset = 0,
  latest = 0,
  activeEntry = null,
  dragPayload = null;
const known = new Map();
const $ = (id) => document.getElementById(id);
function el(tag, text, cls) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (cls) node.className = cls;
  return node;
}
function notify(text, error = false) {
  const box = $("notice");
  box.textContent = text;
  box.classList.toggle("error", error);
  box.hidden = false;
}
async function api(path, data, bytes) {
  const options = {};
  if (data !== undefined || bytes) {
    options.method = "POST";
    options.headers = {
      "X-Local-Token": session.token,
      "Content-Type": bytes ? "application/octet-stream" : "application/json",
    };
    options.body = bytes || JSON.stringify(data);
  }
  const response = await fetch(path, options);
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "操作失敗");
  return result;
}
function choose(title, text, label) {
  return new Promise((resolve) => {
    const dialog = $("confirm");
    $("confirm-title").textContent = title;
    $("confirm-text").textContent = text;
    $("confirm-action").textContent = label;
    const finish = (value) => {
      dialog.close();
      $("confirm-action").onclick = null;
      $("cancel-action").onclick = null;
      dialog.oncancel = null;
      resolve(value);
    };
    $("confirm-action").onclick = () => finish(true);
    $("cancel-action").onclick = () => finish(false);
    dialog.oncancel = (event) => {
      event.preventDefault();
      finish(false);
    };
    dialog.showModal();
  });
}
async function operation(callback) {
  if (busy) {
    notify("正在完成上一筆操作，請稍候。");
    return;
  }
  busy = true;
  document.body.setAttribute("aria-busy", "true");
  try {
    await callback();
    await refresh();
  } catch (error) {
    notify(error.message, true);
  } finally {
    busy = false;
    document.body.removeAttribute("aria-busy");
  }
}
function actionButton(text, fn) {
  const button = el("button", text);
  button.type = "button";
  button.onclick = fn;
  return button;
}
function card(record, from = "collection") {
  known.set(record.id, record);
  const node = el("article", undefined, "skill");
  node.draggable = true;
  node.dataset.id = record.id;
  node.dataset.from = from;
  node.append(
    el("h3", record.name),
    el("p", record.summary || record.description),
  );
  const tags = el("div", undefined, "tags");
  tags.append(el("span", record.category_label || "待分類", "tag"));
  if (record.approval === "pending")
    tags.append(el("span", "新下載・待審", "tag pending"));
  if (record.status === "quarantined")
    tags.append(el("span", "需修整，暫不可啟用", "tag quarantine"));
  if (record.imported)
    tags.append(el("span", record.source?.label || "匯入", "tag"));
  node.append(tags);
  const buttons = el("div", undefined, "card-actions");
  buttons.append(actionButton("檢視原文", () => detail(record.id)));
  if (from === "collection" || from === "archive") {
    if (record.archived)
      buttons.append(
        actionButton("還原收藏", () =>
          move(record.id, "collection", "archive"),
        ),
      );
    else if (record.status !== "quarantined") {
      buttons.append(
        actionButton("啟用 Codex", () =>
          move(record.id, "Codex", "collection"),
        ),
        actionButton("啟用 OpenCode", () =>
          move(record.id, "OpenCode", "collection"),
        ),
      );
    }
  } else
    buttons.append(
      actionButton("停止啟用", () => move(record.id, "collection", from)),
    );
  node.append(buttons);
  node.addEventListener("dragstart", (event) => {
    dragPayload = { id: record.id, from };
    event.dataTransfer.setData(
      "application/x-nas-skill",
      JSON.stringify(dragPayload),
    );
    event.dataTransfer.setData("text/plain", record.id);
    event.dataTransfer.effectAllowed = "copyMove";
    node.classList.add("dragging");
  });
  node.addEventListener("dragend", () => {
    dragPayload = null;
    node.classList.remove("dragging");
    document
      .querySelectorAll(".drag-over")
      .forEach((item) => item.classList.remove("drag-over"));
  });
  return node;
}
async function library(append = false) {
  const ticket = ++latest;
  if (!append) offset = 0;
  const params = new URLSearchParams({
    query: $("query").value,
    mode: $("mode").value,
    category: $("category").value,
    offset: String(offset),
    limit: "30",
  });
  const result = await api("/api/library?" + params);
  if (ticket !== latest) return;
  if (!append) $("collection-list").replaceChildren();
  for (const record of result.records)
    $("collection-list").append(
      card(record, record.archived ? "archive" : "collection"),
    );
  offset += result.records.length;
  $("count").textContent = result.total + " 個版本";
  $("more").hidden = offset >= result.total;
  if (offset === 0)
    $("collection-list").append(el("p", "沒有符合條件的技能。", "empty"));
  bookmarks(result.bookmarks);
}
function bookmarks(values) {
  $("bookmark-count").textContent = values.length;
  $("bookmarks").replaceChildren();
  for (const item of values) {
    const row = el("div", undefined, "bookmark-row");
    const link = el("a", item.label + " · " + item.url);
    link.href = item.url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    row.append(
      link,
      actionButton("下載到待審", () => importGithub(item.url)),
    );
    $("bookmarks").append(row);
  }
  if (!values.length)
    $("bookmarks").append(
      el("p", "貼上 GitHub 連結後，可先收藏再下載。", "empty"),
    );
}
async function bindings() {
  const values = await api("/api/bindings");
  for (const client of ["Codex", "OpenCode"]) {
    const target = $(client + "-list");
    target.replaceChildren();
    $(client === "Codex" ? "codex-count" : "opencode-count").textContent =
      values[client].length;
    for (const item of values[client]) target.append(card(item.record, client));
    if (!values[client].length)
      target.append(el("p", "尚未從此介面啟用技能。", "empty"));
  }
}
async function refresh() {
  await Promise.all([library(), bindings()]);
}
async function detail(id) {
  try {
    const data = await api("/api/entry?id=" + encodeURIComponent(id));
    activeEntry = data;
    const record = data.record;
    known.set(id, record);
    $("detail-title").textContent = record.name;
    $("entry-path").textContent = data.entrypoint;
    $("source-text").textContent =
      data.content + (data.truncated ? "\n…預覽已截斷，請讀完整原件。" : "");
    const meta = $("detail-meta");
    meta.replaceChildren();
    meta.append(el("p", record.description));
    const info = [
      ["來源", record.source?.url || "目前 NAS 盤點"],
      ["固定版本", record.source?.commit || record.package_sha256],
      [
        "授權",
        record.source?.license ||
          record.frontmatter?.license ||
          "請依原始來源確認",
      ],
      ["相依工具", record.dependencies.join("、") || "來源未列出"],
      [
        "狀態",
        record.approval === "pending"
          ? "新下載，尚未安裝"
          : "已收錄；實際工作流程仍需驗證",
      ],
    ];
    for (const [label, value] of info)
      meta.append(el("p", label + "：" + value));
    if (record.issues.length)
      meta.append(el("p", "待改善：" + record.issues.join("、")));
    const actions = $("detail-actions");
    actions.replaceChildren();
    if (record.archived)
      actions.append(
        actionButton("還原收藏", () => {
          $("detail").close();
          move(id, "collection", "archive");
        }),
      );
    else {
      actions.append(
        actionButton("啟用 Codex", () => {
          $("detail").close();
          move(id, "Codex", "collection");
        }),
        actionButton("啟用 OpenCode", () => {
          $("detail").close();
          move(id, "OpenCode", "collection");
        }),
        actionButton("移到回收筒", () => {
          $("detail").close();
          move(id, "archive", "collection");
        }),
      );
    }
    $("detail").showModal();
  } catch (error) {
    notify(error.message, true);
  }
}
async function move(id, target, from) {
  if (from === target) return;
  await operation(async () => {
    const record = known.get(id);
    if (!record) throw new Error("請重新整理後再操作");
    if (target === "Codex" || target === "OpenCode") {
      if (record.archived || record.status === "quarantined")
        throw new Error("請先還原收藏或修整這個技能。");
      let confirmed = false;
      if (record.approval === "pending") {
        const description = record.source?.url || "使用者 ZIP";
        confirmed = await choose(
          "安裝新下載的 Skill？",
          record.name +
            "\n來源：" +
            description +
            "\n版本：" +
            (record.source?.commit || record.package_sha256 || "請先檢視原文") +
            "\n將在這台 " +
            session.machine +
            " 的 " +
            target +
            " 建立 NAS 查找入口。下載的腳本不會在安裝時執行。",
          "確認安裝到 " + target,
        );
        if (!confirmed) return;
      }
      await api("/api/action", {
        action: "install",
        id,
        client: target,
        confirmed,
      });
      notify(
        "已啟用 " +
          record.name +
          "。請重新啟動 " +
          target +
          "，使它讀到新入口。",
      );
    } else if (target === "collection") {
      if (from === "archive" || record.archived) {
        await api("/api/action", { action: "restore", id });
        $("mode").value = "collection";
        notify("已還原 NAS 收藏。");
      } else if (from === "Codex" || from === "OpenCode") {
        await api("/api/action", { action: "uninstall", id, client: from });
        notify("已停止 " + from + " 的這個入口，保留可還原備份與 NAS 原件。");
      }
    } else if (target === "archive") {
      if (from !== "collection")
        throw new Error("請先拖回收藏區停止本機啟用，再移除 NAS 收藏。");
      if (
        !(await choose(
          "移除 NAS 收藏？",
          record.name +
            "\n此變更會影響各電腦的中央查找清單。封裝與歷史仍會保留，可從回收筒還原。",
          "移到回收筒",
        ))
      )
        return;
      await api("/api/action", { action: "archive", id });
      notify("已移到回收筒，原始封裝保留。");
    }
  });
}
async function importGithub(url) {
  await operation(async () => {
    notify("正在從 GitHub 下載並檢查技能包…");
    const result = await api("/api/import-github", { url });
    $("mode").value = "pending";
    $("query").value = "";
    notify(
      "已下載 " +
        result.records.length +
        " 個技能到待審區，尚未安裝。可先檢視原文，再拖到工具啟用。",
    );
  });
}
async function importZip(file) {
  if (!file) return;
  if (!file.name.toLowerCase().endsWith(".zip"))
    return notify("請選擇技能包 ZIP。", true);
  if (file.size > 64 * 1024 * 1024) return notify("ZIP 超過 64 MiB。", true);
  await operation(async () => {
    notify("正在檢查 ZIP 與保存技能包…");
    const result = await api(
      "/api/import-zip",
      undefined,
      await file.arrayBuffer(),
    );
    $("mode").value = "pending";
    $("query").value = "";
    notify("已匯入 " + result.records.length + " 個待審技能，尚未安裝。");
    $("zip-file").value = "";
  });
}
function wireDrop(zone) {
  zone.addEventListener("dragover", (event) => {
    if (
      dragPayload ||
      event.dataTransfer.types.includes("application/x-nas-skill")
    ) {
      event.preventDefault();
      event.dataTransfer.dropEffect =
        zone.dataset.target === "Codex" || zone.dataset.target === "OpenCode"
          ? "copy"
          : "move";
      zone.classList.add("drag-over");
    }
  });
  zone.addEventListener("dragleave", (event) => {
    if (!zone.contains(event.relatedTarget)) zone.classList.remove("drag-over");
  });
  zone.addEventListener("drop", (event) => {
    event.preventDefault();
    zone.classList.remove("drag-over");
    let payload = dragPayload;
    try {
      const text = event.dataTransfer.getData("application/x-nas-skill");
      if (text) payload = JSON.parse(text);
    } catch {
      notify("拖曳資料無效。", true);
      return;
    }
    if (payload?.id && payload.from)
      move(payload.id, zone.dataset.target, payload.from);
  });
}
async function gaps() {
  const result = await api("/api/gaps");
  const grid = el("div", undefined, "gaps-grid");
  for (const item of result.items || []) {
    const node = el("article", undefined, "gap-card");
    node.append(
      el("h3", item.topic),
      el("p", item.finding),
      el("p", item.status || "候選待審"),
    );
    if (item.url) {
      const link = el("a", "GitHub 來源");
      link.href = item.url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      node.append(
        link,
        actionButton("檢視待審", () => {
          $("mode").value = "imports";
          $("query").value = item.entry_name || item.topic;
          $("category").value = "";
          library()
            .then(() =>
              $("query").scrollIntoView({
                block: "center",
                behavior: "smooth",
              }),
            )
            .catch((error) => notify(error.message, true));
        }),
        actionButton("收藏連結", () =>
          operation(async () => {
            await api("/api/bookmark", { url: item.url });
            notify("已收藏連結。");
          }),
        ),
        actionButton("下載待審", () => importGithub(item.url)),
      );
    }
    grid.append(node);
  }
  $("gaps").replaceChildren(grid);
}
async function init() {
  try {
    session = await api("/api/status");
    $("machine").textContent =
      "此機：" +
      session.machine +
      (session.test_user_root ? " · 測試目錄" : "");
    $("library-location").textContent =
      session.library.replace(/^\\\\\?\\UNC\\/, "\\\\") +
      " · " +
      session.snapshot;
    for (const [value, label] of Object.entries(session.categories)) {
      $("category").append(new Option(label, value));
    }
    await Promise.all([refresh(), gaps()]);
  } catch (error) {
    notify(error.message, true);
  }
}
$("github-form").onsubmit = (event) => {
  event.preventDefault();
  importGithub($("github-url").value.trim());
};
$("bookmark").onclick = () =>
  operation(async () => {
    await api("/api/bookmark", { url: $("github-url").value.trim() });
    notify("已收藏連結，尚未下載或安裝。");
  });
$("zip-file").onchange = (event) => importZip(event.target.files[0]);
$("zip-drop").ondragover = (event) => {
  if (event.dataTransfer.types.includes("Files")) {
    event.preventDefault();
    $("zip-drop").classList.add("drag-over");
  }
};
$("zip-drop").ondragleave = () => $("zip-drop").classList.remove("drag-over");
$("zip-drop").ondrop = (event) => {
  event.preventDefault();
  $("zip-drop").classList.remove("drag-over");
  importZip(event.dataTransfer.files[0]);
};
$("refresh").onclick = () =>
  refresh().catch((error) => notify(error.message, true));
$("more").onclick = () =>
  library(true).catch((error) => notify(error.message, true));
let timer;
$("query").oninput = () => {
  clearTimeout(timer);
  timer = setTimeout(
    () => library().catch((error) => notify(error.message, true)),
    220,
  );
};
for (const id of ["mode", "category"])
  $(id).onchange = () =>
    library().catch((error) => notify(error.message, true));
$("show-archive").onclick = () => {
  $("mode").value = "archived";
  library().catch((error) => notify(error.message, true));
};
$("close-detail").onclick = () => $("detail").close();
$("copy-path").onclick = () =>
  navigator.clipboard
    .writeText(activeEntry.entrypoint)
    .then(() => notify("已複製原件路徑。"))
    .catch(() => notify("請選取上方路徑複製。"));
document.querySelectorAll("[data-target]").forEach(wireDrop);
init();
