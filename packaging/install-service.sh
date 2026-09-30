#!/bin/sh
# Install the sink as a systemd user service that runs from this checkout.
#   packaging/install-service.sh           install and start it
#   packaging/install-service.sh --print   show the unit it would install
set -eu
repo=$(cd "$(dirname "$0")/.." && pwd)
unit=$(sed "s#@REPO@#$repo#g" "$repo/packaging/comprehension-annotator.service")

if [ "${1:-}" = "--print" ]; then
  printf '%s\n' "$unit"
  exit 0
fi

(cd "$repo" && uv sync --quiet)
mkdir -p "$repo/library" "$HOME/.config/comprehension-annotator" "$HOME/.config/systemd/user"
printf '%s\n' "$unit" > "$HOME/.config/systemd/user/comprehension-annotator.service"
systemctl --user daemon-reload
systemctl --user enable --now comprehension-annotator
echo "sink running at http://127.0.0.1:8790/"
