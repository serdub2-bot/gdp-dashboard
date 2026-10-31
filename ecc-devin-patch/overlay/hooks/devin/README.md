# Devin hooks adapter

ECC's hook graph lives in `hooks/hooks.json` and is written for Claude Code. Devin
CLI loads plugin hooks from a **root `hooks.json`** in its own v1 format: Claude
tool names (`Bash`, `Write`, `Edit`, …) never fire, `PostToolUseFailure` and
`PreCompact` do not exist, and a `hookSpecificOutput.permissionDecision: "deny"`
is not a block. Installing ECC into Devin used to surface a "malformed hook"
warning and silently run no hooks at all.

This directory is the adapter. It adds no policy of its own: it selects ECC's
existing hooks, feeds them the payload shape they already parse, and translates
their result back into Devin's contract.

```
Devin event ──> root hooks.json (6 entries) ──> hooks/devin/dispatch.mjs
                                                     │  reads hooks/hooks.json (unchanged)
                                                     │  Devin payload -> Claude payload
                                                     ├─> ECC hook command (node scripts/hooks/…)
                                                     └─> Claude output -> Devin output
```

## Mapping

| Devin event | ECC event | Notes |
| --- | --- | --- |
| `PreToolUse` | `PreToolUse` | matcher tested against the mapped Claude tool name |
| `PostToolUse` | `PostToolUse` | |
| `UserPromptSubmit` | `UserPromptSubmit` | |
| `SessionStart` | `SessionStart` | context injected via `additionalContext` |
| `End`/`Stop` | `Stop` | |
| `SessionEnd` | `SessionEnd` | |
| — | `PostToolUseFailure` | no Devin equivalent, not run |
| `PostCompaction` | `PreCompact` | **deliberately not mapped**: Devin fires after compaction, ECC's hook saves state before it |

Tool names (`hooks/devin/dispatch.mjs`, `TOOL_MAP`): `exec`→`Bash`, `write`→`Write`,
`edit`/`apply_patch`→`Edit`, `read`→`Read`, `grep`→`Grep`, `glob`→`Glob`,
`webfetch`→`WebFetch`, `run_subagent`/`read_subagent`→`Task`, `skill`→`Skill`,
`todo_write`→`TodoWrite`, `notebook_edit`→`NotebookEdit`, `get_output`→`BashOutput`,
`kill_shell`→`KillShell`, `mcp_call_tool`→`mcp__call_tool`.

Output translation:

| ECC (Claude) output | Devin output |
| --- | --- |
| `exit 2` | `{"decision":"block","reason": …}` |
| `{"decision":"block", …}` | unchanged |
| `hookSpecificOutput.permissionDecision: "deny"` | `{"decision":"block","reason": <reason>}` |
| `hookSpecificOutput.additionalContext`, `systemMessage`, warn-only stderr | `{"hookSpecificOutput":{"hookEventName": …, "additionalContext": …}}` |
| `exit 1` / other | logged, fail open (Devin's own policy) |

`[Hook] bootstrap: …` diagnostics on stderr are stripped — they are terminal noise,
not agent context.

## Files

| File | Role |
| --- | --- |
| `build-hooks-json.mjs` | single source of truth for the root `hooks.json`; `--check` for CI |
| `dispatch.mjs` | the runtime described above |
| `validate.mjs` | schema, freshness, wiring and translation checks; runs no Devin |

`hooks.json` is generated — edit `build-hooks-json.mjs` and re-run it, never the JSON.

## Usage

```bash
node hooks/devin/build-hooks-json.mjs          # regenerate hooks.json
node hooks/devin/build-hooks-json.mjs --check  # CI: fail if stale
node hooks/devin/validate.mjs                  # all checks
```

Diagnostics:

```bash
# what would run for a given Devin payload
echo '{"tool_name":"exec","tool_input":{"command":"git status"}}' \
  | DEVIN_PLUGIN_ROOT="$PWD" node hooks/devin/dispatch.mjs PreToolUse --list

# verbose per-hook selection and timing
ECC_DEVIN_DEBUG=1 ...

# kill switch, e.g. for a session where hooks get in the way
ECC_HOOKS=0 ...
```

## Limitations (Devin's, not the adapter's)

* Devin loads plugin hooks in **local sessions only** (CLI and Devin Desktop), and
  they are **best effort / fail open** — cloud sessions never run them. Skills,
  rules, subagents and MCP servers are unaffected.
* Devin's `timeout` is seconds, as is Claude's `timeout` in `hooks/hooks.json`;
  the adapter converts both to `spawnSync`'s milliseconds.
* ECC hooks flagged `async: true` have no Devin equivalent; they run detached with
  output discarded, so they never block a Devin session.
* A hook command receives the plugin root as `DEVIN_PLUGIN_ROOT`
  (`CLAUDE_PLUGIN_ROOT` fallback), which is why the root `hooks.json` entries do
  not hardcode any path.
