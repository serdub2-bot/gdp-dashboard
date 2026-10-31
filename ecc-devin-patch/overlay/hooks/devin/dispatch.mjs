#!/usr/bin/env node
/**
 * ECC -> Devin hooks bridge.
 *
 * ECC ships one hook graph (`hooks/hooks.json`) written for Claude Code:
 * tool names are Bash/Write/Edit/..., blocking is `exit 2` or
 * `hookSpecificOutput.permissionDecision: "deny"`, and the entry list is keyed
 * by Claude event names.
 *
 * Devin CLI reads plugin hooks from a root `hooks.json` in its own v1 shape and
 * calls its tools `exec`/`write`/`edit`/... ; it blocks on `decision: "block"`
 * (or exit 2) and injects text through `hookSpecificOutput.additionalContext`.
 * It also has no PreToolUse-time `permissionDecision` and no
 * PostToolUseFailure/PreCompact events.
 *
 * This dispatcher is the only new runtime: Devin calls it once per event, it
 * selects the matching entries out of the unchanged `hooks/hooks.json`,
 * normalizes the Devin payload into the Claude payload ECC's scripts already
 * parse, runs them, and translates their output back into Devin's contract.
 *
 * Usage (from a Devin root hooks.json entry):
 *   node hooks/devin/dispatch.mjs <EventName>
 *   node hooks/devin/dispatch.mjs <EventName> --list     # what would run
 *
 * Env:
 *   DEVIN_PLUGIN_ROOT / CLAUDE_PLUGIN_ROOT  plugin root (Devin exports both)
 *   CLAUDE_PROJECT_DIR / DEVIN_PROJECT_DIR  project root for cwd
 *   ECC_HOOKS=0                             disable the bridge
 *   ECC_DEVIN_DEBUG=1                       log selection details to stderr
 */
import { spawn, spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PLUGIN_ROOT =
  process.env.DEVIN_PLUGIN_ROOT ||
  process.env.CLAUDE_PLUGIN_ROOT ||
  path.resolve(HERE, '..', '..');

const HOOKS_FILE = path.join(PLUGIN_ROOT, 'hooks', 'hooks.json');
const DEBUG = process.env.ECC_DEVIN_DEBUG === '1';

/** Devin lifecycle events the bridge runs on. */
const SUPPORTED_EVENTS = new Set([
  'PreToolUse',
  'PostToolUse',
  'UserPromptSubmit',
  'SessionStart',
  'SessionEnd',
  'Stop',
]);

/** Devin event -> ECC/Claude event. Everything else has no equivalent. */
const EVENT_MAP = {
  PreToolUse: 'PreToolUse',
  PostToolUse: 'PostToolUse',
  UserPromptSubmit: 'UserPromptSubmit',
  SessionStart: 'SessionStart',
  SessionEnd: 'SessionEnd',
  Stop: 'Stop',
  // Devin fires PostCompaction *after* compaction; ECC's PreCompact hook saves
  // state *before* it, so mapping them would be wrong. PermissionRequest has
  // no ECC equivalent either (ECC gates inside PreToolUse).
};

/** Devin tool_name -> Claude tool_name (what ECC's matchers expect). */
const TOOL_MAP = {
  exec: 'Bash',
  get_output: 'BashOutput',
  write_to_process: 'BashOutput',
  kill_shell: 'KillShell',
  write: 'Write',
  edit: 'Edit',
  apply_patch: 'Edit',
  notebook_edit: 'NotebookEdit',
  notebook_read: 'NotebookRead',
  read: 'Read',
  grep: 'Grep',
  glob: 'Glob',
  webfetch: 'WebFetch',
  run_subagent: 'Task',
  read_subagent: 'Task',
  skill: 'Skill',
  todo_write: 'TodoWrite',
  exit_plan_mode: 'ExitPlanMode',
  mcp_call_tool: 'mcp__call_tool',
};

/** Events where Devin renders injected context. */
const CONTEXT_EVENTS = new Set(['UserPromptSubmit', 'SessionStart', 'PostToolUse', 'PreToolUse']);

const DEFAULT_TIMEOUT_MS = 60_000;
const MAX_CONTEXT_CHARS = 8_000;

function log(msg) {
  if (DEBUG) process.stderr.write(`[ecc:devin] ${msg}\n`);
}

function readStdin() {
  try {
    return readFileSync(0, 'utf8');
  } catch {
    return '';
  }
}

function projectDir(payload) {
  return (
    process.env.CLAUDE_PROJECT_DIR ||
    process.env.DEVIN_PROJECT_DIR ||
    payload.cwd ||
    process.cwd()
  );
}

/** Map the Devin payload onto the Claude-shaped payload ECC scripts parse. */
function toClaudePayload(devinEvent, payload) {
  const claude = { ...payload };
  claude.hook_event_name = EVENT_MAP[devinEvent] || devinEvent;
  claude.cwd = projectDir(payload);
  if (typeof payload.tool_name === 'string') {
    const mapped = TOOL_MAP[payload.tool_name];
    claude.devin_tool_name = payload.tool_name;
    claude.tool_name = mapped || payload.tool_name;
  }
  if (claude.permission_mode === undefined) claude.permission_mode = 'default';
  if (claude.transcript_path === undefined) claude.transcript_path = '';
  return claude;
}

function loadHookGraph() {
  const raw = JSON.parse(readFileSync(HOOKS_FILE, 'utf8'));
  return raw.hooks || raw;
}

function matches(matcher, toolName) {
  if (!matcher || matcher === '.*') return true;
  try {
    return new RegExp(`^(?:${matcher})$`).test(toolName ?? '');
  } catch {
    log(`invalid matcher ${JSON.stringify(matcher)}, skipping entry`);
    return false;
  }
}

function selectEntries(graph, claudeEvent, toolName) {
  const entries = Array.isArray(graph[claudeEvent]) ? graph[claudeEvent] : [];
  const selected = [];
  for (const group of entries) {
    const groupMatcher = group.matcher ?? '';
    if (toolName !== undefined && !matches(groupMatcher, toolName)) continue;
    for (const hook of group.hooks || []) {
      if (hook.type && hook.type !== 'command') continue;
      selected.push({
        matcher: groupMatcher,
        command: hook.command,
        timeout: hook.timeout,
        async: hook.async === true,
      });
    }
  }
  return selected;
}

function shorten(textValue, max = 120) {
  const flat = String(textValue).replace(/\s+/g, ' ').trim();
  return flat.length > max ? `${flat.slice(0, max)}…` : flat;
}

/**
 * ECC/Claude hook `timeout` values are seconds (5, 10, ...). Devin's `timeout`
 * is seconds too, but spawnSync wants milliseconds.
 */
function toTimeoutMs(seconds) {
  const value = Number(seconds);
  if (!Number.isFinite(value) || value <= 0) return DEFAULT_TIMEOUT_MS;
  return Math.round(value * 1000);
}

function runCommand(command, payload, cwd, timeoutMs) {
  const env = {
    ...process.env,
    CLAUDE_PLUGIN_ROOT: PLUGIN_ROOT,
    DEVIN_PLUGIN_ROOT: PLUGIN_ROOT,
    CLAUDE_PROJECT_DIR: cwd,
    DEVIN_PROJECT_DIR: cwd,
    ECC_HOOK_SOURCE: 'devin',
  };
  return spawnSync(command, {
    shell: true,
    input: payload,
    cwd,
    env,
    encoding: 'utf8',
    timeout: timeoutMs,
    maxBuffer: 16 * 1024 * 1024,
  });
}

function runDetached(command, payload, cwd) {
  // ECC marks a few hooks async (build analysis, session-end bookkeeping).
  // Devin has no async flag, so keep them non-blocking here: detached child,
  // payload on stdin, output discarded.
  const env = {
    ...process.env,
    CLAUDE_PLUGIN_ROOT: PLUGIN_ROOT,
    DEVIN_PLUGIN_ROOT: PLUGIN_ROOT,
    CLAUDE_PROJECT_DIR: cwd,
    DEVIN_PROJECT_DIR: cwd,
    ECC_HOOK_SOURCE: 'devin',
  };
  try {
    const child = spawn(command, {
      shell: true,
      cwd,
      env,
      detached: true,
      stdio: ['pipe', 'ignore', 'ignore'],
    });
    child.on('error', (error) => log(`async hook failed to start: ${error.message}`));
    child.stdin.on('error', () => {});
    child.stdin.end(payload);
    child.unref();
    return child;
  } catch (error) {
    log(`async hook failed to start: ${error.message}`);
    return null;
  }
}

/**
 * ECC's bootstrap prints diagnostics on stderr ("[Hook] bootstrap: ..."). They
 * are useful in a terminal, but injecting them into the agent's context is pure
 * noise, so drop them before anything is forwarded.
 */
const NOISE_PATTERNS = [/^\[Hook\] bootstrap:/i, /^\s*$/];

function clean(text) {
  if (!text) return '';
  return String(text)
    .replace(/\u001b\[[0-9;]*m/g, '')
    .split('\n')
    .filter((line) => !NOISE_PATTERNS.some((pattern) => pattern.test(line)))
    .join('\n')
    .trim();
}

/** Translate one ECC hook result into {block?, reason?, context?}. */
function translate(result, devinEvent, timeoutMs) {
  const stdout = clean(result.stdout).trim() ? String(result.stdout).trim() : '';
  const stderr = clean(result.stderr);

  if (result.error && result.error.code === 'ETIMEDOUT') {
    return {
      context: `[ecc] hook timed out after ${Math.round(timeoutMs / 1000)}s (fail-open)`,
    };
  }

  if (result.status === 2) {
    return { block: true, reason: stderr || stdout || 'Blocked by an ECC hook.' };
  }

  if (stdout.startsWith('{')) {
    let json;
    try {
      json = JSON.parse(stdout);
    } catch {
      json = null;
    }
    if (json) {
      const specific = json.hookSpecificOutput || {};
      if (json.decision === 'block' || specific.permissionDecision === 'deny') {
        return {
          block: true,
          reason: json.reason || specific.permissionDecisionReason || stderr || 'Blocked by an ECC hook.',
        };
      }
      const chunks = [];
      const context = clean(specific.additionalContext || '');
      if (context) chunks.push(context);
      if (json.systemMessage) chunks.push(clean(json.systemMessage));
      if (stderr) chunks.push(stderr);
      if (chunks.length) return { context: chunks.join('\n') };
      return {};
    }
  }

  if (result.status !== 0) {
    // Devin treats any exit other than 0/2 as a logged error. Stay fail-open,
    // but surface a readable line instead of a stack trace.
    log(`hook exited ${result.status}: ${shorten(stderr || stdout)}`);
    return {};
  }

  const chunks = [];
  if (CONTEXT_EVENTS.has(devinEvent)) {
    if (stdout) chunks.push(stdout);
    if (stderr) chunks.push(stderr);
  }
  return chunks.length ? { context: chunks.join('\n') } : {};
}

function emit(output) {
  if (output && Object.keys(output).length) process.stdout.write(`${JSON.stringify(output)}\n`);
}

function main(argv) {
  const devinEvent = argv[2];
  const listOnly = argv.includes('--list') || argv.includes('--dry-run');

  if (process.env.ECC_HOOKS === '0') {
    log('disabled via ECC_HOOKS=0');
    return 0;
  }
  if (!devinEvent || !SUPPORTED_EVENTS.has(devinEvent)) {
    log(`unsupported event ${JSON.stringify(devinEvent)}`);
    return 0;
  }

  let payload = {};
  const stdin = readStdin();
  if (stdin.trim()) {
    try {
      payload = JSON.parse(stdin);
    } catch {
      payload = {};
    }
  }

  const claudeEvent = EVENT_MAP[devinEvent];
  const claudePayload = toClaudePayload(devinEvent, payload);
  const toolName = typeof payload.tool_name === 'string' ? claudePayload.tool_name : undefined;

  let graph;
  try {
    graph = loadHookGraph();
  } catch (error) {
    log(`cannot read ${HOOKS_FILE}: ${error.message}`);
    return 0; // fail open
  }

  const selected = selectEntries(graph, claudeEvent, toolName);
  log(`${devinEvent}${toolName ? ` tool=${toolName}` : ''} -> ${selected.length} ECC hook(s)`);

  if (listOnly) {
    emit({
      event: devinEvent,
      ecc_event: claudeEvent,
      tool_name: toolName ?? null,
      hooks: selected.map((entry) => ({ matcher: entry.matcher, command: shorten(entry.command, 200) })),
    });
    return 0;
  }

  if (!selected.length) return 0;

  const cwd = claudePayload.cwd;
  const stdinPayload = JSON.stringify(claudePayload);
  const contexts = [];
  let block = null;

  for (const entry of selected) {
    if (entry.async) {
      log(`dispatching async ECC hook: ${shorten(entry.command)}`);
      runDetached(entry.command, stdinPayload, cwd);
      continue;
    }
    const startedAt = Date.now();
    const timeoutMs = toTimeoutMs(entry.timeout);
    const result = runCommand(entry.command, stdinPayload, cwd, timeoutMs);
    const outcome = translate(result, devinEvent, timeoutMs);
    log(
      `hook ${selected.indexOf(entry) + 1}/${selected.length} matcher=${JSON.stringify(entry.matcher)} ` +
        `${Date.now() - startedAt}ms status=${result.status}${result.error ? ` error=${result.error.code}` : ''}`,
    );
    if (outcome.block && !block) {
      block = outcome.reason;
      break;
    }
    if (outcome.context) contexts.push(outcome.context);
  }

  if (block) {
    emit({ decision: 'block', reason: block });
    return 0;
  }

  if (contexts.length) {
    const additionalContext = contexts.join('\n\n').slice(0, MAX_CONTEXT_CHARS);
    emit({ hookSpecificOutput: { hookEventName: devinEvent, additionalContext } });
  }
  return 0;
}

process.exitCode = main(process.argv);
