"use strict";

// Interface languages. The choice ("auto", "en" or "fr") is kept in storage.local; "auto" follows
// Firefox's language. English is the fallback for any missing text.

const MESSAGES = {
  en: {
    // Units and times
    unitGB: "GB",
    unitMB: "MB",
    unitKB: "KB",
    timeJustNow: "just now",
    timeMinutesAgo: "{n} min ago",
    timeToday: "today {time}",
    timeYesterday: "yesterday {time}",
    timeLeft: "{time} left",
    // Download rows
    videoFrom: "Video from {host}",
    status_downloading: "Downloading",
    status_queued: "Queued",
    status_done: "Done",
    status_failed: "Failed",
    status_cancelled: "Cancelled",
    preparing: "Preparing…",
    audioTrack: "audio track",
    audio: "Audio",
    canResume: "can resume",
    cancelResumable: "Cancel (can resume)",
    removeFromQueue: "Remove from the queue",
    openFile: "Open the file",
    showInFolder: "Show in folder",
    resume: "Resume",
    retry: "Retry",
    openSource: "Open the original page",
    copyLink: "Copy the link",
    removeFromHistory: "Remove from history",
    removeAndDeletePartial: "Remove and delete the partial file",
    // Bridge
    bridgeMissing: "YDM's companion app isn't installed yet.",
    bridgeUnavailable: "Companion app unavailable: {error}",
    bridgeOutdated: "YDM's companion app needs an update.",
    howToInstall: "How to install it",
    howToUpdate: "How to update it",
    credit: "YDM runs on yt-dlp, made by volunteers.",
    supportThem: "Support them",
    err_bad_action: "action refused",
    err_wait_for_downloads: "wait until the current downloads finish",
    err_no_folder_dialog: "no folder picker available (install zenity)",
    err_already_downloading: "already downloading",
    err_already_queued: "already queued",
    err_folder_unusable: "this folder can't be used",
    err_bad_entry: "entry refused",
    err_file_missing: "file not found (moved or deleted?)",
    err_cannot_resume: "cannot resume",
    err_cannot_open: "cannot open",
    err_folder_dialog_failed: "the folder picker could not open",
    err_bad_mode: "mode refused",
    err_bad_referer: "referer refused",
    err_download_missing: "download not found",
    err_unknown_message: "unknown message type",
    err_bad_url: "URL refused",
    // Popup
    history: "History",
    settings: "Settings",
    streamsDetected: "Detected streams",
    nothingLine1: "No video detected on this page.",
    nothingLine2: "Start playing it, or analyze the page.",
    analyzePage: "Analyze the page",
    downloads: "Downloads",
    cannotListQualities: "Can't list the qualities: {error}",
    tryAnyway: "Try anyway",
    best: "Best",
    video: "Video",
    moreQualities_one: "{n} more quality",
    moreQualities_other: "{n} more qualities",
    audioOnly: "Audio only",
    chooseQuality: "Choose the quality",
    downloadBest: "Download (best quality)",
    streamFile: "File",
    // Downloads page
    downloadsTitle: "YDM downloads",
    filter: "Filter",
    filterAll: "All",
    filterActive: "In progress",
    filterDone: "Done",
    filterProblem: "Failed / cancelled",
    search: "Search",
    clearHistory: "Clear history",
    confirm: "Confirm?",
    downloadFolder: "Download folder",
    choose: "Choose…",
    chooseInWindow: "Choose in the window…",
    defaultFolder: "Default",
    engine: "yt-dlp engine",
    update: "Update",
    updating: "Updating…",
    language: "Language",
    langAuto: "Automatic (Firefox)",
    footnote: "Clearing the history never deletes a finished video. Partial files of cancelled or failed downloads are deleted.",
    summaryActive: "{n} in progress",
    summaryQueued: "{n} queued",
    summaryTotal: "{size} downloaded",
    emptyNone: "No downloads yet. Click the YDM icon on a page with a video.",
    emptyFilter: "No results for this filter.",
    engineVersion: "version {v}",
    engineUnknown: "unknown version",
    engineChecked: "checked {when}",
    engineNeverChecked: "never checked",
    engineCheckFailed: "last check failed",
    engineNoAccel: "accelerator off",
    // Toolbar and menu
    menuDownload: "Download with YDM",
    toolbarActive_one: "{n} download in progress",
    toolbarActive_other: "{n} downloads in progress",
    toolbarQueued: "{n} queued",
  },
  fr: {
    unitGB: "Go",
    unitMB: "Mo",
    unitKB: "Ko",
    timeJustNow: "à l'instant",
    timeMinutesAgo: "il y a {n} min",
    timeToday: "aujourd'hui {time}",
    timeYesterday: "hier {time}",
    timeLeft: "{time} restant",
    videoFrom: "Vidéo de {host}",
    status_downloading: "En cours",
    status_queued: "En attente",
    status_done: "Terminé",
    status_failed: "Échec",
    status_cancelled: "Annulé",
    preparing: "Préparation…",
    audioTrack: "piste audio",
    audio: "Audio",
    canResume: "reprise possible",
    cancelResumable: "Annuler (reprise possible)",
    removeFromQueue: "Retirer de la file d'attente",
    openFile: "Ouvrir le fichier",
    showInFolder: "Afficher dans le dossier",
    resume: "Reprendre",
    retry: "Réessayer",
    openSource: "Ouvrir la page d'origine",
    copyLink: "Copier le lien",
    removeFromHistory: "Retirer de l'historique",
    removeAndDeletePartial: "Retirer et supprimer le fichier partiel",
    bridgeMissing: "L'application compagnon de YDM n'est pas encore installée.",
    bridgeUnavailable: "Application compagnon indisponible : {error}",
    bridgeOutdated: "L'application compagnon de YDM doit être mise à jour.",
    howToInstall: "Comment l'installer",
    howToUpdate: "Comment la mettre à jour",
    credit: "YDM repose sur yt-dlp, fait par des bénévoles.",
    supportThem: "Les soutenir",
    err_bad_action: "action refusée",
    err_wait_for_downloads: "attends la fin des téléchargements en cours",
    err_no_folder_dialog: "aucune fenêtre de choix de dossier (installe zenity)",
    err_already_downloading: "déjà en cours",
    err_already_queued: "déjà en attente",
    err_folder_unusable: "dossier inutilisable",
    err_bad_entry: "entrée refusée",
    err_file_missing: "fichier introuvable (déplacé ou supprimé ?)",
    err_cannot_resume: "impossible de reprendre",
    err_cannot_open: "impossible d'ouvrir",
    err_folder_dialog_failed: "la fenêtre de choix du dossier n'a pas pu s'ouvrir",
    err_bad_mode: "mode refusé",
    err_bad_referer: "referer refusé",
    err_download_missing: "téléchargement introuvable",
    err_unknown_message: "type de message inconnu",
    err_bad_url: "URL refusée",
    history: "Historique",
    settings: "Réglages",
    streamsDetected: "Flux détectés",
    nothingLine1: "Aucune vidéo détectée sur cette page.",
    nothingLine2: "Lance la lecture, ou analyse la page.",
    analyzePage: "Analyser la page",
    downloads: "Téléchargements",
    cannotListQualities: "Impossible de lister les qualités : {error}",
    tryAnyway: "Essayer quand même",
    best: "Meilleure",
    video: "Vidéo",
    moreQualities_one: "{n} autre qualité",
    moreQualities_other: "{n} autres qualités",
    audioOnly: "Audio seul",
    chooseQuality: "Choisir la qualité",
    downloadBest: "Télécharger (meilleure qualité)",
    streamFile: "Fichier",
    downloadsTitle: "Téléchargements YDM",
    filter: "Filtrer",
    filterAll: "Tout",
    filterActive: "En cours",
    filterDone: "Terminés",
    filterProblem: "Échecs / annulés",
    search: "Rechercher",
    clearHistory: "Vider l'historique",
    confirm: "Confirmer ?",
    downloadFolder: "Dossier de téléchargement",
    choose: "Choisir…",
    chooseInWindow: "Choisis dans la fenêtre…",
    defaultFolder: "Par défaut",
    engine: "Moteur yt-dlp",
    update: "Mettre à jour",
    updating: "Mise à jour…",
    language: "Langue",
    langAuto: "Automatique (Firefox)",
    footnote: "Vider l'historique ne supprime aucune vidéo terminée. Les fichiers partiels des téléchargements annulés ou en échec sont supprimés.",
    summaryActive: "{n} en cours",
    summaryQueued: "{n} en attente",
    summaryTotal: "{size} téléchargés",
    emptyNone: "Aucun téléchargement pour l'instant. Clique sur l'icône YDM sur une page avec une vidéo.",
    emptyFilter: "Aucun résultat pour ce filtre.",
    engineVersion: "version {v}",
    engineUnknown: "version inconnue",
    engineChecked: "vérifié {when}",
    engineNeverChecked: "jamais vérifié",
    engineCheckFailed: "échec de la dernière vérification",
    engineNoAccel: "accélérateur désactivé",
    menuDownload: "Télécharger avec YDM",
    toolbarActive_one: "{n} téléchargement en cours",
    toolbarActive_other: "{n} téléchargements en cours",
    toolbarQueued: "{n} en attente",
  },
};

const LANGUAGES = ["en", "fr"];

function resolveLang(choice) {
  if (LANGUAGES.includes(choice)) return choice;
  return browser.i18n.getUILanguage().toLowerCase().startsWith("fr") ? "fr" : "en";
}

let LANG = resolveLang("auto");
let langChoice = "auto";

async function loadLang() {
  try {
    langChoice = (await browser.storage.local.get("lang")).lang || "auto";
  } catch {
    langChoice = "auto";
  }
  LANG = resolveLang(langChoice);
  document.documentElement.lang = LANG;
}

const I18N_READY = loadLang();

function locale() {
  return LANG === "fr" ? "fr-FR" : "en-US";
}

/** Text for `key` in the current language, with {name} placeholders filled from `vars`. */
function t(key, vars = {}) {
  let text = MESSAGES[LANG][key] ?? MESSAGES.en[key] ?? key;
  for (const [name, value] of Object.entries(vars)) text = text.split("{" + name + "}").join(String(value));
  return text;
}

/** Plural form: `key_one`, `key_other`... chosen for `n` by the language's rules. */
function tn(key, n, vars = {}) {
  const form = new Intl.PluralRules(locale()).select(n);
  const exact = key + "_" + form;
  return t(MESSAGES[LANG][exact] ?? MESSAGES.en[exact] ? exact : key + "_other", { n, ...vars });
}

/** Message of a failed reply: the bridge's code in the current language, else its own text. */
function errorText(res) {
  const key = "err_" + res.code;
  return res.code && MESSAGES.en[key] ? t(key) : res.error;
}

/** Fills the elements marked data-i18n (text), data-i18n-placeholder, data-i18n-title and data-i18n-label. */
function localizePage(root = document) {
  for (const node of root.querySelectorAll("[data-i18n]")) node.textContent = t(node.dataset.i18n);
  for (const node of root.querySelectorAll("[data-i18n-placeholder]")) node.placeholder = t(node.dataset.i18nPlaceholder);
  for (const node of root.querySelectorAll("[data-i18n-title]")) {
    node.title = t(node.dataset.i18nTitle);
    node.setAttribute("aria-label", node.title);
  }
  for (const node of root.querySelectorAll("[data-i18n-label]")) node.setAttribute("aria-label", t(node.dataset.i18nLabel));
}
