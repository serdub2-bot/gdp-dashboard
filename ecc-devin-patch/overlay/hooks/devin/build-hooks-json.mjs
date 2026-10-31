#!/usr/bin/env node
/**
 * Generates the Devin root `hooks.json` (Devin hook format v1) from a single
 * event table, so every entry stays byte-identical and reviewable.
 *
 *   node hooks/devin/build-hooks-json.mjs           # write hooks.json
 *   node hooks/devin/build-hooks-json.mjs --check   # exit 1 if out of date
 *
 * The generated file is intentionally tiny: one entry per Devin lifecycle
 * event, all work happens in hooks/devin/dispatch.mjs, which reuses the
 * unchanged Claude hook graph in hooks/hooks.json.
 */
import { readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '..', '..');
const OUT = path.join(ROOT, 'hooks.json');

/** Devin event -> timeout in whole seconds (Devin's unit). */
export const EVENTS = [
  ['SessionStart', 60],
  ['UserPromptSubmit', 30],
  ['PreToolUse', 60],
  ['PostToolUse', 60],
  ['Stop', 60],
  ['SessionEnd', 15],
];

/**
 * Devin runs `command` through a shell, and only documents DEVIN_PLUGIN_ROOT as
 * an environment variable handed to plugin hooks (not as a `${...}` token that
 * is expanded in the file). `node -e` keeps the entry portable across sh, cmd
 * and PowerShell, and makes a missing root a clean no-op instead of a broken
 * "/hooks/devin/dispatch.mjs" path.
 */
export function commandFor(event) {
  const js = [
    "const{spawnSync}=require('child_process'),p=require('path')",
    'const r=process.env.DEVIN_PLUGIN_ROOT||process.env.CLAUDE_PLUGIN_ROOT',
    'if(!r)process.exit(0)',
    `const x=spawnSync(process.execPath,[p.join(r,'hooks','devin','dispatch.mjs'),'${event}'],{stdio:'inherit'})`,
    "process.exit(typeof x.status==='number'?x.status:0)",
  ].join(';');
  return `node -e "${js}"`;
}

export function buildHooksFile() {
  const hooks = {};
  for (const [event, timeout] of EVENTS) {
    hooks[event] = [
      {
        matcher: '',
        hooks: [
          {
            type: 'command',
            command: commandFor(event),
            timeout,
          },
        ],
      },
    ];
  }
  return hooks;
}

export function render() {
  return `${JSON.stringify(buildHooksFile(), null, 2)}\n`;
}

const invokedDirectly = process.argv[1] && path.resolve(process.argv[1]) === path.resolve(fileURLToPath(import.meta.url));
if (invokedDirectly) {
  const check = process.argv.includes('--check');
  const expected = render();
  if (check) {
    let actual = '';
    try {
      actual = readFileSync(OUT, 'utf8');
    } catch {
      actual = '';
    }
    if (actual !== expected) {
      console.error('hooks.json is out of date. Run: node hooks/devin/build-hooks-json.mjs');
      process.exit(1);
    }
    console.log('hooks.json is up to date');
  } else {
    writeFileSync(OUT, expected);
    console.log(`wrote ${path.relative(process.cwd(), OUT)}`);
  }
}
