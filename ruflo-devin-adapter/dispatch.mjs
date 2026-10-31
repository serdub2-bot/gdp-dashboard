#!/usr/bin/env node
// Ruflo command-hook compatibility bridge. No dependencies; Node >=20.
import {readFileSync} from 'node:fs';
import {spawnSync} from 'node:child_process';
import {dirname, resolve, join} from 'node:path';
import {fileURLToPath} from 'node:url';
export const EVENTS = ['SessionStart','UserPromptSubmit','PreToolUse','PostToolUse','Stop','SessionEnd'];
export const TOOLS = {exec:'Bash',read:'Read',write:'Write',edit:'Edit',apply_patch:'Edit',glob:'Glob',grep:'Grep',webfetch:'WebFetch',run_subagent:'Task',read_subagent:'Task',get_output:'BashOutput',write_to_process:'BashOutput',skill:'Skill',todo_write:'TodoWrite'};
export function normalize(event, data, cwd) {
  const input = {...(data.tool_input || {})};
  if (input.file_path === undefined && typeof input.path === 'string') input.file_path = input.path;
  return {...data, cwd, hook_event_name:event, tool_name:TOOLS[data.tool_name] || data.tool_name, tool_input:input};
}
export function select(graph, event, payload) {
  return (graph[event] || []).filter(group => {
    if (!group.matcher) return true;
    const subject = ['PreToolUse','PostToolUse'].includes(event) ? payload.tool_name : (payload.source || payload.reason || '');
    try { return new RegExp(`^(?:${group.matcher})$`).test(subject || ''); } catch { return false; }
  }).flatMap(group => group.hooks || []).filter(h => h.type === 'command' && typeof h.command === 'string');
}
export function translate(result) {
  const out = String(result.stdout || '').trim(), err = String(result.stderr || '').trim();
  if (result.status === 2) return {block:err || out || 'Blocked by Ruflo hook'};
  if (result.error || result.status !== 0) return {warning:`Ruflo hook failed (${result.error?.code || result.status}); fail-open`};
  let value;
  try { value = JSON.parse(out); } catch { return {context:out}; }
  const specific = value?.hookSpecificOutput || {};
  if (value?.decision === 'block' || value?.continue === false || specific.permissionDecision === 'deny')
    return {block:value.reason || value.stopReason || specific.permissionDecisionReason || 'Blocked by Ruflo hook'};
  // Never forward unconditional allow verdicts, permission overrides or updatedInput.
  return {context:[specific.additionalContext,value?.systemMessage].filter(x => typeof x === 'string').join('\n')};
}
export function main(argv = process.argv) {
  if (process.env.RUFLO_DEVIN_HOOKS === '0') return 0;
  const event = argv[2];
  if (!EVENTS.includes(event)) return 0;
  const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
  const config = JSON.parse(readFileSync(join(root,'devin-adapter','config.json'),'utf8'));
  let raw;
  try { raw = JSON.parse(readFileSync(0,'utf8') || '{}'); }
  catch { process.stderr.write('[ruflo-devin] invalid hook payload\n'); return 1; }
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return 1;
  const cwd = process.env.DEVIN_PROJECT_DIR || raw.cwd || process.cwd();
  const payload = normalize(event, raw, cwd);
  const document = config.hookSource ? JSON.parse(readFileSync(join(root,config.hookSource),'utf8')) : {};
  const selected = select(document.hooks || document,event,payload);
  if (argv.includes('--list')) { console.log(JSON.stringify({event,tool_name:payload.tool_name,hooks:selected})); return 0; }
  const commandRoot = config.commandRoot ? resolve(root,config.commandRoot) : root;
  const context = [];
  // Fixed aggregate budget, no unbounded detached async jobs.
  const deadline = Date.now() + 45000;
  for (const hook of selected) {
    const remaining = deadline - Date.now();
    if (remaining <= 0) { process.stderr.write('[ruflo-devin] aggregate timeout; remaining hooks skipped\n'); break; }
    // Some legacy manifests use milliseconds (5000); modern ones use seconds.
    const requested = Number(hook.timeout) || 10;
    const timeout = Math.min(remaining, requested >= 1000 ? requested : requested * 1000, 15000);
    const result = spawnSync(hook.command, {shell:true, cwd, input:JSON.stringify(payload), encoding:'utf8',
      timeout, maxBuffer:1024*1024, env:{...process.env,CLAUDE_PLUGIN_ROOT:commandRoot,DEVIN_PLUGIN_ROOT:commandRoot,
        CLAUDE_PROJECT_DIR:cwd,DEVIN_PROJECT_DIR:cwd,RUFLO_HOOK_SOURCE:'devin'}});
    const outcome = translate(result);
    if (outcome.warning) process.stderr.write(`[ruflo-devin] ${outcome.warning}\n`);
    if (outcome.block) { console.log(JSON.stringify({decision:'block',reason:outcome.block})); return 0; }
    if (outcome.context) context.push(outcome.context);
  }
  if (context.length) console.log(JSON.stringify({hookSpecificOutput:{hookEventName:event,additionalContext:context.join('\n\n').slice(0,12000)}}));
  return 0;
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try { process.exitCode = main(); } catch (error) { console.error(`[ruflo-devin] ${error.message}`); process.exitCode = 1; }
}
