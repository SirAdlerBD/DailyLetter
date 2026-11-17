#!/usr/bin/env bash
# Bring DailyLetter on this server up to date with GitHub, in one command:
#   ~/DailyLetter/deploy/update.sh
set -euo pipefail
cd "$(dirname "$0")/.."

before=$(git rev-parse --short HEAD)
git pull --ff-only --quiet
after=$(git rev-parse --short HEAD)

if [ "$before" = "$after" ] && [ "${1:-}" != "--force" ]; then
  echo "DailyLetter is al up-to-date ($after)."
  exit 0
fi

# New or changed dependencies first, then our own code, always fresh (the version number rarely changes).
.venv/bin/pip install --quiet .
.venv/bin/pip install --quiet --force-reinstall --no-deps .
.venv/bin/dailyletter init
systemctl --user restart dailyletter-web.service

echo "DailyLetter bijgewerkt: $before -> $after"
git log --oneline "$before..$after"
