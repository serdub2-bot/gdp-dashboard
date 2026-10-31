#!/usr/bin/env bash
# Apply the ECC -> Devin compatibility patch to an ECC checkout.
#
#   ./apply.sh /path/to/ECC [--no-release-patch] [--dry-run]
#
# Copies the plugin files (manifest, root hooks.json, hooks/devin/*) and applies
# the release.sh version-bump patch. Idempotent: re-running overwrites the same
# files with the same content.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="${1:-}"
shift || true

WITH_RELEASE_PATCH=1
DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --no-release-patch) WITH_RELEASE_PATCH=0 ;;
    --dry-run) DRY_RUN=1 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

if [[ -z "$TARGET" ]]; then
  echo "usage: $0 /path/to/ECC [--no-release-patch] [--dry-run]" >&2
  exit 2
fi

TARGET="$(cd "$TARGET" && pwd)"
[[ -d "$TARGET/.git" ]] || { echo "not a git checkout: $TARGET" >&2; exit 1; }
[[ -f "$TARGET/hooks/hooks.json" ]] || { echo "no hooks/hooks.json in $TARGET — is this ECC?" >&2; exit 1; }

say() { printf '  %s\n' "$*"; }

echo "Applying ECC -> Devin patch to $TARGET"

if [[ "$DRY_RUN" = "1" ]]; then
  say "would create .devin-plugin/plugin.json"
  say "would create hooks.json"
  say "would create hooks/devin/{dispatch,build-hooks-json,validate}.mjs, hooks/devin/README.md"
  [[ "$WITH_RELEASE_PATCH" = "1" ]] && say "would apply patches/0001-release-sh-version-bump.patch"
  exit 0
fi

mkdir -p "$TARGET/.devin-plugin" "$TARGET/hooks/devin"
cp "$HERE/overlay/.devin-plugin/plugin.json" "$TARGET/.devin-plugin/plugin.json"
cp "$HERE/overlay/hooks.json" "$TARGET/hooks.json"
cp "$HERE"/overlay/hooks/devin/*.mjs "$TARGET/hooks/devin/"
cp "$HERE/overlay/hooks/devin/README.md" "$TARGET/hooks/devin/README.md"

say "created .devin-plugin/plugin.json"
say "created hooks.json"
say "created hooks/devin/ (dispatch, build, validate, README)"

if [[ "$WITH_RELEASE_PATCH" = "1" ]]; then
  PATCH="$HERE/patches/0001-release-sh-version-bump.patch"
  if git -C "$TARGET" apply --check "$PATCH" 2>/dev/null; then
    git -C "$TARGET" apply "$PATCH"
    say "patched scripts/release.sh (version bump tracks .devin-plugin/plugin.json)"
  elif git -C "$TARGET" apply --reverse --check "$PATCH" 2>/dev/null; then
    say "scripts/release.sh already patched, skipping"
  else
    say "WARNING: could not apply release.sh patch (upstream changed?) — apply manually, see patches/"
  fi
fi

echo
echo "Next:"
echo "  cd $TARGET"
echo "  node hooks/devin/validate.mjs"
echo "  git status --short"
echo "  git checkout -b feat/devin-native-plugin && git add -A && git commit -m 'feat(devin): native plugin manifest and hooks bridge'"
