"use strict";

const $ = (id) => document.getElementById(id);
let entries = [];
let filter = "all";
let query = "";

const FILTERS = {
  all: () => true,
  downloading: isPending,
  done: (e) => e.status === "done",
  problem: (e) => e.status === "failed" || e.status === "cancelled",
};

function matches(e) {
  if (!query) return true;
  const hay = [e.title, e.file, e.url, e.referer, e.label].filter(Boolean).join(" ").toLowerCase();
  return hay.includes(query);
}

function render() {
  for (const [name, test] of Object.entries(FILTERS)) {
    const n = entries.filter(test).length;
    document.querySelector(`[data-count="${name}"]`).textContent = n ? String(n) : "";
  }
  const active = entries.filter((e) => e.status === "downloading").length;
  const queued = entries.filter((e) => e.status === "queued").length;
  const total = entries.filter(FILTERS.done).reduce((sum, e) => sum + (e.size || 0), 0);
  $("summary").textContent = [
    active ? t("summaryActive", { n: active }) : null,
    queued ? t("summaryQueued", { n: queued }) : null,
    total ? t("summaryTotal", { size: formatSize(total) }) : null,
  ]
    .filter(Boolean)
    .join(" · ");

  const shown = entries.filter(FILTERS[filter]).filter(matches);
  syncEntryList($("list"), shown, (action, e) => runAction(action, e, showError), { full: true });

  $("empty").hidden = shown.length > 0;
  if (!shown.length) {
    const text = entries.length === 0 ? t("emptyNone") : t("emptyFilter");
    $("empty").replaceChildren(icon(entries.length ? "search" : "download"), el("p", { text }));
  }
  $("clear").disabled = !entries.some((e) => !isPending(e));
}

async function refresh() {
  const state = await browser.runtime.sendMessage({ type: "getState", incognito: browser.extension.inIncognitoContext });
  entries = state.entries;
  showError(bridgeProblem(state));
  render();
}

// Filters
document.querySelectorAll(".segmented button").forEach((b) =>
  b.addEventListener("click", () => {
    filter = b.dataset.filter;
    document.querySelectorAll(".segmented button").forEach((x) => x.setAttribute("aria-selected", String(x === b)));
    render();
  })
);

// Search
$("search-icon").replaceWith(icon("search"));
$("search").addEventListener("input", (ev) => {
  query = ev.target.value.trim().toLowerCase();
  render();
});

// Clear the history: two clicks (the first asks for confirmation), no dialog box
let confirmTimer = null;
$("clear").addEventListener("click", async () => {
  const btn = $("clear");
  if (!confirmTimer) {
    btn.textContent = t("confirm");
    confirmTimer = setTimeout(() => {
      confirmTimer = null;
      btn.textContent = t("clearHistory");
    }, 3000);
    return;
  }
  clearTimeout(confirmTimer);
  confirmTimer = null;
  btn.textContent = t("clearHistory");
  const res = await browser.runtime.sendMessage({ type: "clear" });
  if (res && res.error) showError(errorText(res));
});

// Download folder: picked in a system window, on the bridge's side (no path ever comes from here)
$("folder-icon").replaceWith(icon("folder"));
$("engine-icon").replaceWith(icon("retry"));
$("language-icon").replaceWith(icon("globe"));

function renderSettings(s) {
  if (!s) return;
  if (s.error) {
    showError(errorText(s));
    return;
  }
  $("download-dir").textContent = s.download_dir;
  $("download-dir").title = s.download_dir;
  $("reset-folder").hidden = s.is_default;
  if (s.ytdlp) renderEngine(s.ytdlp);
}

function renderEngine(y) {
  const parts = [
    y.version ? t("engineVersion", { v: y.version }) : t("engineUnknown"),
    y.checked ? t("engineChecked", { when: timeAgo(y.checked) }) : t("engineNeverChecked"),
  ];
  if (y.error) parts.push(t("engineCheckFailed"));
  if (!y.fast) parts.push(t("engineNoAccel"));
  $("engine-info").textContent = parts.join(" · ");
  $("engine-info").title = y.error || "";
}

$("pick-folder").addEventListener("click", async () => {
  const btn = $("pick-folder");
  btn.disabled = true;
  btn.textContent = t("chooseInWindow");
  try {
    renderSettings(await browser.runtime.sendMessage({ type: "pickFolder" }));
  } finally {
    btn.disabled = false;
    btn.textContent = t("choose");
  }
});

$("reset-folder").addEventListener("click", async () => {
  renderSettings(await browser.runtime.sendMessage({ type: "resetFolder" }));
});

$("update-engine").addEventListener("click", async () => {
  const btn = $("update-engine");
  btn.disabled = true;
  btn.textContent = t("updating");
  try {
    renderSettings(await browser.runtime.sendMessage({ type: "update" }));
  } finally {
    btn.disabled = false;
    btn.textContent = t("update");
  }
});

// Language: saved in Firefox; every open YDM page reloads in the new language.
$("language").addEventListener("change", (ev) => {
  browser.storage.local.set({ lang: ev.target.value });
});
browser.storage.onChanged.addListener((changes, area) => {
  if (area === "local" && changes.lang) location.reload();
});

browser.runtime.onMessage.addListener((msg) => {
  if (msg.type === "changed") refresh();
});

I18N_READY.then(() => {
  localizePage();
  $("language").value = langChoice;
  refresh();
  browser.runtime.sendMessage({ type: "settings" }).then((s) => {
    renderSettings(s);
    if (location.hash === "#reglages") $("reglages").scrollIntoView();
  });
});
// Keeps relative times ("3 min ago") accurate
setInterval(render, 30000);
