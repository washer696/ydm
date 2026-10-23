#!/usr/bin/env python3
"""Publishes the signed version to the public repository: one clean commit, the update manifest and the downloadable release.

Usage: tools/publish.py [--fresh] [--message TEXT]   (after tools/sign.sh, with no uncommitted changes)

--message replaces the public commit's message ("YDM <version>" by default), for changes that don't
touch the extension, such as the tests.

--fresh starts the public history over with this version: older commits, releases and tags are
deleted, and links to older versions stop working. Only for cleaning up what was published by mistake.

The public repository is the one named by `update_url` in extension/manifest.json. Every operation
goes through the GitHub account stored in ~/.config/gh-ydm (gh auth login with GH_CONFIG_DIR), never
through the machine's default GitHub account. The script stops if that account does not own the
public repository. Public commits carry the anonymous address GitHub gives that account, and UTC
timestamps so they do not reveal the author's time zone.
"""
import glob, hashlib, json, os, re, shutil, subprocess, sys, tarfile, tempfile
from io import BytesIO

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GH = shutil.which("gh") or os.path.expanduser("~/.local/bin/gh")
GH_ENV = {**os.environ, "GH_CONFIG_DIR": os.path.expanduser("~/.config/gh-ydm")}
WORK = os.path.expanduser("~/.local/share/ydm-publish")
GIT_UTC = {**os.environ, "TZ": "UTC"}
DESCRIPTION = "Download the videos you're watching, straight from Firefox. A small front end for yt-dlp."


def run(cmd, cwd=None, env=None, capture=True):
    res = subprocess.run(cmd, cwd=cwd, env=env, capture_output=capture, text=True)
    if res.returncode != 0:
        sys.exit(f"Failed: {' '.join(cmd)}\n{res.stderr if capture else ''}")
    return res.stdout.strip() if capture else ""


def gh(*args, capture=True):
    return run([GH, *args], env=GH_ENV, capture=capture)


def main():
    with open(os.path.join(ROOT, "extension", "manifest.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    gecko, version = manifest["browser_specific_settings"]["gecko"], manifest["version"]
    match = re.fullmatch(r"https://raw\.githubusercontent\.com/([^/]+)/([^/]+)/main/updates\.json", gecko["update_url"])
    owner, name = match[1], match[2]
    repo = f"{owner}/{name}"
    fresh = "--fresh" in sys.argv[1:]
    args = sys.argv[1:]
    message = args[args.index("--message") + 1] if "--message" in args[:-1] else f"YDM {version}"

    if run(["git", "status", "--porcelain"], cwd=ROOT):
        sys.exit("The repository has uncommitted changes: commit them first.")
    signed = sorted(glob.glob(os.path.join(ROOT, "web-ext-artifacts", f"*-{version}.xpi")), key=os.path.getmtime)
    if not signed:
        sys.exit(f"No signed .xpi for version {version}: run tools/sign.sh first.")
    xpi = os.path.join(ROOT, "web-ext-artifacts", f"ydm-{version}.xpi")
    if signed[-1] != xpi:
        shutil.copyfile(signed[-1], xpi)
    # Same file under a fixed name: install.py fetches releases/latest/download/ydm.xpi.
    latest = os.path.join(ROOT, "web-ext-artifacts", "ydm.xpi")
    shutil.copyfile(xpi, latest)

    user = json.loads(gh("api", "user"))
    if user["login"] != owner:
        sys.exit(f"The ~/.config/gh-ydm account is {user['login']}, not {owner}: refusing to publish.")
    identity = ["-c", f"user.name={owner}", "-c", f"user.email={user['id']}+{owner}@users.noreply.github.com",
                "-c", "credential.https://github.com.helper=",
                "-c", f"credential.https://github.com.helper=!GH_CONFIG_DIR={GH_ENV['GH_CONFIG_DIR']} {GH} auth git-credential"]

    # Working copy of the public repository: created, or cloned again if missing.
    public = os.path.join(WORK, name)
    exists = subprocess.run([GH, "repo", "view", repo], env=GH_ENV, capture_output=True).returncode == 0
    if exists and fresh:
        for tag in gh("release", "list", "--repo", repo, "--json", "tagName", "-q", ".[].tagName").split():
            gh("release", "delete", tag, "--repo", repo, "--cleanup-tag", "--yes")
        shutil.rmtree(public, ignore_errors=True)
        run(["git", "init", "-q", "-b", "main", public])
        run(["git", "remote", "add", "origin", f"https://github.com/{repo}.git"], cwd=public)
    if not exists:
        gh("repo", "create", repo, "--public", "--description", DESCRIPTION)
    else:
        gh("repo", "edit", repo, "--description", DESCRIPTION)  # kept in sync with this file
    if not os.path.isdir(os.path.join(public, ".git")):
        shutil.rmtree(public, ignore_errors=True)
        os.makedirs(WORK, exist_ok=True)
        if exists:
            run(["git", *identity, "clone", f"https://github.com/{repo}.git", public])
        else:
            run(["git", "init", "-q", "-b", "main", public])
            run(["git", "remote", "add", "origin", f"https://github.com/{repo}.git"], cwd=public)

    # Content: exactly the files tracked by the private repository at this commit (nothing else, no history).
    updates_path = os.path.join(public, "updates.json")
    try:
        with open(updates_path, encoding="utf-8") as f:
            updates = json.load(f)
    except FileNotFoundError:
        updates = {"addons": {}}
    for item in os.listdir(public):
        if item != ".git":
            path = os.path.join(public, item)
            shutil.rmtree(path) if os.path.isdir(path) and not os.path.islink(path) else os.remove(path)
    archive = subprocess.run(["git", "archive", "--format=tar", "HEAD"], cwd=ROOT, capture_output=True, check=True).stdout
    with tarfile.open(fileobj=BytesIO(archive)) as tar:
        tar.extractall(public, filter="data")

    with open(xpi, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    versions = updates["addons"].setdefault(gecko["id"], {"updates": []})["updates"]
    versions[:] = [v for v in versions if v["version"] != version] + [{
        "version": version,
        "update_link": f"https://github.com/{repo}/releases/download/v{version}/ydm-{version}.xpi",
        "update_hash": f"sha256:{digest}",
    }]
    with open(updates_path, "w", encoding="utf-8") as f:
        json.dump(updates, f, indent=2)
        f.write("\n")

    run(["git", "add", "-A"], cwd=public)
    if run(["git", "status", "--porcelain"], cwd=public):
        run(["git", *identity, "commit", "-q", "-m",
             f"{message}\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"], cwd=public, env=GIT_UTC)
    run(["git", *identity, "push", "-q", "-u", *(["--force"] if fresh else []), "origin", "main"], cwd=public)

    if subprocess.run([GH, "release", "view", f"v{version}", "--repo", repo], env=GH_ENV, capture_output=True).returncode == 0:
        gh("release", "upload", f"v{version}", xpi, latest, "--clobber", "--repo", repo)
    else:
        gh("release", "create", f"v{version}", xpi, latest, "--repo", repo, "--target", "main", "--title", f"YDM {version}",
           "--notes", "Install or update YDM with the one-line command in the README. "
           "The extension is signed by Mozilla, and Firefox keeps it up to date.")
    print(f"Published: https://github.com/{repo}/releases/tag/v{version}")


if __name__ == "__main__":
    main()
