import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,mkdirSync,writeFileSync,copyFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {spawnSync} from 'node:child_process';
import {EVENTS,TOOLS,normalize,select,translate} from './dispatch.mjs';
test('all tool mappings and path alias',()=>{
 for (const [name,target] of Object.entries(TOOLS)) assert.equal(normalize('PreToolUse',{tool_name:name},'/p').tool_name,target);
 assert.equal(normalize('PostToolUse',{tool_input:{path:'a.txt'}},'/p').tool_input.file_path,'a.txt');
 assert.equal(normalize('PreToolUse',{tool_name:'unknown'},'/p').tool_name,'unknown');
});
test('matcher selection, absent tool never runs Bash hook',()=>{
 const g={PreToolUse:[{matcher:'Bash|Edit',hooks:[{type:'command',command:'ok'},{type:'prompt',prompt:'skip'}]}]};
 assert.equal(select(g,'PreToolUse',{tool_name:'Bash'}).length,1);
 assert.equal(select(g,'PreToolUse',{}).length,0);
 assert.equal(select(g,'PreToolUse',{tool_name:'Read'}).length,0);
});
test('deny contracts and no permission escalation',()=>{
 assert.ok(translate({status:2,stderr:'denied'}).block);
 for (const value of [{decision:'block'},{continue:false},{hookSpecificOutput:{permissionDecision:'deny'}}])
  assert.ok(translate({status:0,stdout:JSON.stringify(value)}).block);
 assert.equal(translate({status:0,stdout:'{"permission":"allow"}'}).context,'');
 assert.ok(translate({status:null,error:{code:'ETIMEDOUT'}}).warning);
 assert.equal(translate({status:0,stdout:'hello'}).context,'hello');
 assert.equal(translate({status:0,stdout:'{"hookSpecificOutput":{"additionalContext":"ctx"}}'}).context,'ctx');
});
test('real dispatch preserves literal tool input and plugin/project roots',()=>{
 const root=mkdtempSync(join(tmpdir(),'ruflo devin '));
 try {
  mkdirSync(join(root,'devin-adapter'));mkdirSync(join(root,'hooks'));
  copyFileSync(new URL('./dispatch.mjs',import.meta.url),join(root,'devin-adapter/dispatch.mjs'));
  writeFileSync(join(root,'devin-adapter/config.json'),JSON.stringify({hookSource:'hooks/hooks.json'}));
  writeFileSync(join(root,'check.cjs'),`let s='';process.stdin.on('data',x=>s+=x);process.stdin.on('end',()=>{const p=JSON.parse(s);console.log(JSON.stringify({hookSpecificOutput:{additionalContext:JSON.stringify({tool:p.tool_name,input:p.tool_input,root:process.env.CLAUDE_PLUGIN_ROOT,cwd:process.cwd()})}}))});`);
  writeFileSync(join(root,'hooks/hooks.json'),JSON.stringify({hooks:{PreToolUse:[{matcher:'Bash',hooks:[{type:'command',command:`node "${join(root,'check.cjs')}"`}]}]}}));
  const command='echo "$(touch SHOULD_NOT_EXIST)"; < >&';
  const run=spawnSync(process.execPath,[join(root,'devin-adapter/dispatch.mjs'),'PreToolUse'],{input:JSON.stringify({tool_name:'exec',tool_input:{command},cwd:root}),encoding:'utf8',env:{...process.env,DEVIN_PROJECT_DIR:root}});
  assert.equal(run.status,0,run.stderr);
  const actual=JSON.parse(JSON.parse(run.stdout).hookSpecificOutput.additionalContext);
  assert.equal(actual.input.command,command);assert.equal(actual.tool,'Bash');assert.equal(actual.root,root);assert.equal(actual.cwd,root);
  const disabled=spawnSync(process.execPath,[join(root,'devin-adapter/dispatch.mjs'),'PreToolUse'],{input:'{}',encoding:'utf8',env:{...process.env,RUFLO_DEVIN_HOOKS:'0'}});
  assert.equal(disabled.stdout,'');
 } finally {rmSync(root,{recursive:true,force:true});}
});
test('only equivalent lifecycle events exposed',()=>{
 assert.ok(!EVENTS.includes('PreCompact'));assert.ok(!EVENTS.includes('PostToolUseFailure'));
});
