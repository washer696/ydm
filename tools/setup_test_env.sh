#!/bin/sh
# Sets up an official Firefox build, geckodriver and Selenium in a cache folder, for UI tests.
# The snap Firefox will not do: its portal requires a permission dialog, which fails in headless mode.
# Usage: setup_test_env.sh <cache folder>
set -eu
CACHE=$1
mkdir -p "$CACHE"
cd "$CACHE"
if [ ! -x firefox/firefox ]; then
  curl -sL "https://download.mozilla.org/?product=firefox-latest&os=linux64&lang=fr" -o firefox.tar.xz
  tar -xf firefox.tar.xz && rm firefox.tar.xz
fi
if [ ! -x geckodriver ]; then
  TAG=$(curl -s https://api.github.com/repos/mozilla/geckodriver/releases/latest | python3 -c "import json,sys; print(json.load(sys.stdin)['tag_name'])")
  curl -sL "https://github.com/mozilla/geckodriver/releases/download/$TAG/geckodriver-$TAG-linux64.tar.gz" | tar -xz
fi
if [ ! -x venv/bin/python ]; then
  python3 -m venv venv
  ./venv/bin/pip install -q selenium
fi
echo "$CACHE ready: $(./firefox/firefox --version 2>/dev/null), $(./geckodriver --version | head -1)"
