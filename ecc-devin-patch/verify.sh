#!/usr/bin/env bash
# Verify the Devin bridge inside an ECC checkout, without installing Devin:
#
#   ./verify.sh /path/to/ECC
#
# Runs the structural validator plus a real end-to-end pass through
# hooks/devin/dispatch.mjs: an ECC hook must actually block a destructive exec
# and stay silent for a harmless one.
set -euo pipefail

TARGET="${1:-.}"
TARGET="$(cd "$TARGET" && pwd)"
cd "$TARGET"

[[ -f hooks/devin/validate.mjs ]] || { echo "run apply.sh first" >&2; exit 1; }

echo "== structural checks"
node hooks/devin/validate.mjs

echo
echo "== end-to-end: dispatch -> real ECC hooks"

SCRATCH="$(mktemp -d)"
# GateGuard keeps per-session state, so a fixed id would make this test depend on
# whatever a previous run left behind. Use a fresh session per invocation.
SESSION="verify-$(date +%s)-$$"
trap 'rm -rf "$SCRATCH"' EXIT
git -C "$SCRATCH" init -q
mkdir -p "$SCRATCH/src"
printf 'console.log(1)\n' > "$SCRATCH/src/b.ts"

dispatch() {
  local event="$1" payload="$2"
  (
    cd "$SCRATCH"
    printf '%s' "$payload" | \
      DEVIN_PLUGIN_ROOT="$TARGET" CLAUDE_PLUGIN_ROOT="$TARGET" CLAUDE_PROJECT_DIR="$SCRATCH" \
      node "$TARGET/hooks/devin/dispatch.mjs" "$event"
  )
}

fail=0

payload() { printf '%s' "$1"; }

blocked="$(dispatch PreToolUse "$(payload '{"hook_event_name":"PreToolUse","tool_name":"exec","tool_input":{"command":"rm -rf /"},"session_id":"'"$SESSION"'"}')")"
if grep -q '"decision":"block"' <<<"$blocked"; then
  echo "PASS  destructive exec is blocked and translated to Devin's contract"
else
  echo "FAIL  destructive exec was not blocked (got: ${blocked:-<empty>})"
  fail=1
fi

quiet="$(dispatch PreToolUse "$(payload '{"hook_event_name":"PreToolUse","tool_name":"exec","tool_input":{"command":"ls"},"session_id":"'"$SESSION"'"}')")"
if [[ -z "$quiet" ]]; then
  echo "PASS  harmless exec passes through silently"
else
  echo "WARN  harmless exec produced output: ${quiet:0:200}"
fi

post="$(dispatch PostToolUse "$(payload '{"hook_event_name":"PostToolUse","tool_name":"edit","tool_input":{"file_path":"'"$SCRATCH"'/src/b.ts"},"tool_response":{"success":true},"session_id":"'"$SESSION"'"}')")"
if grep -q 'console.log' <<<"$post"; then
  echo "PASS  PostToolUse edit feeds ECC's console.log warning back as additionalContext"
else
  echo "WARN  PostToolUse edit produced no context (ok if ECC's console.log hook is disabled)"
fi

echo
if [[ "$fail" = "0" ]]; then
  echo "verification passed"
else
  echo "verification failed"
  exit 1
fi
