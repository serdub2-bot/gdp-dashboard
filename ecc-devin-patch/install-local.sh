#!/usr/bin/env bash
# Build a ready-to-install Devin plugin from upstream ECC + this patch.
#
#   ./install-local.sh [target-dir]      # default: ./ecc-devin-plugin
#
# Then, in the target dir:
#   devin plugins install --local .
#   devin plugins info ecc
#
# Local plugins are linked to the folder, so later edits apply to new sessions
# without reinstalling.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="${1:-$PWD/ecc-devin-plugin}"

if [[ -e "$TARGET" ]]; then
  echo "target already exists: $TARGET" >&2
  echo "remove it or pass another directory" >&2
  exit 1
fi

echo "Cloning ECC into $TARGET …"
git clone --depth 1 https://github.com/affaan-m/ECC.git "$TARGET"

echo "Applying the Devin patch …"
"$HERE/apply.sh" "$TARGET" --no-release-patch >/dev/null

echo "Verifying …"
"$HERE/verify.sh" "$TARGET" > /dev/null && echo "ok"

cat <<EOF

Ready: $TARGET

  cd "$TARGET"
  devin plugins install --local .     # or: devin plugins install --local "$TARGET"
  devin plugins info ecc              # expect a hooks line, e.g. hooks.json (6 events)

Notes
  * Devin loads plugin hooks in local sessions only (CLI and Devin Desktop).
  * Cloud sessions get skills/rules/agents, never plugin hooks — by design.
  * If the old GitHub-sourced copy is installed, remove it first:
      devin plugins remove ecc
EOF
