"use strict";

// --- Connection to the bridge program (yt-dlp) ---

const HOST = "ytdlp_bridge";
// Bridge version this extension expects (BRIDGE_VERSION in host/ytdlp_bridge.py). The extension updates
// itself, the bridge doesn't: when it is older, YDM's pages ask to run install.py again.
const BRIDGE_REQUIRED = 2;
let port = null;
let hostError = null;
let bridgeVersion = null; // null until the bridge has answered
let nextId = 1;
const pending = new Map(); // request id -> { resolve, reject }
const REPLY_TYPES = new Set(["check", "formats", "started", "ok", "history", "settings", "error"]);

function getPort() {
  if (port) return port;
  port = browser.runtime.connectNative(HOST);
  hostError = null;
  port.onMessage.addListener(onHostMessage);
  port.onDisconnect.addListener((p) => {
    hostError = (p.error && p.error.message) || "bridge stopped";
    port = null;
    for (const { reject } of pending.values()) reject(new Error(hostError));
    pending.clear();
    changed();
  });
  // As soon as we connect: fetch the history (it lives in the bridge, not in Firefox).
  const id = nextId++;
  pending.set(id, {
    resolve: (msg) => {
      bridgeVersion = msg.bridge ?? 1; // bridges older than this announcement say nothing
      changed();
    },
    reject: () => {},
  });
  port.postMessage({ id, type: "history" });
  return port;
}

function request(type, payload = {}) {
  return new Promise((resolve, reject) => {
    const id = nextId++;
    pending.set(id, { resolve, reject });
    try {
      getPort().postMessage({ id, type, ...payload });
    } catch (e) {
      pending.delete(id);
      hostError = String(e.message || e);
      reject(new Error(hostError));
    }
  });
}

/** Reply for the extension's pages when a request failed: the bridge's text and code. */
function failure(e) {
  return { error: e.message, code: e.code };
}

function onHostMessage(msg) {
  if (msg.type === "entry") {
    entries.set(msg.entry.id, msg.entry);
    changed();
    return;
  }
  if (msg.type === "history") {
    entries.clear();
    for (const e of msg.entries) entries.set(e.id, e);
    changed();
  }
  if (msg.type === "started") {
    entries.set(msg.entry.id, msg.entry);
    changed();
  }
  if (!REPLY_TYPES.has(msg.type)) return;
  const p = pending.get(msg.id);
  if (!p) return;
  pending.delete(msg.id);
  if (msg.type === "error") {
    const err = new Error(msg.error);
    err.code = msg.code;
    p.reject(err);
  } else {
    p.resolve(msg);
  }
}

// --- History and downloads (a copy of what the bridge says) ---

const entries = new Map(); // id -> entry

let changeTimer = null;
function changed() {
  // Tells the open pages (popup, Downloads page); batched so they aren't flooded.
  if (changeTimer) return;
  changeTimer = setTimeout(() => {
    changeTimer = null;
    browser.runtime.sendMessage({ type: "changed" }).catch(() => {});
    updateActiveBadge();
  }, 150);
}

function sortedEntries() {
  return [...entries.values()].sort((a, b) => (b.created || 0) - (a.created || 0));
}

// --- Recognizing the sites yt-dlp supports ---

const checkCache = new Map(); // url -> extractor name or null
const formatsCache = new Map(); // url -> { at, promise }
const FORMATS_TTL = 10 * 60 * 1000;

function isHttp(url) {
  return typeof url === "string" && /^https?:\/\//i.test(url);
}

async function checkUrl(url) {
  if (!isHttp(url)) return null;
  if (checkCache.has(url)) return checkCache.get(url);
  let extractor = null;
  try {
    extractor = (await request("check", { url })).extractor;
  } catch {
    return null;
  }
  if (checkCache.size > 500) checkCache.delete(checkCache.keys().next().value);
  checkCache.set(url, extractor);
  return extractor;
}

function getFormats(url, referer) {
  const cached = formatsCache.get(url);
  if (cached && Date.now() - cached.at < FORMATS_TTL) return cached.promise;
  const payload = { url };
  if (isHttp(referer) && referer !== url) payload.referer = referer;
  const promise = request("formats", payload);
  formatsCache.set(url, { at: Date.now(), promise });
  promise.then((r) => r.error && formatsCache.delete(url), () => formatsCache.delete(url));
  if (formatsCache.size > 50) formatsCache.delete(formatsCache.keys().next().value);
  return promise;
}

// The quality list is prepared as soon as you linger on a recognized page, so the popup opens instantly.
// Cost: one yt-dlp analysis per video page viewed in the active tab. Set to 0 to turn it off.
// Never in private browsing: the site gets nothing more than the visit itself.
const PREFETCH_DELAY = 1500;

function prefetchFormats(tabId, url) {
  if (!PREFETCH_DELAY) return;
  setTimeout(async () => {
    const tab = await browser.tabs.get(tabId).catch(() => null);
    const s = tabs.get(tabId);
    if (tab?.active && !tab.incognito && s?.url === url && s.extractor) getFormats(url).catch(() => {});
  }, PREFETCH_DELAY);
}

// --- Per-tab state ---

const tabs = new Map(); // tabId -> { url, extractor, media: Map(url -> {url, kind, size}) }

function tabState(tabId) {
  let s = tabs.get(tabId);
  if (!s) {
    s = { url: null, extractor: null, media: new Map() };
    tabs.set(tabId, s);
  }
  return s;
}

function updateBadge(tabId) {
  const s = tabs.get(tabId);
  const count = s ? (s.extractor ? 1 : 0) + s.media.size : 0;
  browser.browserAction.setBadgeText({ tabId, text: count ? String(count) : "" });
  browser.browserAction.setBadgeBackgroundColor({ tabId, color: "#188038" });
  browser.browserAction.setBadgeTextColor({ tabId, color: "#ffffff" });
}

function updateActiveBadge() {
  const all = sortedEntries();
  const active = all.filter((e) => e.status === "downloading").length;
  const queued = all.filter((e) => e.status === "queued").length;
  const parts = [];
  if (active) parts.push(tn("toolbarActive", active));
  if (queued) parts.push(t("toolbarQueued", { n: queued }));
  browser.browserAction.setTitle({ title: parts.length ? "YDM — " + parts.join(", ") : "YDM" });
}

// Brief feedback on the icon (keyboard shortcut), then back to the count of detected videos.
function flashBadge(tabId, text, color) {
  browser.browserAction.setBadgeText({ tabId, text });
  browser.browserAction.setBadgeBackgroundColor({ tabId, color });
  setTimeout(() => updateBadge(tabId), 2000);
}

async function onTabUrl(tabId, url) {
  const s = tabState(tabId);
  s.url = url;
  s.extractor = null;
  updateBadge(tabId);
  const extractor = await checkUrl(url);
  if (tabState(tabId).url !== url) return; // the tab moved to another page meanwhile
  s.extractor = extractor;
  updateBadge(tabId);
  changed();
  if (extractor) prefetchFormats(tabId, url);
}

browser.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (tab.incognito) privateUsed = true;
  if (changeInfo.url) onTabUrl(tabId, changeInfo.url);
});
browser.tabs.onRemoved.addListener((tabId) => tabs.delete(tabId));
browser.tabs.onActivated.addListener(({ tabId }) => {
  const s = tabs.get(tabId);
  if (s?.extractor) prefetchFormats(tabId, s.url);
});

// A new page is loading: forget the previous page's streams.
browser.webRequest.onBeforeRequest.addListener(
  (d) => {
    if (d.tabId >= 0) tabState(d.tabId).media.clear();
  },
  { urls: ["<all_urls>"], types: ["main_frame"] }
);

// --- Detecting video streams (like XDM / Video DownloadHelper) ---

const MIN_DIRECT_SIZE = 1024 * 1024; // ignores small files (ads, previews)
const IGNORED_HOSTS = /(^|\.)googlevideo\.com$/; // chunks of a page yt-dlp already handles: go through the page

function header(headers, name) {
  const h = headers.find((x) => x.name.toLowerCase() === name);
  return h ? h.value.toLowerCase() : "";
}

function mediaKind(url, contentType) {
  let path;
  try {
    path = new URL(url).pathname.toLowerCase();
  } catch {
    return null;
  }
  if (contentType.includes("mpegurl") || path.endsWith(".m3u8")) return "HLS";
  if (contentType.includes("dash+xml") || path.endsWith(".mpd")) return "DASH";
  if (contentType.includes("mp2t") || contentType.includes("iso.segment")) return null; // segments
  const ext = path.match(/\.(mp4|webm|mkv|mov|m4v|flv)$/);
  if (contentType.startsWith("video/") || ext) return "File";
  return null;
}

function dirOf(url) {
  const u = new URL(url);
  return u.origin + u.pathname.slice(0, u.pathname.lastIndexOf("/") + 1);
}

function totalSize(headers) {
  const range = header(headers, "content-range").match(/\/(\d+)$/);
  if (range) return Number(range[1]);
  return Number(header(headers, "content-length")) || 0;
}

browser.webRequest.onHeadersReceived.addListener(
  (d) => {
    if (d.tabId < 0 || d.statusCode >= 400) return;
    let host;
    try {
      host = new URL(d.url).hostname;
    } catch {
      return;
    }
    if (IGNORED_HOSTS.test(host)) return;
    const kind = mediaKind(d.url, header(d.responseHeaders, "content-type"));
    if (!kind) return;
    // For HLS/DASH, the size received is the playlist's, not the video's: don't show it.
    const size = kind === "File" ? totalSize(d.responseHeaders) : 0;
    if (kind === "File" && size && size < MIN_DIRECT_SIZE) return;
    const s = tabState(d.tabId);
    if (s.media.has(d.url) || s.media.size >= 20) return;
    // The variants (one per quality) of a stream already detected sit under its folder: one line is enough.
    if (kind !== "File") {
      for (const m of s.media.values()) if (m.kind === kind && d.url.startsWith(dirOf(m.url))) return;
    }
    s.media.set(d.url, { url: d.url, kind, size });
    updateBadge(d.tabId);
    changed();
  },
  { urls: ["<all_urls>"], types: ["media", "xmlhttprequest", "object", "other"] },
  ["responseHeaders"]
);

// --- Messages from the extension's pages (popup, Downloads page) ---

const ENTRY_ACTIONS = new Set(["cancel", "resume", "remove"]);

browser.runtime.onMessage.addListener((msg, sender) => {
  if (sender.id !== browser.runtime.id || !sender.url?.startsWith(browser.runtime.getURL(""))) return;
  switch (msg.type) {
    case "getState": {
      try {
        getPort();
      } catch (e) {
        hostError = String(e.message || e);
      }
      const s = msg.tabId != null ? tabs.get(msg.tabId) : null;
      return Promise.resolve({
        url: s?.url ?? null,
        extractor: s?.extractor ?? null,
        media: s ? [...s.media.values()] : [],
        // Private downloads only show up in private windows.
        entries: sortedEntries().filter((e) => msg.incognito === true || !e.private),
        hostError,
        bridgeOutdated: bridgeVersion !== null && bridgeVersion < BRIDGE_REQUIRED,
      });
    }
    case "formats":
      if (!isHttp(msg.url)) return;
      return getFormats(msg.url, msg.referer).catch(failure);
    case "download": {
      if (!isHttp(msg.url) || !["video", "audio"].includes(msg.mode)) return;
      const payload = { url: msg.url, mode: msg.mode };
      if (isHttp(msg.referer) && msg.referer !== msg.url) payload.referer = msg.referer;
      if (Number.isInteger(msg.height)) payload.height = msg.height;
      if (typeof msg.title === "string") payload.title = msg.title.slice(0, 300);
      if (typeof msg.label === "string") payload.label = msg.label.slice(0, 40);
      if (msg.pageTitle === true) payload.pageTitle = true;
      if (msg.private === true) payload.private = true;
      return request("download", payload).then(() => ({ ok: true }), failure);
    }
    case "open":
      return request("open", { entry: msg.entry, what: msg.what }).then(() => ({ ok: true }), failure);
    case "clear":
      return request("clear").then(() => ({ ok: true }), failure);
    case "openPage":
      if (!isHttp(msg.url)) return;
      return browser.tabs.create({ url: msg.url }).then(() => ({ ok: true }));
    case "settings":
    case "pickFolder":
    case "resetFolder":
    case "update":
      return request(msg.type).catch(failure);
    case "openDownloads": {
      const page = msg.section === "reglages" ? "downloads.html#reglages" : "downloads.html";
      return browser.tabs.create({ url: browser.runtime.getURL(page) }).then(() => ({ ok: true }));
    }
    default:
      if (ENTRY_ACTIONS.has(msg.type) && typeof msg.entry === "string") {
        return request(msg.type, { entry: msg.entry }).then(() => ({ ok: true }), failure);
      }
  }
});

// --- Right click: download a link, a video or the page ---

const MENU_ID = "ytdlp-download";

browser.menus.create({
  id: MENU_ID,
  title: t("menuDownload"),
  contexts: ["link", "video", "audio", "page"],
});

browser.menus.onClicked.addListener((info, tab) => {
  if (info.menuItemId !== MENU_ID) return;
  // A "blob:" video can't be downloaded directly: give the page to yt-dlp.
  const url = [info.linkUrl, info.srcUrl, info.pageUrl].find(isHttp);
  if (!url) return;
  const payload = { url, mode: "video" };
  if (url !== info.linkUrl && tab?.title) payload.title = tab.title.slice(0, 300);
  // Direct video file: its original name is often unreadable, so use the page title.
  if (url === info.srcUrl && payload.title) payload.pageTitle = true;
  if (isHttp(info.pageUrl) && info.pageUrl !== url) payload.referer = info.pageUrl;
  if (tab?.incognito) payload.private = true;
  request("download", payload).catch(() => {});
});

// --- Keyboard shortcut (Alt+Shift+D by default): the tab's video, in the best quality ---

browser.commands.onCommand.addListener(async (command) => {
  if (command !== "download-tab") return;
  const [tab] = await browser.tabs.query({ active: true, currentWindow: true });
  if (!tab || !isHttp(tab.url)) return;
  const s = tabs.get(tab.id);
  const payload = { url: tab.url, mode: "video" };
  if (tab.incognito) payload.private = true;
  // Page unknown to yt-dlp but streams detected: the largest file, else the first stream,
  // named after the page as in the popup.
  if (!s?.extractor && s?.media.size) {
    const media = [...s.media.values()];
    const best = media.filter((m) => m.kind === "File").sort((a, b) => b.size - a.size)[0] || media[0];
    payload.url = best.url;
    payload.referer = tab.url;
    if (tab.title) {
      payload.title = tab.title.slice(0, 300);
      payload.pageTitle = true;
    }
  }
  try {
    await request("download", payload);
    flashBadge(tab.id, "✓", "#188038");
  } catch {
    flashBadge(tab.id, "!", "#d93025");
  }
});

// --- Private browsing: forgotten when the last private window closes, as in Firefox ---

let privateUsed = true; // at startup, any previous private session is over

async function forgetPrivateIfOver() {
  if (!privateUsed) return;
  const windows = await browser.windows.getAll();
  if (windows.some((w) => w.incognito)) return;
  // No address from the private session stays in memory.
  checkCache.clear();
  formatsCache.clear();
  request("forgetPrivate").then(() => (privateUsed = false), () => {});
}

browser.windows.onRemoved.addListener(forgetPrivateIfOver);

// --- Interface language (menu and toolbar tooltip) ---

function applyLanguage() {
  browser.menus.update(MENU_ID, { title: t("menuDownload") });
  updateActiveBadge();
}

I18N_READY.then(applyLanguage);
browser.storage.onChanged.addListener((changes, area) => {
  if (area === "local" && changes.lang) loadLang().then(applyLanguage);
});

// --- Startup ---

try {
  getPort();
} catch (e) {
  hostError = String(e.message || e);
}
forgetPrivateIfOver();
browser.tabs.query({}).then((all) => {
  for (const tab of all) if (tab.url) onTabUrl(tab.id, tab.url);
});
