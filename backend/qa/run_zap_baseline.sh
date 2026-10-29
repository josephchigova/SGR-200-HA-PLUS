#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPORT_DIR="$SCRIPT_DIR/artifacts"
TARGET_URL="${ZAP_TARGET_URL:-http://127.0.0.1:8000}"

case "$TARGET_URL" in
  http://localhost:*|http://127.0.0.1:*|https://localhost:*|https://127.0.0.1:*) ;;
  *)
    if [[ "${ZAP_ALLOW_REMOTE:-0}" != "1" ]]; then
      printf 'Refusing to scan non-local target: %s\n' "$TARGET_URL" >&2
      printf 'For an explicitly authorized remote test only, set ZAP_ALLOW_REMOTE=1.\n' >&2
      exit 2
    fi
    ;;
esac

ZAP_BASELINE="${ZAP_BASELINE:-$(command -v zap-baseline.py || true)}"
if [[ -z "$ZAP_BASELINE" ]]; then
  candidates=(
    "${ZAP_HOME:-}/zap-baseline.py"
    "${ZAP_HOME:-}/zap-baseline.sh"
    "$HOME/Downloads/ZAP/zap-baseline.py"
    "/usr/share/zaproxy/zap-baseline.py"
  )
  for candidate in "${candidates[@]}"; do
    if [[ -f "$candidate" ]]; then
      ZAP_BASELINE="$candidate"
      break
    fi
  done
  if [[ -z "$ZAP_BASELINE" && -d "$HOME/Downloads" ]]; then
    ZAP_BASELINE="$(find "$HOME/Downloads" -maxdepth 5 -type f -name zap-baseline.py -print -quit 2>/dev/null || true)"
  fi
fi

if [[ -n "$ZAP_BASELINE" && ! -f "$ZAP_BASELINE" ]]; then
  ZAP_BASELINE="$(command -v "$ZAP_BASELINE" 2>/dev/null || true)"
fi

if [[ -z "$ZAP_BASELINE" || ! -f "$ZAP_BASELINE" ]]; then
  cat >&2 <<'EOF'
OWASP ZAP baseline runner was not found in PATH or common install locations.
Locate the downloaded ZAP directory, then run:
  ZAP_HOME="/absolute/path/to/ZAP" bash backend/qa/run_zap_baseline.sh
Or point directly at the packaged baseline runner:
  ZAP_BASELINE="/absolute/path/to/zap-baseline.py" bash backend/qa/run_zap_baseline.sh
This script runs the passive baseline (spider + passive rules), not an active attack scan.
EOF
  exit 2
fi

mkdir -p "$REPORT_DIR"
HTML_REPORT="$REPORT_DIR/zap-baseline.html"
JSON_REPORT="$REPORT_DIR/zap-baseline.json"

printf 'Target: %s\n' "$TARGET_URL"
printf 'Mode: ZAP baseline passive scan; no active scan rules are requested.\n'
printf 'HTML report: %s\nJSON report: %s\n' "$HTML_REPORT" "$JSON_REPORT"

if [[ "$ZAP_BASELINE" == *.py ]]; then
  python3 "$ZAP_BASELINE" -t "$TARGET_URL" -m 2 -r "$HTML_REPORT" -J "$JSON_REPORT"
else
  "$ZAP_BASELINE" -t "$TARGET_URL" -m 2 -r "$HTML_REPORT" -J "$JSON_REPORT"
fi
