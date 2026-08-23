#!/usr/bin/env bash
# run_clap_wsl.sh — CLAP-score every take in a session folder.
# Usage: scripts/run_clap_wsl.sh <session-dir-inside-wsl>
# Runs under the WSL venv (torch lives there). Graceful per-take degradation.
set -uo pipefail
SESSION="${1:?usage: run_clap_wsl.sh <session-dir>}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY=/root/agentic-music-venv/bin/python

shopt -s nullglob
wavs=("$SESSION"/takes/take-*.wav)
if [[ ${#wavs[@]} -eq 0 ]]; then
  echo "no takes found in $SESSION/takes" >&2
  exit 2
fi
for wav in "${wavs[@]}"; do
  "$PY" "$HERE/clap_score.py" --caption "$SESSION/caption.md" --audio "$wav"
done
