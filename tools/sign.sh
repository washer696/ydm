#!/bin/sh
# Has Mozilla sign the extension (unlisted: it does not appear on the add-ons site) and produces an installable .xpi.
# API keys are created at https://addons.mozilla.org/developers/addon/api/key/ and stored in
# ~/.config/ytdlp-bridge/amo.env, outside the repository. Each signing needs a version never submitted before (manifest.json).
# Self-hosted extension (update_url): the linter must not apply the rules for extensions hosted by Mozilla.
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
CREDS="$HOME/.config/ytdlp-bridge/amo.env"

if [ ! -f "$CREDS" ]; then
  mkdir -p "$(dirname "$CREDS")"
  (umask 077; printf 'WEB_EXT_API_KEY=\nWEB_EXT_API_SECRET=\n' > "$CREDS")
  echo "File created: $CREDS"
  echo "Paste the 'JWT issuer' after WEB_EXT_API_KEY= and the 'JWT secret' after WEB_EXT_API_SECRET=, then run this again."
  exit 1
fi

# Read line by line rather than sourced: the file cannot run commands.
WEB_EXT_API_KEY=$(sed -n 's/^WEB_EXT_API_KEY=//p' "$CREDS" | tr -d ' \r')
WEB_EXT_API_SECRET=$(sed -n 's/^WEB_EXT_API_SECRET=//p' "$CREDS" | tr -d ' \r')
if [ -z "$WEB_EXT_API_KEY" ] || [ -z "$WEB_EXT_API_SECRET" ]; then
  echo "The keys in $CREDS are still empty"
  exit 1
fi
export WEB_EXT_API_KEY WEB_EXT_API_SECRET

cd "$ROOT"
npx --yes web-ext@8 lint --self-hosted --source-dir extension --warnings-as-errors >/dev/null
npx --yes web-ext@8 sign --channel unlisted --source-dir extension --artifacts-dir web-ext-artifacts
ls -t web-ext-artifacts/*.xpi | head -1
