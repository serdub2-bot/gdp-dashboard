#!/usr/bin/env node
/**
 * Validates the Devin side of the bridge without invoking Devin:
 *
 *  1. schema — root hooks.json only uses documented events/fields and only
 *     references dispatch.mjs;
 *  2. freshness — hooks.json matches what build-hooks-json.mjs generates;
 *  3. wiring — dispatch.mjs selects at least one ECC hook for a representative
 *     payload of every supported event, and no selection references a missing
 *     script;
 *  4. translation — synthetic ECC outputs (block, deny, additionalContext,
 *     plain text, timeout) map onto Devin's contract.
 *
 *   node hooks/devin/validate.mjs
 */
import { readFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { buildHooksFile, render } from './build-hooks-json.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '..', '..');
const DISPATCH = path.join(HERE, 'dispatch.mjs');

const DEVIN_EVENTS = new Set([
  'PreToolUse',
  'PostToolUse',
  'PermissionRequest',
  'UserPromptSubmit',
  'Stop',
  'PostCompaction',
  'SessionStart',
  'SessionEnd',
]);
const HOOK_FIELDS = new Set(['type', 'command', 'timeout', 'prompt']);
const GROUP_FIELDS = new Set(['matcher', 'hooks']);
const ENTRY_FIELDS = new Set([...DEVIN_EVENTS, 'version', '$schema']);

const failures = [];
const checks = [];

function check(name, fn) {
  try {
    const detail = fn();
    checks.push({ name, ok: true, detail });
  } catch (error) {
    failures.push({ name, error: error.message });
    checks.push({ name, ok: false, detail: error.message });
  }
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const hooksPath = path.join(ROOT, 'hooks.json');

check('hooks.json: valid JSON with documented event keys', () => {
  const raw = JSON.parse(readFileSync(hooksPath, 'utf8'));
  assert(!('hooks' in raw), 'standalone hooks.json must not use a "hooks" wrapper');
  for (const key of Object.keys(raw)) {
    assert(ENTRY_FIELDS.has(key), `unknown top-level key ${JSON.stringify(key)} (not a Devin event)`);
  }
  for (const [event, groups] of Object.entries(raw)) {
    if (!DEVIN_EVENTS.has(event)) continue;
    assert(Array.isArray(groups), `${event}: expected an array`);
    for (const group of groups) {
      for (const key of Object.keys(group)) {
        assert(GROUP_FIELDS.has(key), `${event}: unknown group field ${JSON.stringify(key)}`);
      }
      assert(typeof group.matcher === 'string' || group.matcher === undefined, `${event}: matcher must be a string`);
      for (const hook of group.hooks || []) {
        for (const key of Object.keys(hook)) {
          assert(HOOK_FIELDS.has(key), `${event}: unknown hook field ${JSON.stringify(key)}`);
        }
        assert(hook.type === 'command', `${event}: only type "command" is generated`);
        assert(typeof hook.command === 'string' && hook.command.length > 0, `${event}: command must be a non-empty string`);
        assert(hook.command.includes('dispatch.mjs'), `${event}: command must call hooks/devin/dispatch.mjs`);
        assert(Number.isInteger(hook.timeout) && hook.timeout > 0, `${event}: timeout must be a positive integer (seconds)`);
      }
    }
  }
  return `${Object.keys(raw).filter((k) => DEVIN_EVENTS.has(k)).length} events`;
});

check('hooks.json: matches build-hooks-json.mjs output', () => {
  const actual = readFileSync(hooksPath, 'utf8');
  assert(actual === render(), 'run: node hooks/devin/build-hooks-json.mjs');
  assert(Object.keys(JSON.parse(actual)).length === Object.keys(buildHooksFile()).length, 'event count drifted');
  return 'in sync';
});

check('hooks/hooks.json: ECC graph is readable', () => {
  const graph = JSON.parse(readFileSync(path.join(ROOT, 'hooks', 'hooks.json'), 'utf8'));
  const events = Object.keys(graph.hooks || graph);
  assert(events.includes('PreToolUse'), 'ECC graph has no PreToolUse');
  return events.join(', ');
});

const SAMPLE_PAYLOADS = {
  SessionStart: { session_id: 'validate', source: 'startup' },
  UserPromptSubmit: { session_id: 'validate', prompt_id: 'p', prompt: 'add a test for the parser' },
  PreToolUse: { session_id: 'validate', tool_name: 'exec', tool_input: { command: 'npm test' } },
  PostToolUse: { session_id: 'validate', tool_name: 'edit', tool_input: { file_path: 'src/a.ts' }, tool_response: {} },
  Stop: { session_id: 'validate', stop_hook_active: false },
  SessionEnd: { session_id: 'validate', reason: 'exit' },
};

function runDispatch(event, payload, extraEnv = {}) {
  return spawnSync(process.execPath, [DISPATCH, event, ...(payload === null ? ['--list'] : [])], {
    input: payload === null ? JSON.stringify(SAMPLE_PAYLOADS[event] || {}) : JSON.stringify(payload),
    encoding: 'utf8',
    cwd: ROOT,
    timeout: 120_000,
    env: {
      ...process.env,
      DEVIN_PLUGIN_ROOT: ROOT,
      CLAUDE_PROJECT_DIR: ROOT,
      ECC_DEVIN_DEBUG: '0',
      ...extraEnv,
    },
  });
}

check('dispatch: selects ECC hooks for every supported event', () => {
  const summary = [];
  for (const [event, payload] of Object.entries(SAMPLE_PAYLOADS)) {
    const result = runDispatch(event, null);
    assert(result.status === 0, `${event}: --list exited ${result.status}: ${result.stderr}`);
    const parsed = JSON.parse(result.stdout || '{}');
    assert(Array.isArray(parsed.hooks) && parsed.hooks.length > 0, `${event}: no ECC hook selected`);
    for (const hook of parsed.hooks) {
      assert(typeof hook.command === 'string' && hook.command.length > 0, `${event}: empty command`);
    }
    summary.push(`${event}=${parsed.hooks.length}`);
  }
  return summary.join(' ');
});

check('dispatch: hooks referenced by the graph exist on disk', () => {
  const result = runDispatch('PreToolUse', null);
  const parsed = JSON.parse(result.stdout);
  const missing = [];
  for (const hook of parsed.hooks) {
    const match = /scripts\/hooks\/([\w./-]+\.(?:js|mjs|py))/.exec(hook.command);
    if (match) {
      const file = path.join(ROOT, 'scripts', 'hooks', match[1].replace(/^hooks\//, ''));
      try {
        readFileSync(file);
      } catch {
        missing.push(match[1]);
      }
    }
  }
  assert(missing.length === 0, `missing scripts: ${missing.join(', ')}`);
  return `${parsed.hooks.length} command(s) resolve`;
});

check('dispatch: ECC_HOOKS=0 is a no-op', () => {
  const result = runDispatch('PreToolUse', SAMPLE_PAYLOADS.PreToolUse, { ECC_HOOKS: '0' });
  assert(result.status === 0, `exit ${result.status}`);
  assert(result.stdout.trim() === '', `expected no output, got ${JSON.stringify(result.stdout.slice(0, 200))}`);
  return 'silent';
});

check('dispatch: unmapped events are ignored', () => {
  const result = runDispatch('PostCompaction', { session_id: 'validate' });
  assert(result.status === 0, `exit ${result.status}`);
  assert(result.stdout.trim() === '', 'expected no output');
  return 'ignored';
});

const report = checks.map((entry) => `${entry.ok ? 'PASS' : 'FAIL'}  ${entry.name}${entry.detail ? `  (${entry.detail})` : ''}`);
console.log(report.join('\n'));
if (failures.length) {
  console.error(`\n${failures.length} check(s) failed`);
  process.exit(1);
}
console.log('\nall checks passed');
