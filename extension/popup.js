"use strict";

const $ = (id) => document.getElementById(id);
const VISIBLE_QUALITIES = 4;
const RECENT_DOWNLOADS = 4;

let tab = null;
let analyzed = false; // the user asked to analyze a page that wasn't recognized
const loadedSources = new Set(); // URLs whose qualities are shown / loading

// --- Qualities of a source (the page or a detected stream) ---

function skeleton(container) {
  container.replaceChildren(...[0, 1, 2].map(() => el("div", { class: "skeleton skeleton-row" })));
}

function qualityButton({ label, tag, size, iconName = "download", onClick, best }) {
  const go = el("span", { class: "q-go" }, icon(iconName));
  const btn = el(
    "button",
    { class: "quality" + (best ? " best" : "") },
    el("span", { class: "q-label", text: label }),
    tag ? el("span", { class: "q-tag", text: tag }) : null,
    el("span", { class: "q-size", text: size ? "~" + formatSize(size) : "" }),
    go
  );
  btn.addEventListener("click", async () => {
    if (btn.classList.contains("sent")) return;
    btn.classList.add("sent");
    go.replaceChildren(icon("check"));
    const res = await onClick();
    if (res && res.error) {
      showError(errorText(res));
      btn.classList.remove("sent");
      go.replaceChildren(icon(iconName));
    }
  });
  return btn;
}

function download(source, data, options) {
  // Detected stream: yt-dlp only knows the stream's technical name, so the file is named after the page.
  const isStream = Boolean(source.referer);
  return browser.runtime.sendMessage({
    type: "download",
    private: tab.incognito,
    url: source.url,
    referer: source.referer,
    title: (isStream ? tab.title : data?.title) || undefined,
    pageTitle: isStream && Boolean(tab.title),
    ...options,
  });
}

function renderQualities(container, source, data) {
  if (data.error) {
    container.replaceChildren(
      el("div", { class: "q-error", text: t("cannotListQualities", { error: data.error }) }),
      qualityButton({ label: t("tryAnyway"), size: null, onClick: () => download(source, null, { mode: "video" }) })
    );
    return;
  }
  const rows = data.qualities.map((q, i) =>
    qualityButton({
      label: q.label,
      tag: i === 0 ? t("best") : null,
      size: q.size,
      best: i === 0,
      onClick: () => download(source, data, { mode: "video", height: q.height, label: q.label }),
    })
  );
  if (rows.length === 0) {
    rows.push(qualityButton({ label: t("video"), tag: t("best"), best: true, onClick: () => download(source, data, { mode: "video" }) }));
  }
  const hidden = rows.slice(VISIBLE_QUALITIES);
  hidden.forEach((r) => (r.hidden = true));
  const children = [...rows];
  if (hidden.length) {
    const more = el("button", { class: "quality more" }, el("span", { text: tn("moreQualities", hidden.length) }), icon("chevron"));
    more.querySelector("svg").style.cssText = "width:14px;height:14px";
    more.addEventListener("click", () => {
      hidden.forEach((r) => (r.hidden = false));
      more.remove();
    });
    children.push(more);
  }
  if (data.audio) {
    children.push(
      qualityButton({
        label: t("audioOnly"),
        size: data.audio.size,
        iconName: "music",
        onClick: () => download(source, data, { mode: "audio", label: t("audio") }),
      })
    );
  }
  container.replaceChildren(...children);
}

async function loadQualities(container, source, onData) {
  skeleton(container);
  const data = await browser.runtime.sendMessage({ type: "formats", url: source.url, referer: source.referer });
  if (onData) onData(data);
  renderQualities(container, source, data);
}

// --- "This page" card ---

function loadPageCard() {
  const source = { url: tab.url };
  $("page-card").hidden = false;
  $("page-title").replaceChildren(el("div", { class: "skeleton skeleton-text", style: "width:90%" }), el("div", { class: "skeleton skeleton-text", style: "width:60%" }));
  $("page-thumb").replaceChildren(icon("film"));
  $("page-sub").textContent = hostOf(tab.url);
  loadQualities($("qualities"), source, (data) => {
    $("page-title").textContent = data.title || tab.title || hostOf(tab.url);
    if (data.thumbnail && data.thumbnail.startsWith("https://")) {
      $("page-thumb").replaceChildren(el("img", { src: data.thumbnail, alt: "", referrerpolicy: "no-referrer" }));
    }
    $("page-sub").textContent = [data.extractor || hostOf(tab.url), formatDuration(data.duration)].filter(Boolean).join(" · ");
  });
}

// --- Detected streams ---

function fileName(url) {
  try {
    const u = new URL(url);
    return decodeURIComponent(u.pathname.split("/").pop()) || u.hostname;
  } catch {
    return url;
  }
}

function renderStreams(media) {
  $("streams-card").hidden = media.length === 0;
  $("streams-count").textContent = media.length ? `(${media.length})` : "";
  const container = $("streams");
  for (const m of media) {
    if (loadedSources.has("stream:" + m.url)) continue;
    loadedSources.add("stream:" + m.url);
    const source = { url: m.url, referer: tab.url };
    const qualities = el("div", { class: "qualities", hidden: true });
    const toggle = iconButton("chevron", t("chooseQuality"), () => {
      qualities.hidden = !qualities.hidden;
      if (!qualities.hidden && !qualities.childElementCount) loadQualities(qualities, source);
    });
    const quick = iconButton("download", t("downloadBest"), async () => {
      quick.replaceChildren(icon("check"));
      const res = await download(source, null, { mode: "video" });
      if (res && res.error) showError(errorText(res));
    }, "accent");
    container.append(
      el(
        "div",
        { class: "stream" },
        el(
          "div",
          { class: "stream-head" },
          el("span", { class: "stream-kind", text: m.kind === "File" ? t("streamFile") : m.kind }),
          el("span", { class: "stream-name", text: fileName(m.url), title: m.url }),
          el("span", { class: "stream-size", text: formatSize(m.size) }),
          toggle,
          quick
        ),
        qualities
      )
    );
  }
}

// --- Recent downloads ---

function act(action, entry) {
  runAction(action, entry, showError);
}

function renderDownloads(entries) {
  const active = entries.filter(isPending);
  const recent = entries.filter((e) => !isPending(e)).slice(0, Math.max(0, RECENT_DOWNLOADS - active.length));
  const shown = [...active, ...recent];
  $("downloads-section").hidden = shown.length === 0;
  syncEntryList($("downloads"), shown, act);
}

// --- Whole popup ---

async function refresh() {
  const state = await browser.runtime.sendMessage({ type: "getState", tabId: tab.id, incognito: tab.incognito });
  showError(bridgeProblem(state));

  const isWeb = /^https?:/.test(tab.url || "");
  if ((state.extractor || analyzed) && isWeb && !loadedSources.has("page")) {
    loadedSources.add("page");
    loadPageCard();
  }
  renderStreams(state.media);
  $("nothing").hidden = !isWeb || loadedSources.has("page") || state.media.length > 0;
  renderDownloads(state.entries);
}

$("nothing-icon").replaceWith(icon("film"));
$("analyze").addEventListener("click", () => {
  analyzed = true;
  refresh();
});
$("open-downloads").addEventListener("click", () => {
  browser.runtime.sendMessage({ type: "openDownloads" });
  window.close();
});

browser.runtime.onMessage.addListener((msg) => {
  if (msg.type === "changed" && tab) refresh();
});

(async () => {
  await I18N_READY;
  localizePage();
  $("open-downloads").prepend(icon("history"));
  $("open-settings").replaceWith(
    iconButton("gear", t("settings"), () => {
      browser.runtime.sendMessage({ type: "openDownloads", section: "reglages" });
      window.close();
    })
  );
  // ?tab=<id> opens the popup in a tab, for tests.
  const forced = Number(new URLSearchParams(location.search).get("tab"));
  tab = forced ? await browser.tabs.get(forced) : (await browser.tabs.query({ active: true, currentWindow: true }))[0];
  refresh();
})();
