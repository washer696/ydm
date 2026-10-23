"""Test client for the bridge: speaks the native messaging protocol in an isolated environment.

The bridge's state (history, settings) goes to a temporary folder through XDG_STATE_HOME:
nothing a test does touches the real history or settings.
A fake `zenity` placed first in PATH answers in place of the folder picker dialog
(the bridge prefers it to the system dialog when it finds it, on Linux, macOS or Windows).
"""
import json, os, queue, shutil, stat, struct, subprocess, sys, tempfile, threading, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRIDGE = os.path.join(ROOT, "host", "ytdlp_bridge.py")
WINDOWS = sys.platform == "win32"


def fake_command(root, name, posix, windows):
    """Fake tool in <root>/bin: a shell script, or a .cmd file on Windows (body without the header line)."""
    fake_bin = os.path.join(root, "bin")
    os.makedirs(fake_bin, exist_ok=True)
    if WINDOWS:
        with open(os.path.join(fake_bin, name + ".cmd"), "w", newline="") as f:
            f.write("@echo off\r\n" + windows.replace("\n", "\r\n"))
        return
    script = os.path.join(fake_bin, name)
    with open(script, "w") as f:
        f.write("#!/bin/sh\n" + posix)
    os.chmod(script, os.stat(script).st_mode | stat.S_IEXEC)


def isolated_env(root, zenity_answer=None, home=None):
    """Environment whose state lives under `root`. `zenity_answer`: path returned by the fake zenity, None = cancel. `home`: replacement HOME."""
    fake_bin = os.path.join(root, "bin")
    if zenity_answer:
        fake_command(root, "zenity", f"printf '%s\\n' '{zenity_answer}'\n", f"echo {zenity_answer}\n")
    else:
        fake_command(root, "zenity", "exit 1\n", "exit /b 1\n")
    # no desktop notifications during tests
    fake_command(root, "notify-send", "exit 0\n", "exit /b 0\n")
    state = os.path.join(root, "state", "ytdlp-bridge")
    os.makedirs(state, exist_ok=True)
    update = os.path.join(state, "update.json")
    if not os.path.exists(update):  # without this, every test bridge would run a real `yt-dlp -U`
        with open(update, "w") as f:
            json.dump({"checked": time.time()}, f)
    env = dict(os.environ, XDG_STATE_HOME=os.path.join(root, "state"), PATH=fake_bin + os.pathsep + os.environ["PATH"])
    if home:
        # On Windows, the home folder comes from USERPROFILE and programs from LOCALAPPDATA.
        env.update(HOME=home, USERPROFILE=home, LOCALAPPDATA=os.path.join(home, "AppData", "Local"))
    return env


class Bridge:
    def __init__(self, env, bridge=BRIDGE, cmd=None):
        """`cmd`: launch command as Firefox would use it (installed launcher); otherwise the bridge from the source tree."""
        self.proc = subprocess.Popen(cmd or [sys.executable, bridge], stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=env)
        self.inbox = queue.Queue()
        self.next_id = 1
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        while True:
            header = self.proc.stdout.read(4)
            if len(header) < 4:
                return
            self.inbox.put(json.loads(self.proc.stdout.read(struct.unpack("@I", header)[0])))

    def send(self, type_, **payload):
        msg_id = self.next_id
        self.next_id += 1
        data = json.dumps({"id": msg_id, "type": type_, **payload}).encode()
        self.proc.stdin.write(struct.pack("@I", len(data)) + data)
        self.proc.stdin.flush()
        return msg_id

    def until(self, pred, timeout=90):
        end = time.time() + timeout
        while time.time() < end:
            try:
                msg = self.inbox.get(timeout=1)
            except queue.Empty:
                continue
            if pred(msg):
                return msg
        raise TimeoutError("expected message not received from the bridge")

    def call(self, type_, timeout=90, **payload):
        msg_id = self.send(type_, **payload)
        return self.until(lambda m: m.get("id") == msg_id and m["type"] != "entry", timeout)

    def entry_until(self, entry_id, pred, timeout=120):
        return self.until(lambda m: m["type"] == "entry" and m["entry"]["id"] == entry_id and pred(m["entry"]), timeout)["entry"]

    def close(self):
        self.proc.stdin.close()
        self.proc.wait(timeout=60)


def sandbox():
    return tempfile.mkdtemp(prefix="ytdlp-bridge-test-")


def cleanup(root):
    shutil.rmtree(root, ignore_errors=True)
