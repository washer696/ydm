#!/usr/bin/env python3
"""Bridge between the Firefox extension and yt-dlp (native messaging).

Security:
- only a few message types are accepted; everything else is refused;
- URLs are validated (http/https only) and passed to yt-dlp after "--",
  without a shell: they can never become an option or a command;
- the quality is a checked integer, the mode is "video" or "audio": no free-form option;
- "open" only accepts a history ID, never a path sent by the extension;
- the download folder is chosen on the bridge side (zenity), never received from the extension.

Privacy:
- the log contains no URL or title, and it is cleared along with the history;
- the state (history, log, yt-dlp output) is readable by the user only;
- downloads started from a private window are forgotten when private browsing ends.

Each download writes its output to ~/.local/state/ytdlp-bridge/jobs/<id>.out:
any bridge instance can follow its progress and record the result at the end,
even if Firefox was closed and reopened in the meantime.
"""
import json
import locale
import os
import re
import shutil
import signal
import struct
import subprocess
import sys
import threading
import time
import uuid
import zipfile
from urllib.parse import quote, urlsplit

from ydm_paths import DENO, HOME, MACOS, STATE_DIR, WINDOWS, YTDLP, search_path

if WINDOWS:
    import ctypes
    import msvcrt
else:
    import fcntl

FAST = os.path.join(os.path.dirname(os.path.realpath(__file__)), "ytdlp_fast.py")
SELFTEST = os.path.join(os.path.dirname(os.path.realpath(__file__)), "selftest.py")
LOG_FILE = os.path.join(STATE_DIR, "log.txt")
JOBS_DIR = os.path.join(STATE_DIR, "jobs")
HISTORY_FILE = os.path.join(STATE_DIR, "history.json")
SETTINGS_FILE = os.path.join(STATE_DIR, "settings.json")
UPDATE_FILE = os.path.join(STATE_DIR, "update.json")
LOCK_FILE = os.path.join(STATE_DIR, "history.lock")
# Bridge protocol version, announced to the extension: it asks the user to rerun install.py if the bridge is too old.
BRIDGE_VERSION = 2
MAX_URL_LEN = 4096
MAX_HISTORY = 500
UPDATE_INTERVAL = 24 * 3600
FRAGMENTS = "8"  # fragments downloaded in parallel (HLS/DASH), or byte ranges of a single-piece file: much faster
PROGRESS = (
    "download:PROG %(progress.status)s %(progress.downloaded_bytes)s %(progress.total_bytes)s "
    "%(progress.total_bytes_estimate)s %(progress.speed)s %(progress.eta)s "
    "%(progress.fragment_index)s %(progress.fragment_count)s %(info.vcodec)s"
)
ACTIVE = "downloading"
QUEUED = "queued"
PENDING = (ACTIVE, QUEUED)
# Beyond this, downloads wait their turn: each one already opens FRAGMENTS connections.
MAX_ACTIVE = 3
EXT = r"[0-9A-Za-z]+"
FMT = r"\.f[0-9A-Za-z_-]+"
# Strict allowlist of what may follow the name (without extension) of an unfinished download:
# never a finished file (.mp4, .mkv, .opus...), only what yt-dlp leaves along the way.
PARTIAL_SUFFIX = re.compile(
    rf"(?:{FMT})?\.{EXT}\.part(?:-Frag[0-9]+(?:\.part)?)?"
    rf"|(?:{FMT})?\.{EXT}\.ytdl"
    rf"|{FMT}\.{EXT}"
    r"|\.(?:webp|jpg|jpeg|png)"
    rf"|\.temp\.{EXT}"
)

# deno (JS engine for YouTube) and ffmpeg are not always in the PATH that Firefox passes on.
os.environ["PATH"] = os.pathsep.join(search_path() + [os.environ.get("PATH", "")])
os.environ["YDM_YTDLP"] = YTDLP  # for the accelerator and the self-test, which run separately
# yt-dlp writes its paths to a file: UTF-8 everywhere (otherwise Windows would use its code page).
os.environ["PYTHONIOENCODING"] = "utf-8"
os.makedirs(JOBS_DIR, exist_ok=True)
if not WINDOWS:
    # History, log and yt-dlp output reveal what you download: readable by you only.
    # Videos keep the usual permissions (see spawn). On Windows, the
    # %LOCALAPPDATA% folder is already private to the user.
    USER_UMASK = os.umask(0o077)
    for _dir in (STATE_DIR, JOBS_DIR):
        os.chmod(_dir, 0o700)
    with os.scandir(STATE_DIR) as _it:
        for _f in _it:
            if _f.is_file(follow_symlinks=False):
                os.chmod(_f.path, 0o600)

write_lock = threading.Lock()
state_lock = threading.Lock()
history_lock = threading.Lock()
updating = threading.Event()  # while the engine is updating, the queue starts nothing
owned = {}  # entry id -> Popen, for downloads started by this instance
live = {}  # entry id -> {"offset", "pending", "progress"} (tracked in memory, not on disk)


# --- What differs between systems ---

def lock_file(f):
    if WINDOWS:
        f.seek(0)
        while True:
            try:
                # LK_LOCK only retries once per second: far too slow for a lock held for a few ms.
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                return
            except OSError:
                time.sleep(0.01)
    else:
        fcntl.flock(f, fcntl.LOCK_EX)


def unlock_file(f):
    if WINDOWS:
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(f, fcntl.LOCK_UN)


def popen_detached(cmd, **kwargs):
    """Starts a process that outlives the bridge (and Firefox), in its own group, without a window."""
    if not WINDOWS:
        return subprocess.Popen(cmd, start_new_session=True, **kwargs)
    flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    try:
        # Firefox puts the bridge in a Windows "job" that it closes on exit: break away from it when allowed.
        return subprocess.Popen(cmd, creationflags=flags | subprocess.CREATE_BREAKAWAY_FROM_JOB, **kwargs)
    except OSError:
        return subprocess.Popen(cmd, creationflags=flags, **kwargs)


def process_alive(pid):
    if WINDOWS:
        # Never os.kill(pid, 0): on Windows, it kills the process.
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            return bool(ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.killpg(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def stop_process_tree(pid):
    """Stops yt-dlp and its ffmpeg processes; partial files are kept so the download can resume."""
    if WINDOWS:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], stdin=subprocess.DEVNULL,
                       capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        try:
            os.killpg(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass


def system_is_french():
    # POSIX order: the first variable that is set wins. Otherwise (Windows: "French_France") ask Python.
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        if os.environ.get(var):
            return os.environ[var].lower().startswith("fr")
    try:
        return (locale.getlocale()[0] or "").lower().startswith("fr")
    except ValueError:
        return False


FRENCH = system_is_french()


def tr(en, fr):
    """Text shown by the system itself (notifications, folder picker): it follows the system language."""
    return fr if FRENCH else en


def log(msg):
    # Never a URL or a title in the log: entries are referred to by their ID.
    # The filter catches a URL that slipped into an error message.
    msg = re.sub(r"[a-z][a-z0-9+.-]*://\S+", "<url>", msg, flags=re.I)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")


# --- Validation ---

def clean_url(value):
    """Returns the URL if it is safe, otherwise None."""
    if not isinstance(value, str) or not value or len(value) > MAX_URL_LEN:
        return None
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        return None
    try:
        parts = urlsplit(value)
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    return value


def clean_height(value):
    if value is None:
        return None
    if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 10000:
        return value
    raise ValueError("quality refused")


def clean_text(value, limit=300):
    if not isinstance(value, str):
        return None
    text = "".join(c for c in value if ord(c) >= 32 and ord(c) != 127).strip()
    return text[:limit] or None


def safe_name(title):
    """Page title -> safe file name: no folder, no hidden file, bounded length."""
    text = clean_text(title)
    if not text:
        return None
    text = text.replace("/", "_").replace("\\", "_").lstrip(". -")
    if WINDOWS:
        text = re.sub(r'[<>:"|?*]', "_", text).rstrip(". ")
    text = text.encode("utf-8")[:150].decode("utf-8", errors="ignore").strip()
    return text or None


# --- Settings (download folder) ---

def default_download_dir():
    if WINDOWS or MACOS:
        return os.path.join(HOME, "Movies" if MACOS else "Videos")
    try:
        out = subprocess.run(["xdg-user-dir", "VIDEOS"], stdin=subprocess.DEVNULL, capture_output=True,
                             text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        out = ""
    return out if out and os.path.isdir(out) else os.path.join(HOME, "Videos")


def custom_download_dir():
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            path = json.load(f).get("download_dir")
    except (OSError, ValueError, AttributeError):
        return None
    return path if isinstance(path, str) and os.path.isabs(path) and os.path.isdir(path) else None


def download_dir():
    return custom_download_dir() or default_download_dir()


def save_download_dir(path):
    """Saves the chosen folder; None (or the default folder) goes back to the default."""
    if path is not None and path == default_download_dir():
        path = None
    tmp = SETTINGS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"download_dir": path} if path else {}, f, ensure_ascii=False)
    os.replace(tmp, SETTINGS_FILE)


def settings_message(msg_id):
    return {"type": "settings", "id": msg_id, "download_dir": download_dir(),
            "is_default": custom_download_dir() is None, "ytdlp": ytdlp_info()}


# --- Native messaging protocol: 4-byte length + UTF-8 JSON ---

def read_message():
    raw_len = sys.stdin.buffer.read(4)
    if len(raw_len) < 4:
        return None
    (length,) = struct.unpack("@I", raw_len)
    if length > 1024 * 1024:
        raise ValueError("message too large")
    return json.loads(sys.stdin.buffer.read(length).decode("utf-8"))


def send(msg):
    data = json.dumps(msg).encode("utf-8")
    with write_lock:
        try:
            sys.stdout.buffer.write(struct.pack("@I", len(data)))
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()
        except (BrokenPipeError, ValueError):
            pass  # Firefox is closed: the desktop notification is enough


def notify(title, body):
    tool = shutil.which("notify-send")
    if tool:
        spawn_quiet([tool, "-a", "YDM", "-i", "folder-videos", title, body])
    elif MACOS:
        # Texts are passed as arguments, never inside the script: no quote can break it.
        spawn_quiet(["osascript", "-e", "on run argv", "-e",
                     "display notification (item 2 of argv) with title (item 1 of argv)", "-e", "end run",
                     title, body])
    elif WINDOWS:
        spawn_quiet(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                     "Add-Type -AssemblyName System.Windows.Forms, System.Drawing;"
                     "$n = New-Object System.Windows.Forms.NotifyIcon;"
                     "$n.Icon = [System.Drawing.SystemIcons]::Information; $n.Visible = $true;"
                     "$n.ShowBalloonTip(5000, $env:YDM_TITLE, $env:YDM_BODY, 'Info'); Start-Sleep 6; $n.Dispose()"],
                    env={**os.environ, "YDM_TITLE": title, "YDM_BODY": body or " "})


def spawn_quiet(cmd, env=None):
    try:
        popen_detached(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, env=env)
        return True
    except OSError:
        return False


# --- History (JSON file shared between instances, protected by a lock) ---

class History:
    def __enter__(self):
        history_lock.acquire()  # first between the bridge's threads, then between instances (file lock)
        try:
            self.lock = open(LOCK_FILE, "a")
            lock_file(self.lock)
        except BaseException:
            history_lock.release()
            raise
        try:
            with open(HISTORY_FILE, encoding="utf-8") as f:
                self.entries = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self.entries = []
        self.changed = False
        return self

    def get(self, entry_id):
        return next((e for e in self.entries if e["id"] == entry_id), None)

    def __exit__(self, *exc):
        try:
            if self.changed:
                self.entries = self.entries[:MAX_HISTORY]
                tmp = HISTORY_FILE + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(self.entries, f, ensure_ascii=False)
                os.replace(tmp, HISTORY_FILE)
        finally:
            unlock_file(self.lock)
            self.lock.close()
            history_lock.release()


def public(entry):
    """Entry as sent to the extension, with live progress."""
    e = {k: v for k, v in entry.items() if k != "pgid"}
    state = live.get(entry["id"])
    if entry["status"] == ACTIVE and state and state["progress"]:
        e["progress"] = state["progress"]
    return e


def push(entry):
    send({"type": "entry", "entry": public(entry)})


# --- yt-dlp as a library (the official binary is an importable zip archive) ---

sys.path.insert(0, YTDLP)
_extractors = None


def extractors():
    global _extractors
    if _extractors is None:
        from yt_dlp.extractor import gen_extractor_classes

        _extractors = [
            ie for ie in gen_extractor_classes()
            if ie.ie_key() != "Generic" and ie._WORKING
        ]
    return _extractors


def check(url):
    for ie in extractors():
        if ie.suitable(url):
            return ie.IE_NAME
    return None


def estimate_size(f, duration):
    size = f.get("filesize") or f.get("filesize_approx")
    if not size and f.get("tbr") and duration:
        size = f["tbr"] * 1000 / 8 * duration
    return int(size) if size else None


def formats(url, referer):
    """Lists the available qualities: one entry per height (the best one at that height)."""
    import yt_dlp

    opts = {"quiet": True, "no_warnings": True, "noplaylist": True, "socket_timeout": 20}
    if referer:
        opts["http_headers"] = {"Referer": referer}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    if info.get("_type") == "playlist":
        entries = [e for e in info.get("entries") or [] if e]
        if not entries:
            raise ValueError("no video found")
        info = entries[0]

    duration = info.get("duration")
    all_formats = info.get("formats") or [info]
    audio = [f for f in all_formats if f.get("vcodec") == "none" and f.get("acodec") not in (None, "none")]
    best_audio = estimate_size(audio[-1], duration) if audio else None

    # yt-dlp sorts its formats from worst to best: the last one at each height is the one it would pick.
    by_height = {}
    for f in all_formats:
        h = f.get("height")
        if h and f.get("vcodec") != "none":
            by_height[h] = f
    qualities = []
    for h in sorted(by_height, reverse=True):
        f = by_height[h]
        size = estimate_size(f, duration)
        if size and f.get("acodec") == "none" and best_audio:
            size += best_audio
        fps = f.get("fps")
        qualities.append({
            "height": h,
            "label": f"{h}p" + (f"{round(fps)}" if fps and fps > 30 else ""),
            "size": size,
        })
    return {
        "title": info.get("title"),
        "thumbnail": clean_url(info.get("thumbnail")),
        "duration": duration,
        "extractor": info.get("extractor_key"),
        "qualities": qualities,
        "audio": {"size": best_audio} if audio else None,
    }


# --- Engine update ---

def ytdlp_version():
    """yt-dlp version read from the archive, without importing or running it (starting it costs 1.7 s)."""
    try:
        with zipfile.ZipFile(YTDLP) as z:
            match = re.search(r"__version__\s*=\s*['\"]([^'\"]+)['\"]", z.read("yt_dlp/version.py").decode("utf-8"))
    except (OSError, KeyError, zipfile.BadZipFile):
        return None
    return match[1] if match else None


def read_update_state():
    try:
        with open(UPDATE_FILE, encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, ValueError):
        return {}
    return state if isinstance(state, dict) else {}


def write_update_state(**changes):
    state = {**read_update_state(), **changes}
    tmp = UPDATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)
    os.replace(tmp, UPDATE_FILE)


def fast_enabled():
    version = ytdlp_version()
    state = read_update_state()
    return version is not None and state.get("fast_ok") is True and state.get("fast_version") == version


def ytdlp_info():
    state = read_update_state()
    return {"version": ytdlp_version(), "checked": state.get("checked"), "error": state.get("error"),
            "fast": fast_enabled()}


def run_selftest():
    version = ytdlp_version()
    try:
        res = subprocess.run([sys.executable, SELFTEST], stdin=subprocess.DEVNULL, capture_output=True,
                             text=True, timeout=180)
        ok, last = res.returncode == 0, (res.stdout.strip().splitlines() or [""])[-1]
    except (OSError, subprocess.TimeoutExpired) as e:
        ok, last = False, str(e)
    write_update_state(fast_version=version, fast_ok=ok)
    log(f"SELFTEST OK {version}" if ok else f"SELFTEST FAILED {version} {last[:200]}")


def downloads_running():
    with History() as h:
        return any(e["status"] == ACTIVE and is_running(e) for e in h.entries)


def update_engine():
    """Updates yt-dlp and deno, then checks the accelerator if the version changed. Returns (before, after)."""
    before = ytdlp_version()
    try:
        res = subprocess.run([sys.executable, YTDLP, "-U"], stdin=subprocess.DEVNULL, capture_output=True,
                             text=True, timeout=180, **({"creationflags": subprocess.CREATE_NO_WINDOW} if WINDOWS else {}))
        lines = [l for l in (res.stderr or res.stdout).splitlines() if l.strip()]
        error = None if res.returncode == 0 else (lines[-1].strip() if lines else "failed with no message")[:300]
    except (OSError, subprocess.TimeoutExpired) as e:
        error = (str(e) or type(e).__name__)[:300]
    after = ytdlp_version()
    write_update_state(checked=time.time(), error=error)
    if before != after:
        log(f"UPDATE {before} -> {after}")
    elif error is None:
        log(f"UPDATE up to date {after}")
    else:
        log("UPDATE FAILED " + error)
    if os.path.isfile(DENO):
        spawn_quiet([DENO, "upgrade", "--quiet"])  # deno replaces itself atomically: no need to wait
    if after != read_update_state().get("fast_version"):
        run_selftest()
    return before, after


def maybe_update():
    # At startup: replacing the yt-dlp file under a process that has already imported it would break its
    # later lazy imports; here nothing is loaded yet.
    try:
        state = read_update_state()
        if time.time() - (state.get("checked") or 0) >= UPDATE_INTERVAL and not downloads_running():
            update_engine()
        elif state.get("fast_version") != ytdlp_version():
            run_selftest()
    except Exception as e:  # a failed update must never keep the bridge from starting
        log("UPDATE ERROR " + repr(e))


def update_now(msg_id):
    if downloads_running():
        send({"type": "error", "id": msg_id, "code": "wait_for_downloads", "error": "wait until the current downloads finish"})
        return
    updating.set()
    try:
        before, after = update_engine()
    finally:
        updating.clear()
    send(settings_message(msg_id))
    if after != before and "yt_dlp" in sys.modules:
        # The library loaded in this process no longer matches the file: the extension
        # reconnects on its next request and gets a brand-new bridge.
        log("RESTART engine updated")
        os._exit(0)


# --- Downloads ---

def job_paths(entry_id):
    return os.path.join(JOBS_DIR, entry_id + ".out"), os.path.join(JOBS_DIR, entry_id + ".err")


def build_command(entry):
    # Without an accelerator validated for this yt-dlp version: sequential 2 MB chunks, the measured fallback.
    base = [sys.executable, FAST] if fast_enabled() else [sys.executable, YTDLP, "--http-chunk-size", "2M"]
    cmd = base + ["--no-playlist", "-N", FRAGMENTS,
                  "-P", entry.get("dir") or download_dir(),
                  "--print", "video:TITLE %(title)s", "--print", "video:THUMB %(thumbnail)s",
                  "--print", "before_dl:STEM %(filename)s",
                  "--print", "after_move:FILE %(filepath)s",
                  "--progress", "--newline", "--progress-template", PROGRESS]
    h = entry.get("height")
    name = entry.get("name")
    # "%" doubled: the name is plain text, never a field of the yt-dlp template.
    stem = name.replace("%", "%%") if name else "%(title).150B [%(id)s]"
    if entry["mode"] == "audio":
        cmd += ["-x"]
        if name:
            cmd += ["-o", stem + ".%(ext)s"]
    elif h:
        cmd += ["-f", f"bv*[height={h}]+ba/b[height={h}]/bv*[height<={h}]+ba/b[height<={h}]/b",
                # The quality goes in the name: two qualities of the same video don't overwrite each other.
                "-o", stem + " %(height)sp.%(ext)s"]
    elif name:
        cmd += ["-o", stem + ".%(ext)s"]
    if entry.get("referer"):
        cmd += ["--referer", entry["referer"]]
    return cmd + ["--", entry["url"]]


def spawn(entry):
    """Starts yt-dlp for an entry (new or resumed). Existing .part files are resumed."""
    cmd = build_command(entry)
    quality = f" {entry['height']}p" if entry.get("height") else ""
    log(f"START {entry['id']} {entry['mode']}{quality} " + ("ranges" if cmd[1] == FAST else "normal"))
    out_path, err_path = job_paths(entry["id"])
    # Output goes to files (not pipes): if Firefox closes, yt-dlp keeps running.
    with open(out_path, "w") as out_f, open(err_path, "w") as err_f:
        proc = popen_detached(cmd, stdin=subprocess.DEVNULL, stdout=out_f, stderr=err_f,
                              **({} if WINDOWS else {"umask": USER_UMASK}))
    entry.update(status=ACTIVE, pgid=proc.pid, error=None, file=None, size=None,
                 started=time.time(), finished=None)
    with state_lock:
        owned[entry["id"]] = proc
        live[entry["id"]] = {"offset": 0, "pending": "", "progress": None}
    # Non-daemon thread: the bridge stays alive until its downloads finish.
    threading.Thread(target=wait_for, args=(entry["id"], proc)).start()


def wait_for(entry_id, proc):
    proc.wait()
    finalize(entry_id)


def pump(h):
    """Starts queued downloads, oldest first, while there is room.

    Called under the history lock: two bridge instances never start the same entry."""
    if updating.is_set():
        return []
    active = sum(e["status"] == ACTIVE for e in h.entries)
    started = []
    for e in sorted((e for e in h.entries if e["status"] == QUEUED), key=lambda e: e.get("queued") or 0):
        if active >= MAX_ACTIVE:
            break
        spawn(e)
        e.pop("queued", None)
        active += 1
        h.changed = True
        started.append(dict(e))
    return started


def enqueue(h, entry):
    entry.update(status=QUEUED, queued=time.time(), error=None, finished=None)
    h.changed = True
    return pump(h)


def start_queued():
    with History() as h:
        started = pump(h)
    for snapshot in started:
        push(snapshot)


def is_running(entry):
    with state_lock:
        proc = owned.get(entry["id"])
    if proc is not None:
        return proc.poll() is None
    pgid = entry.get("pgid")
    return isinstance(pgid, int) and process_alive(pgid)


def parse_progress(line):
    parts = line.split(" ")
    if len(parts) < 10:
        return None

    def num(v):
        try:
            return float(v)
        except ValueError:
            return None

    _, status, done, total, estimate, speed, eta, frag_i, frag_n, vcodec = parts[:10]
    done, total, estimate = num(done), num(total), num(estimate)
    frag_i, frag_n = num(frag_i), num(frag_n)
    total = total or estimate
    if total and done is not None:
        percent = min(100.0, done * 100 / total)
    elif frag_i and frag_n:
        percent = min(100.0, frag_i * 100 / frag_n)
    else:
        percent = None
    return {
        "percent": round(percent, 1) if percent is not None else None,
        "downloaded": done,
        "total": total,
        "speed": num(speed),
        "eta": num(eta),
        "part": "audio" if vcodec == "none" else "video",
    }


def read_output(entry_id):
    """Reads the new lines from yt-dlp. Returns the (progress, info) found."""
    out_path, _ = job_paths(entry_id)
    with state_lock:
        state = live.setdefault(entry_id, {"offset": 0, "pending": "", "progress": None})
    try:
        with open(out_path, encoding="utf-8", errors="replace") as f:
            f.seek(state["offset"])
            chunk = f.read()
            state["offset"] = f.tell()
    except FileNotFoundError:
        return None, {}
    lines = (state["pending"] + chunk).split("\n")
    state["pending"] = lines.pop()
    progress, info = None, {}
    for line in lines:
        if line.startswith("PROG "):
            progress = parse_progress(line) or progress
        elif line.startswith("TITLE "):
            info["title"] = clean_text(line[6:])
        elif line.startswith("THUMB "):
            info["thumbnail"] = clean_url(line[6:])
        elif line.startswith("STEM "):
            stem = os.path.splitext(os.path.basename(line[5:]))[0]
            if stem:
                info["stem"] = stem
        elif line.startswith("FILE "):
            info["file"] = line[5:]
    if progress:
        state["progress"] = progress
    return progress, info


def apply_info(entry, info):
    for k, v in info.items():
        # A download named after the page keeps that title (yt-dlp's is a technical one).
        if v and not (k == "title" and entry.get("name")):
            entry[k] = v


def finalize(entry_id):
    """Records the result of a finished download. Does nothing if already done."""
    _, info = read_output(entry_id)
    out_path, err_path = job_paths(entry_id)
    with History() as h:
        entry = h.get(entry_id)
        if not entry or entry["status"] != ACTIVE:
            return
        try:
            with open(err_path, encoding="utf-8", errors="replace") as f:
                err = f.read()
        except FileNotFoundError:
            err = ""
        apply_info(entry, info)
        entry["finished"] = time.time()
        file_path = entry.get("file")
        if entry.get("cancel_requested"):
            entry["status"] = "cancelled"
        elif file_path and os.path.isfile(file_path):
            entry["status"] = "done"
            entry["size"] = os.path.getsize(file_path)
        else:
            errors = [l for l in err.splitlines() if "ERROR" in l] or err.strip().splitlines()[-1:]
            entry["status"] = "failed"
            entry["error"] = (errors[-1] if errors else "interrupted").replace("ERROR: ", "")[:500]
        entry.pop("cancel_requested", None)
        entry.pop("pgid", None)
        h.changed = True
        snapshot = dict(entry)
        forgotten = drop_forgotten(h)
        kept = list(h.entries)
    with state_lock:
        owned.pop(entry_id, None)
        live.pop(entry_id, None)
    for p in (out_path, err_path):
        try:
            os.remove(p)
        except FileNotFoundError:
            pass

    log(f"{snapshot['status'].upper()} {entry_id}")
    # Notifications stay in the desktop's notification list: nothing from private browsing shows there.
    private = snapshot.get("private")
    if snapshot["status"] == "done":
        notify(tr("Download finished", "Téléchargement terminé"),
               tr("Private browsing", "Navigation privée") if private else os.path.basename(snapshot["file"]))
    elif snapshot["status"] == "failed":
        notify(tr("Download failed", "Échec du téléchargement"),
               tr("Private browsing", "Navigation privée") if private else snapshot.get("error") or "")
    if forgotten:
        discard_partials(forgotten, kept)
        send({"type": "history", "id": None, "entries": history_list()})
    else:
        push(snapshot)
    start_queued()  # a slot has opened up


def monitor():
    """Tracks all running downloads (including those from a previous Firefox session)."""
    last_push = {}
    while True:
        with History() as h:
            # Also picks up the queue of a bridge instance that went away midway.
            started = pump(h)
            running = [dict(e) for e in h.entries if e["status"] == ACTIVE]
        for snapshot in started:
            push(snapshot)
        for entry in running:
            progress, info = read_output(entry["id"])
            if info:
                # Saved right away: finalize() won't read these already consumed lines again.
                with History() as h:
                    e = h.get(entry["id"])
                    if e:
                        apply_info(e, info)
                        h.changed = True
                        entry = dict(e)
            if not is_running(entry):
                finalize(entry["id"])
            elif progress or info:
                now = time.monotonic()
                if now - last_push.get(entry["id"], 0) > 0.4:
                    last_push[entry["id"]] = now
                    push(entry)
        time.sleep(0.5)


# --- Actions ---

def new_entry_id():
    # A random part: the Windows high-resolution clock only moves in 15.6 ms steps.
    return time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:12]


def start_download(msg_id, url, referer, mode, height, title, label, name, private):
    with History() as h:
        for e in h.entries:
            if e["status"] in PENDING and e["url"] == url and e["mode"] == mode and e.get("height") == height:
                code, text = (("already_downloading", "already downloading") if e["status"] == ACTIVE
                              else ("already_queued", "already queued"))
                send({"type": "error", "id": msg_id, "code": code, "error": text})
                return
        entry = {
            "id": new_entry_id(), "url": url, "referer": referer, "mode": mode, "height": height,
            "label": label, "title": title, "name": name, "thumbnail": None,
            "dir": download_dir(), "created": time.time(),
        }
        if private:
            entry["private"] = True
        h.entries.insert(0, entry)
        started = enqueue(h, entry)
        snapshot = dict(entry)
    send({"type": "started", "id": msg_id, "entry": public(snapshot)})
    for s in started:
        if s["id"] != snapshot["id"]:
            push(s)


def cancel(msg_id, entry_id):
    with History() as h:
        entry = h.get(entry_id)
        if not entry or entry["status"] not in PENDING:
            send({"type": "error", "id": msg_id, "code": "download_missing", "error": "download not found"})
            return
        h.changed = True
        if entry["status"] == QUEUED:  # nothing has started yet: cancelled right away
            entry.pop("queued", None)
            entry.update(status="cancelled", finished=time.time())
            snapshot = dict(entry)
            forgotten = drop_forgotten(h)
        else:
            entry["cancel_requested"] = True
            snapshot = None
            pgid = entry.get("pgid")
    if snapshot:
        if forgotten:
            send({"type": "history", "id": None, "entries": history_list()})
        else:
            push(snapshot)
    else:
        if isinstance(pgid, int):
            stop_process_tree(pgid)
    send({"type": "ok", "id": msg_id})


def resume(msg_id, entry_id):
    with History() as h:
        entry = h.get(entry_id)
        if not entry or entry["status"] not in ("failed", "cancelled"):
            send({"type": "error", "id": msg_id, "code": "cannot_resume", "error": "cannot resume"})
            return
        started = enqueue(h, entry)
        snapshot = dict(entry)
    for s in [snapshot] + [s for s in started if s["id"] != entry_id]:
        push(s)
    send({"type": "ok", "id": msg_id})


def partial_files(entry):
    """Unfinished files left by a download (only lists them, deletes nothing)."""
    folder, stem = entry.get("dir"), entry.get("stem")
    if not folder or not stem or not os.path.isdir(folder):
        return []
    found = []
    with os.scandir(folder) as it:
        for item in it:
            if (item.name.startswith(stem) and PARTIAL_SUFFIX.fullmatch(item.name[len(stem):])
                    and item.is_file(follow_symlinks=False)):
                found.append(item.path)
    return found


def delete_partials(entry, kept):
    """`kept`: entries that remain in the history."""
    # A download restarted as a new row writes to the same files as the old one.
    if any(e.get("stem") == entry.get("stem") and e.get("dir") == entry.get("dir") for e in kept):
        return
    count = 0
    for path in partial_files(entry):
        try:
            os.remove(path)
            count += 1
        except FileNotFoundError:
            pass
    if count:
        log(f"PARTIALS {count} file(s) deleted for {entry.get('id')}")


def remove(msg_id, entry_id):
    with History() as h:
        dropped = [e for e in h.entries if e["id"] == entry_id and e["status"] not in PENDING]
        h.entries = [e for e in h.entries if e["id"] != entry_id or e["status"] in PENDING]
        h.changed = bool(dropped)
        kept = list(h.entries)
    discard_partials(dropped, kept)
    send({"type": "history", "id": msg_id, "entries": history_list()})


def clear(msg_id):
    with History() as h:
        dropped = [e for e in h.entries if e["status"] not in PENDING]
        h.entries = [e for e in h.entries if e["status"] in PENDING]
        h.changed = True
        kept = list(h.entries)
    discard_partials(dropped, kept)
    # The log follows the history: clearing one clears the other.
    open(LOG_FILE, "w").close()
    send({"type": "history", "id": msg_id, "entries": history_list()})


def drop_forgotten(h):
    """Removes from the history the finished private downloads whose private browsing session has ended."""
    dropped = [e for e in h.entries if e.get("forget") and e["status"] not in PENDING]
    if dropped:
        ids = {e["id"] for e in dropped}
        h.entries = [e for e in h.entries if e["id"] not in ids]
        h.changed = True
    return dropped


def discard_partials(dropped, kept):
    """Deletes the unfinished files of removed entries (never a finished video)."""
    for e in dropped:
        if e["status"] in ("failed", "cancelled"):
            delete_partials(e, kept)


def forget_private(msg_id):
    """Last private window closed: like Firefox, forget its downloads.

    Those still running or queued are forgotten when they end. Finished videos stay on disk."""
    with History() as h:
        for e in h.entries:
            if e.get("private") and not e.get("forget"):
                e["forget"] = True
                h.changed = True
        dropped = drop_forgotten(h)
        kept = list(h.entries)
    discard_partials(dropped, kept)
    send({"type": "history", "id": msg_id, "entries": history_list()})


def folder_dialog():
    """Command (and environment) for the native folder picker. It prints the chosen path
    and exits with code 0, or exits with code 1 if closed without choosing."""
    title, start = tr("Download folder", "Dossier de téléchargement"), download_dir()
    zenity = shutil.which("zenity")
    if zenity:
        return [zenity, "--file-selection", "--directory", "--title", title, "--filename", start + os.sep], None
    if MACOS:
        return ["osascript", "-e", "on run argv", "-e",
                "POSIX path of (choose folder with prompt (item 1 of argv) default location (POSIX file (item 2 of argv)))",
                "-e", "end run", title, start], None
    if WINDOWS:
        script = ("Add-Type -AssemblyName System.Windows.Forms;"
                  "$owner = New-Object System.Windows.Forms.Form -Property @{TopMost = $true};"
                  "$d = New-Object System.Windows.Forms.FolderBrowserDialog;"
                  "$d.Description = $env:YDM_TITLE; $d.SelectedPath = $env:YDM_START;"
                  "if ($d.ShowDialog($owner) -eq 'OK') {"
                  " [Console]::OutputEncoding = [Text.Encoding]::UTF8; [Console]::Out.Write($d.SelectedPath) }"
                  " else { exit 1 }")
        return (["powershell", "-NoProfile", "-NonInteractive", "-STA", "-Command", script],
                {**os.environ, "YDM_TITLE": title, "YDM_START": start})
    return None, None


def pick_folder(msg_id):
    cmd, env = folder_dialog()
    if not cmd:
        send({"type": "error", "id": msg_id, "code": "no_folder_dialog", "error": "no folder picker available (install zenity)"})
        return
    try:
        res = subprocess.run(cmd, env=env, stdin=subprocess.DEVNULL, capture_output=True, encoding="utf-8",
                             errors="replace", **({"creationflags": subprocess.CREATE_NO_WINDOW} if WINDOWS else {}))
    except OSError:
        send({"type": "error", "id": msg_id, "code": "folder_dialog_failed", "error": "the folder picker could not open"})
        return
    if res.returncode == 0:
        path = res.stdout.strip("\r\n")
        stripped = path.rstrip("/\\")  # macOS ends the path with "/"
        if stripped and os.path.isabs(stripped):  # without breaking "/" or "C:\"
            path = stripped
        if not (os.path.isabs(path) and os.path.isdir(path) and os.access(path, os.W_OK)):
            send({"type": "error", "id": msg_id, "code": "folder_unusable", "error": "this folder can't be used"})
            return
        save_download_dir(path)
    elif res.returncode != 1:  # 1 = window closed without choosing
        log("FOLDER " + res.stderr.strip()[:300])
        send({"type": "error", "id": msg_id, "code": "folder_dialog_failed", "error": "the folder picker could not open"})
        return
    send(settings_message(msg_id))


def history_list():
    with History() as h:
        return [public(e) for e in h.entries]


def open_entry(msg_id, entry_id, what):
    with History() as h:
        entry = h.get(entry_id)
        path = entry.get("file") if entry else None
    if not path or not os.path.isfile(path):
        send({"type": "error", "id": msg_id, "code": "file_missing", "error": "file not found (moved or deleted?)"})
        return
    if WINDOWS:
        try:
            if what == "file":
                os.startfile(path)
            else:  # explorer returns 1 even when all is well: ignore its exit code
                popen_detached(f'explorer /select,"{path}"')
            ok = True
        except OSError:
            ok = False
    elif MACOS:
        ok = spawn_quiet(["open", path] if what == "file" else ["open", "-R", path])
    elif what == "file":
        ok = spawn_quiet(["xdg-open", path])
    else:
        # Opens the folder with the file selected (Files/Nautilus), otherwise just opens the folder.
        uri = "file://" + quote(path)
        try:
            ok = subprocess.run(
                ["gdbus", "call", "--session", "--dest", "org.freedesktop.FileManager1",
                 "--object-path", "/org/freedesktop/FileManager1",
                 "--method", "org.freedesktop.FileManager1.ShowItems", f"['{uri}']", ""],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5,
            ).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            ok = False
        if not ok:
            ok = spawn_quiet(["xdg-open", os.path.dirname(path)])
    send({"type": "ok", "id": msg_id} if ok else {"type": "error", "id": msg_id, "code": "cannot_open", "error": "cannot open"})


# --- Message dispatch ---

def handle(msg):
    if not isinstance(msg, dict):
        return
    msg_id = msg.get("id")
    kind = msg.get("type")
    entry_id = msg.get("entry")
    if entry_id is not None and (not isinstance(entry_id, str) or len(entry_id) > 100):
        send({"type": "error", "id": msg_id, "code": "bad_entry", "error": "entry refused"})
        return

    if kind == "history":
        send({"type": "history", "id": msg_id, "entries": history_list(), "bridge": BRIDGE_VERSION})
    elif kind == "clear":
        clear(msg_id)
    elif kind == "forgetPrivate":
        forget_private(msg_id)
    elif kind == "cancel":
        cancel(msg_id, entry_id)
    elif kind == "resume":
        resume(msg_id, entry_id)
    elif kind == "remove":
        remove(msg_id, entry_id)
    elif kind == "settings":
        send(settings_message(msg_id))
    elif kind == "pickFolder":
        threading.Thread(target=pick_folder, args=(msg_id,), daemon=True).start()
    elif kind == "resetFolder":
        save_download_dir(None)
        send(settings_message(msg_id))
    elif kind == "update":
        threading.Thread(target=update_now, args=(msg_id,), daemon=True).start()
    elif kind == "open":
        what = msg.get("what")
        if what not in ("file", "folder"):
            send({"type": "error", "id": msg_id, "code": "bad_action", "error": "action refused"})
            return
        open_entry(msg_id, entry_id, what)
    elif kind in ("check", "formats", "download"):
        url = clean_url(msg.get("url"))
        if url is None:
            send({"type": "error", "id": msg_id, "code": "bad_url", "error": "URL refused"})
            return
        referer = msg.get("referer")
        if referer is not None:
            referer = clean_url(referer)
            if referer is None:
                send({"type": "error", "id": msg_id, "code": "bad_referer", "error": "referer refused"})
                return
        if kind == "check":
            send({"type": "check", "id": msg_id, "url": url, "extractor": check(url)})
        elif kind == "formats":
            def work():
                try:
                    send({"type": "formats", "id": msg_id, "url": url, **formats(url, referer)})
                except Exception as e:
                    send({"type": "formats", "id": msg_id, "url": url, "error": short_error(e)})
            threading.Thread(target=work, daemon=True).start()
        else:
            mode = msg.get("mode", "video")
            if mode not in ("video", "audio"):
                send({"type": "error", "id": msg_id, "code": "bad_mode", "error": "mode refused"})
                return
            height = clean_height(msg.get("height")) if mode == "video" else None
            title = clean_text(msg.get("title"))
            name = safe_name(title) if msg.get("pageTitle") is True else None
            start_download(msg_id, url, referer, mode, height, title, clean_text(msg.get("label"), 40), name,
                           msg.get("private") is True)
    else:
        send({"type": "error", "id": msg_id, "code": "unknown_message", "error": "unknown message type"})


def short_error(e):
    text = str(e).replace("ERROR: ", "").strip()
    return text.splitlines()[0][:300] if text else type(e).__name__


def main():
    log(f"BRIDGE START pid={os.getpid()} args={sys.argv[1:]}")
    if WINDOWS:  # the protocol is binary: no line-ending conversion
        msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
        msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)
    maybe_update()
    threading.Thread(target=monitor, daemon=True).start()
    while True:
        try:
            msg = read_message()
        except (ValueError, UnicodeDecodeError) as e:
            log("BAD MESSAGE " + str(e))
            return
        if msg is None:
            return
        try:
            handle(msg)
        except Exception as e:  # never let one message kill the bridge
            log("ERROR " + repr(e))
            send({"type": "error", "id": msg.get("id") if isinstance(msg, dict) else None, "error": short_error(e)})


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log("CRASH " + repr(e))
        raise
