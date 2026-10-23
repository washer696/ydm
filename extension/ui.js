"use strict";

// Display code shared by the popup and the Downloads page.
// Any text coming from a web page or from the bridge is inserted with textContent, never as HTML.

const ICONS = {
  download: "M12 3v12m-5-5 5 5 5-5M5 21h14",
  close: "M18 6 6 18M6 6l12 12",
  play: "M8 5.5v13a.5.5 0 0 0 .77.42l10-6.5a.5.5 0 0 0 0-.84l-10-6.5A.5.5 0 0 0 8 5.5z",
  folder: "M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z",
  retry: "M3 12a9 9 0 0 1 15.5-6.3L21 8M21 3v5h-5M21 12a9 9 0 0 1-15.5 6.3L3 16M3 21v-5h5",
  trash: "M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3",
  film: "M4 4h16v16H4zM8 4v16M16 4v16M4 9h4M4 15h4M16 9h4M16 15h4",
  music: "M9 18V5l12-2v13M9 18a3 3 0 1 1-6 0 3 3 0 0 1 6 0zM21 16a3 3 0 1 1-6 0 3 3 0 0 1 6 0z",
  external: "M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5",
  copy: "M9 9h11v11H9zM5 15H4V4h11v1",
  alert: "M12 9v4M12 17h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z",
  history: "M12 7v5l3 2M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0z",
  search: "m21 21-4.3-4.3M11 18a7 7 0 1 1 0-14 7 7 0 0 1 0 14z",
  chevron: "m6 9 6 6 6-6",
  check: "M5 12.5 10 17l9-10",
  stream: "M2 12h3l3-8 4 16 3-8h7",
  gear: "M4 6h8M16 6h4M14 4v4M4 12h2M10 12h10M8 10v4M4 18h10M18 18h2M16 16v4",
  globe: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM3 12h18M12 3c2.5 2.5 3.8 5.6 3.8 9s-1.3 6.5-3.8 9c-2.5-2.5-3.8-5.6-3.8-9S9.5 5.5 12 3z",
};

function icon(name) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("fill", name === "play" ? "currentColor" : "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", name === "play" ? "0" : "2");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.setAttribute("aria-hidden", "true");
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", ICONS[name]);
  svg.append(path);
  return svg;
}

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (v == null || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? "" : v);
  }
  node.append(...children.filter((c) => c != null && c !== false));
  return node;
}

function iconButton(name, label, onClick, extraClass = "") {
  return el("button", { class: "icon-btn " + extraClass, title: label, "aria-label": label, onclick: onClick }, icon(name));
}

// --- Readable formats (in the interface language) ---

function formatNumber(value, digits) {
  return new Intl.NumberFormat(locale(), { maximumFractionDigits: digits }).format(value);
}

function formatSize(bytes) {
  if (!bytes) return "";
  const mb = bytes / (1024 * 1024);
  if (mb >= 1024) return formatNumber(mb / 1024, 1) + " " + t("unitGB");
  if (mb >= 10) return formatNumber(mb, 0) + " " + t("unitMB");
  if (mb >= 0.1) return formatNumber(mb, 1) + " " + t("unitMB");
  return formatNumber(bytes / 1024, 0) + " " + t("unitKB");
}

function formatSpeed(bps) {
  return bps ? formatSize(bps) + "/s" : "";
}

function formatDuration(seconds) {
  if (seconds == null || !isFinite(seconds)) return "";
  seconds = Math.round(seconds);
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}` : `${m}:${String(s).padStart(2, "0")}`;
}

function timeAgo(ts) {
  if (!ts) return "";
  const diff = Date.now() / 1000 - ts;
  if (diff < 60) return t("timeJustNow");
  if (diff < 3600) return t("timeMinutesAgo", { n: Math.floor(diff / 60) });
  const d = new Date(ts * 1000);
  const time = d.toLocaleTimeString(locale(), { hour: "2-digit", minute: "2-digit" });
  const today = new Date();
  const yesterday = new Date(today.getTime() - 86400000);
  if (d.toDateString() === today.toDateString()) return t("timeToday", { time });
  if (d.toDateString() === yesterday.toDateString()) return t("timeYesterday", { time });
  return d.toLocaleDateString(locale(), { day: "numeric", month: "short" }) + " " + time;
}

function hostOf(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

function entryTitle(e) {
  if (e.title) return e.title;
  if (e.file) return e.file.split(/[\\/]/).pop();
  return t("videoFrom", { host: hostOf(e.referer || e.url) });
}

// --- Download row (updated in place so it doesn't flicker) ---

// The project page, read from the extension's update address (works for forks too).
const PROJECT_URL = (() => {
  const update = browser.runtime.getManifest().browser_specific_settings?.gecko?.update_url || "";
  const [owner, repo] = update.split("/").slice(3, 5);
  return owner && repo ? `https://github.com/${owner}/${repo}` : "";
})();

/** Bridge problem to show in the banner, or null; with a link to the install steps when it helps. */
function bridgeProblem(state) {
  const help = (label) => (PROJECT_URL ? { url: PROJECT_URL + "#install", label } : null);
  if (state.hostError && /no such native application/i.test(state.hostError)) {
    return { text: t("bridgeMissing"), link: help(t("howToInstall")) };
  }
  if (state.hostError) return t("bridgeUnavailable", { error: state.hostError });
  if (state.bridgeOutdated) return { text: t("bridgeOutdated"), link: help(t("howToUpdate")) };
  return null;
}

/** Shows a message (text, or { text, link: { url, label } }) in the page's banner; null hides it. */
function showError(message) {
  const banner = document.getElementById("host-error");
  banner.hidden = !message;
  if (!message) return;
  const { text, link } = typeof message === "string" ? { text: message } : message;
  const parts = [icon("alert"), el("span", { text })];
  if (link) {
    parts.push(el("a", { href: link.url, text: link.label, onclick: (ev) => {
      ev.preventDefault();
      browser.tabs.create({ url: link.url });
    } }));
  }
  banner.replaceChildren(...parts);
}

/** Downloading or queued: neither finished nor waiting to be resumed. */
function isPending(e) {
  return e.status === "downloading" || e.status === "queued";
}

function createEntryRow(entry, act, { full = false } = {}) {
  const row = el("div", { class: "entry enter", "data-id": entry.id });
  row._full = full;
  row._act = act;
  row._thumb = el("div", { class: "thumb" });
  row._title = el("div", { class: "entry-title" });
  row._bar = el("span");
  row._progress = el("div", { class: "progress" }, row._bar);
  row._meta = el("div", { class: "entry-meta" });
  row._actions = el("div", { class: "entry-actions" });
  row.append(row._thumb, el("div", { class: "entry-body" }, row._title, row._progress, row._meta), row._actions);
  updateEntryRow(row, entry);
  requestAnimationFrame(() => requestAnimationFrame(() => row.classList.remove("enter")));
  return row;
}

function updateEntryRow(row, e) {
  const act = row._act;
  const full = row._full;
  const title = entryTitle(e);
  if (row._title.textContent !== title) {
    row._title.textContent = title;
    row._title.title = title;
  }

  // Thumbnail (remote image over https only) or icon
  const thumbKey = e.thumbnail && e.thumbnail.startsWith("https://") ? e.thumbnail : "icon:" + e.mode;
  if (row._thumbKey !== thumbKey) {
    row._thumbKey = thumbKey;
    row._thumb.replaceChildren(
      thumbKey.startsWith("icon:")
        ? icon(e.mode === "audio" ? "music" : "film")
        : el("img", { src: thumbKey, alt: "", referrerpolicy: "no-referrer", loading: "lazy" })
    );
  }

  // Progress
  const p = e.progress;
  const downloading = e.status === "downloading";
  row._progress.hidden = !downloading;
  if (downloading) {
    const known = p && p.percent != null;
    row._progress.classList.toggle("indeterminate", !known);
    row._bar.style.width = known ? p.percent + "%" : "";
  }

  // Info line
  const parts = [];
  const add = (text, cls) => text && parts.push(el("span", { class: cls, text }));
  if (downloading) {
    if (p && p.percent != null) add(formatNumber(p.percent, 1) + " %", "num");
    else add(t("preparing"));
    if (p) {
      add(formatSpeed(p.speed));
      if (p.eta != null) add(t("timeLeft", { time: formatDuration(p.eta) }));
      if (p.part === "audio" && e.mode !== "audio") add(t("audioTrack"));
    }
  } else if (e.status === "queued") {
    add(t("status_queued"));
    add(e.mode === "audio" ? t("audio") : e.label);
  } else if (e.status === "done") {
    add(t("status_done"), "status-done");
    add(formatSize(e.size));
    add(e.mode === "audio" ? t("audio") : e.label);
    add(timeAgo(e.finished));
  } else if (e.status === "failed") {
    add(t("status_failed"), "status-failed");
    add(e.error, "error");
  } else if (e.status === "cancelled") {
    add(t("status_cancelled"));
    add(t("canResume"));
  }
  if (!downloading && (full || e.status !== "done")) add(hostOf(e.referer || e.url));
  const pending = isPending(e);
  const meta = [];
  parts.forEach((node, i) => {
    if (i) meta.push(el("span", { class: "sep", text: "·" }));
    meta.push(node);
  });
  row._meta.replaceChildren(...meta);
  if (e.status === "failed") row._meta.title = e.error || "";

  // Buttons: rebuilt only when the status changes
  if (row._status !== e.status) {
    row._status = e.status;
    const buttons = [];
    if (downloading) {
      buttons.push(iconButton("close", t("cancelResumable"), () => act("cancel", e)));
    } else if (e.status === "queued") {
      buttons.push(iconButton("close", t("removeFromQueue"), () => act("cancel", e)));
    } else if (e.status === "done") {
      buttons.push(iconButton("play", t("openFile"), () => act("open-file", e), "accent"));
      buttons.push(iconButton("folder", t("showInFolder"), () => act("open-folder", e)));
    } else {
      buttons.push(iconButton("retry", e.status === "cancelled" ? t("resume") : t("retry"), () => act("resume", e), "accent"));
    }
    if (row._full) {
      buttons.push(iconButton("external", t("openSource"), () => act("source", e)));
      buttons.push(iconButton("copy", t("copyLink"), () => act("copy", e)));
    }
    if (!pending) {
      const label = e.status === "done" ? t("removeFromHistory") : t("removeAndDeletePartial");
      buttons.push(iconButton("trash", label, () => act("remove", e)));
    }
    row._actions.replaceChildren(...buttons);
  }
}

/** Syncs a list of rows with the entries, reusing the existing nodes. */
function syncEntryList(container, entries, act, options) {
  const existing = new Map([...container.children].filter((c) => c.dataset.id).map((c) => [c.dataset.id, c]));
  const rows = entries.map((e) => {
    const row = existing.get(e.id);
    existing.delete(e.id);
    if (row) {
      updateEntryRow(row, e);
      return row;
    }
    return createEntryRow(e, act, options);
  });
  for (const old of existing.values()) old.remove();
  rows.forEach((row, i) => {
    if (container.children[i] !== row) container.insertBefore(row, container.children[i] || null);
  });
}

/** Actions shared by both pages. */
async function runAction(action, e, onError) {
  let res;
  switch (action) {
    case "open-file":
      res = await browser.runtime.sendMessage({ type: "open", entry: e.id, what: "file" });
      break;
    case "open-folder":
      res = await browser.runtime.sendMessage({ type: "open", entry: e.id, what: "folder" });
      break;
    case "source":
      res = await browser.runtime.sendMessage({ type: "openPage", url: e.referer || e.url });
      break;
    case "copy":
      await navigator.clipboard.writeText(e.referer || e.url);
      return;
    default:
      res = await browser.runtime.sendMessage({ type: action, entry: e.id });
  }
  if (res && res.error) onError(errorText(res));
}
