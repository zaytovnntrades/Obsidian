#!/usr/bin/env bash
# remove-bg.sh — one-click background removal with rembg
#
# Usage:
#   ./remove-bg.sh                     # in_folder -> out_folder, model u2net
#   ./remove-bg.sh photo.jpg           # single image -> photo_nobg.png
#   ./remove-bg.sh -a                  # smoother edges (alpha matting)
#   ./remove-bg.sh -w                  # watch in_folder, process new images as they arrive
#   ./remove-bg.sh -m birefnet-general # best quality (needs ~16 GB RAM)
#   ./remove-bg.sh -i my_pics -o done  # custom folders
#
# Models: u2net (default) | u2netp (tiny/fast) | u2net_human_seg (people)
#         isnet-anime (illustrations) | birefnet-general (best, heavy)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$SCRIPT_DIR/.rembg-env"
MODEL="u2net"
IN_DIR="$SCRIPT_DIR/in_folder"
OUT_DIR="$SCRIPT_DIR/out_folder"
EXTRA=()
WATCH=0

usage() { sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

while getopts ":m:i:o:awh" opt; do
  case "$opt" in
    m) MODEL="$OPTARG" ;;
    i) IN_DIR="$OPTARG" ;;
    o) OUT_DIR="$OPTARG" ;;
    a) EXTRA+=("-a") ;;
    w) WATCH=1 ;;
    h) usage 0 ;;
    *) echo "Unknown option: -$OPTARG" >&2; usage 1 ;;
  esac
done
shift $((OPTIND - 1))

# 1. One-time setup: private Python environment so nothing touches your system Python
if [[ ! -x "$VENV/bin/rembg" ]]; then
  PY="$(command -v python3 || command -v python || true)"
  [[ -z "$PY" ]] && { echo "Python 3 not found. Install it from https://python.org first." >&2; exit 1; }
  echo "First run: setting up rembg (one time, ~1-2 min)..."
  "$PY" -m venv "$VENV"
  if command -v nvidia-smi >/dev/null 2>&1; then EXTRAS="cli,gpu"; else EXTRAS="cli,cpu"; fi
  "$VENV/bin/pip" install -q --upgrade pip
  "$VENV/bin/pip" install -q "rembg[$EXTRAS]"
  echo "Setup done ($EXTRAS)."
fi
REMBG="$VENV/bin/rembg"

# 2. Single-image mode
if [[ $# -gt 0 ]]; then
  for f in "$@"; do
    [[ -f "$f" ]] || { echo "Not found: $f" >&2; continue; }
    out="${f%.*}_nobg.png"
    "$REMBG" i -m "$MODEL" ${EXTRA[@]+"${EXTRA[@]}"} "$f" "$out"
    echo "✔ $f -> $out"
  done
  exit 0
fi

# 3. Folder mode
mkdir -p "$IN_DIR" "$OUT_DIR"
if [[ $WATCH -eq 0 ]] && [[ -z "$(ls -A "$IN_DIR" 2>/dev/null)" ]]; then
  echo "Put your images in: $IN_DIR  — then run this script again."
  exit 0
fi

[[ $WATCH -eq 1 ]] && { EXTRA+=("-w"); echo "Watching $IN_DIR (Ctrl+C to stop)..."; }
echo "Model: $MODEL | $IN_DIR -> $OUT_DIR"
"$REMBG" p -m "$MODEL" ${EXTRA[@]+"${EXTRA[@]}"} "$IN_DIR" "$OUT_DIR"
echo "✔ Done. Transparent PNGs are in: $OUT_DIR"
