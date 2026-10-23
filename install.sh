#!/bin/sh
# Installs or updates YDM on Linux and macOS:
#
#   curl -fsSL https://raw.githubusercontent.com/washer696/ydm/main/install.sh | sh
#
# 1. installs what's missing (Python, FFmpeg, and zenity + notify-send on Linux) with the system's
#    package manager: apt, dnf, pacman or Homebrew. Set YDM_NO_DEPS=1 to skip this step;
# 2. fetches YDM (the copy next to this script if there is one, else the latest code from GitHub);
# 3. runs install.py, which sets up yt-dlp, deno and the companion app, then opens the extension in Firefox.
set -eu

REPO=washer696/ydm

missing() {
  for tool in "$@"; do
    command -v "$tool" >/dev/null 2>&1 || printf '%s ' "$tool"
  done
}

install_deps() {
  if [ "$(uname)" = Darwin ]; then
    need=$(missing python3 ffmpeg)
  else
    need=$(missing python3 ffmpeg zenity notify-send)
  fi
  [ -z "$need" ] && return
  echo "Installing what YDM needs: $need"
  if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update -qq
    sudo apt-get install -y $(echo "$need" | sed 's/notify-send/libnotify-bin/')
  elif command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y $(echo "$need" | sed 's/ffmpeg/ffmpeg-free/; s/notify-send/libnotify/')
  elif command -v pacman >/dev/null 2>&1; then
    sudo pacman -S --needed --noconfirm $(echo "$need" | sed 's/python3/python/; s/notify-send/libnotify/')
  elif command -v brew >/dev/null 2>&1; then
    brew install $(echo "$need" | sed 's/python3/python/')
  else
    echo "Please install these first, then run this again: $need"
    exit 1
  fi
}

[ -n "${YDM_NO_DEPS:-}" ] || install_deps

src=${YDM_SRC:-}
if [ -z "$src" ] && [ -f "$(dirname "$0")/install.py" ]; then
  src=$(cd "$(dirname "$0")" && pwd)
fi
if [ -z "$src" ]; then
  src=$(mktemp -d)
  trap 'rm -rf "$src"' EXIT
  echo "Downloading YDM..."
  curl -fsSL "https://github.com/$REPO/archive/refs/heads/main.tar.gz" | tar -xz -C "$src" --strip-components=1
fi

python3 "$src/install.py" "$@"
