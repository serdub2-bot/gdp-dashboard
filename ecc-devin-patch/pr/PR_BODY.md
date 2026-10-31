# feat(devin): native Devin plugin manifest and hooks bridge

## Why

Installing `affaan-m/ECC` into Devin CLI / Devin Desktop shows:

```
⚠ Hook malformed — https://github.com/affaan-m/ECC
```

and no ECC hook actually fires. Two independent causes:

1. **No native manifest.** Devin falls back to `.claude-plugin/plugin.json` and then
   validates `hooks/hooks.json` against its own v1 contract. That file is Claude
   Code's: matchers are `Bash` / `PowerShell` / `Write` / `Edit`, it uses
   `PostToolUseFailure` and `PreCompact` (Devin has neither), `async: true`
   (Devin has no async hooks) and blocks with
   `hookSpecificOutput.permissionDecision: "deny"` (Devin only understands
   `decision: "block"` / exit 2). The validator rejects the file, the warning
   appears, and the whole graph is skipped.
2. **Nothing listens on Devin's events.** Even a valid Claude hook set would never
   fire: Devin calls its tools `exec` / `write` / `edit` / …, so every matcher misses.

The fix belongs in the repository, not in the user's config.

## What this PR adds

| File | Purpose |
| --- | --- |
| `.devin-plugin/plugin.json` | native Devin manifest (`name`, `version`, `description`, `skills`); Devin's manifest precedence is `.devin-plugin/plugin.json` > `.claude-plugin/plugin.json` > root `plugin.json`, so this ends the fallback path that produces the warning |
| `hooks.json` (repo root) | Devin hook file: one entry per Devin event (`SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `Stop`, `SessionEnd`), each a single `command` call into the dispatcher |
| `hooks/devin/dispatch.mjs` | adapter: reads the unchanged `hooks/hooks.json`, normalizes Devin's payload into the Claude payload ECC's scripts already parse (tool-name map `exec`→`Bash`, …), runs the matching hooks with `CLAUDE_PLUGIN_ROOT` set, and translates the result back into Devin's contract |
| `hooks/devin/build-hooks-json.mjs` | generator for the root `hooks.json`; `--check` for CI |
| `hooks/devin/validate.mjs` | schema + freshness + wiring + translation checks, no Devin needed |
| `hooks/devin/README.md` | mapping tables, limitations, debugging |
| `scripts/release.sh` | `.devin-plugin/plugin.json` added to the version-bump and `git add` lists |

`hooks/hooks.json` is **not** modified: Claude Code, Codex, Cursor and the other
harnesses keep the exact graph they have today.

### Design notes

* **Root `hooks.json` holds no policy.** It is six entries; every decision lives in
  `hooks/hooks.json`. Adding or reordering ECC hooks needs no Devin-side change.
* **No path is hardcoded.** Devin exports `DEVIN_PLUGIN_ROOT` to plugin hook
  commands (CLI changelog: "Hooks contributed by a plugin also get
  DEVIN_PLUGIN_ROOT"); each entry resolves it inside `node -e`, which is portable
  across `sh`, `cmd` and PowerShell, and exits 0 when the variable is absent
  instead of pointing at `/hooks/devin/dispatch.mjs`.
* **The generated file is checked in** and `--check` guards it, mirroring the
  existing `hooks.metadata.json` fingerprint discipline.
* **Timeouts.** `hooks/hooks.json` uses seconds (5 / 10) and Devin's `timeout` is
  also seconds; the dispatcher converts to milliseconds for `spawnSync`.
* **`async: true` hooks** run detached with output discarded, since Devin has no
  async hooks and blocking on build analysis would be a regression.
* **`PreCompact` is not mapped to `PostCompaction`.** Devin fires after compaction,
  ECC's hook persists state before it; mapping them would corrupt the intent.
  `PostToolUseFailure` has no Devin equivalent and is documented as not running.
* **`ECC_HOOKS=0`** disables the bridge for a session, matching how ECC users
  already opt out elsewhere.

## Verification

Run against a sparse checkout of this repo's `main` on Node 22 (macOS/Linux):

```
$ node hooks/devin/validate.mjs
PASS  hooks.json: valid JSON with documented event keys  (6 events)
PASS  hooks.json: matches build-hooks-json.mjs output  (in sync)
PASS  hooks/hooks.json: ECC graph is readable  (PreToolUse, UserPromptSubmit, PreCompact, SessionStart, PostToolUse, PostToolUseFailure, Stop, SessionEnd)
PASS  dispatch: selects ECC hooks for every supported event  (SessionStart=2 UserPromptSubmit=1 PreToolUse=4 PostToolUse=2 Stop=8 SessionEnd=1)
PASS  dispatch: hooks referenced by the graph exist on disk  (4 command(s) resolve)
PASS  dispatch: ECC_HOOKS=0 is a no-op  (silent)
PASS  dispatch: unmapped events are ignored  (ignored)
all checks passed
```

End-to-end, through the real ECC hooks (not fixtures):

```
$ echo '{"tool_name":"exec","tool_input":{"command":"rm -rf /"}}' | \
    DEVIN_PLUGIN_ROOT=$PWD node hooks/devin/dispatch.mjs PreToolUse
{"decision":"block","reason":"[Fact-Forcing Gate]\n\nDestructive command detected. …"}

$ echo '{"tool_name":"exec","tool_input":{"command":"git status"}}' | \
    DEVIN_PLUGIN_ROOT=$PWD node hooks/devin/dispatch.mjs PreToolUse
(no output, ~120 ms)

$ echo '{"tool_name":"edit","tool_input":{"file_path":"src/b.ts"}}' | \
    DEVIN_PLUGIN_ROOT=$PWD node hooks/devin/dispatch.mjs PostToolUse
{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":"[Hook] WARNING: console.log found in …"}}
```

Timing per event, cold cache, Node 22: `PreToolUse` 90–120 ms, `PostToolUse` ~115 ms,
`UserPromptSubmit` ~118 ms, `SessionStart` ~370 ms, `Stop` ~460 ms, `SessionEnd` ~106 ms.

Not verifiable from CI: whether Devin *displays* the warning for a plugin after a
reindex. The local `devin plugins info ecc` check is the acceptance step:

```
Hooks   hooks.json (6 events)          # expected after this PR
```

## Upstream caveats to state in the README

* Devin loads plugin hooks in **local sessions only** (CLI + Devin Desktop) and
  they are **best effort / fail open** by Devin's own design — cloud sessions run
  no plugin hooks at all. This PR makes hooks load and fire where they can; it
  cannot make them guaranteed in cloud.
* Devin's docs describe the standalone project file as `.devin/hooks.v1.json`;
  plugin hooks are the root `hooks.json` described in the plugins overview.

## Follow-ups (not in this PR)

* `scripts/lib/harness-adapter-compliance.js` — add a `devin` entry
  (`Adapter-backed`, skills/rules/agents first-class, hooks best-effort and
  local-only, `source_docs: .devin-plugin/plugin.json`, `hooks/devin/README.md`).
* `scripts/ci/catalog.js` / `scripts/harness-audit.js` if their manifest lists are
  exhaustive rather than directory-derived.
* Tagging releases stays the user-facing way to clear Devin's
  "plugin source not pinned" notice.
