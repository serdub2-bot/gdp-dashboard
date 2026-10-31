#!/usr/bin/env python3
"""Non-destructive Devin overlay for a complete Ruflo checkout."""
import argparse, hashlib, json, pathlib, re, shutil, subprocess, zipfile
HERE = pathlib.Path(__file__).resolve().parent
EVENTS = ['SessionStart','UserPromptSubmit','PreToolUse','PostToolUse','Stop','SessionEnd']
def save(p, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n')
def body(text):
    return re.sub(r'\A---\r?\n.*?\r?\n---\r?\n', '', text, count=1, flags=re.S)
def build(source, output):
    if output.exists(): raise SystemExit('Output must not already exist')
    output.mkdir(parents=True)
    # git archive includes every tracked upstream file, regardless of ignore rules.
    import tarfile, io
    blob = subprocess.check_output(['git','-C',str(source),'archive','HEAD'])
    with tarfile.open(fileobj=io.BytesIO(blob)) as archive:
        for member in archive.getmembers():
            if member.name.startswith('/') or '..' in pathlib.PurePosixPath(member.name).parts:
                raise ValueError('Unsafe archive path')
            if member.issym() or member.islnk():
                base = (output / member.name).parent if member.issym() else output
                target = (base / member.linkname).resolve()
                if pathlib.PurePosixPath(member.linkname).is_absolute() or output not in target.parents:
                    raise ValueError('Unsafe archive link')
        archive.extractall(output)
    sha = subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()
    manifests = sorted(output.rglob('.claude-plugin/plugin.json'))
    records = []
    for manifest in manifests:
        root = manifest.parent.parent
        old = json.loads(manifest.read_text())
        is_root = root == output
        adapter = root/'devin-adapter'; adapter.mkdir(exist_ok=True)
        shutil.copy2(HERE/'dispatch.mjs',adapter/'dispatch.mjs')
        hookfile = root/'hooks/hooks.json'
        command_root = None
        if is_root:
            hookfile = root/'plugins/ruflo-core/hooks/hooks.json'
            command_root = 'plugins/ruflo-core'
        document = json.loads(hookfile.read_text()) if hookfile.exists() else {}
        graph = document.get('hooks',document)
        config = {'hookSource':str(hookfile.relative_to(root)) if hookfile.exists() else None}
        if command_root: config['commandRoot'] = command_root
        save(adapter/'config.json',config)
        hooks = {}
        skipped = []
        for event, groups in graph.items():
            if not isinstance(groups,list): continue
            if event not in EVENTS:
                if groups: skipped.append(event)
                continue
            if not any(isinstance(g,dict) and any(isinstance(h,dict) and h.get('type')=='command' for h in g.get('hooks',[])) for g in groups): continue
            command = 'node -e "const p=require(\'path\'),c=require(\'child_process\');const r=process.env.DEVIN_PLUGIN_ROOT||process.env.CLAUDE_PLUGIN_ROOT;if(!r)process.exit(1);const x=c.spawnSync(process.execPath,[p.join(r,\'devin-adapter\',\'dispatch.mjs\'),\''+event+'\'],{stdio:\'inherit\'});process.exit(x.status===null?1:x.status)"'
            hooks[event] = [{'matcher':'','hooks':[{'type':'command','command':command,'timeout':60}]}]
        save(root/'hooks.json',hooks)
        skills = root/'devin-skills'; skills.mkdir(exist_ok=True)
        sources = [('skill',root/'skills'),('command',root/'commands'),('agent',root/'agents')]
        if is_root: sources = [('skill',root/'.claude/skills'),('command',root/'.claude/commands'),('agent',root/'.claude/agents')]
        count = 0
        for kind, directory in sources:
            if not directory.exists(): continue
            files = sorted(directory.rglob('SKILL.md' if kind=='skill' else '*.md'))
            for file in files:
                relative = file.relative_to(directory)
                slug = re.sub('[^a-z0-9-]+','-',str(relative.with_suffix('')).lower()).strip('-')
                slug = (kind+'-'+slug)[:80]+'-'+hashlib.sha256(str(relative).encode()).hexdigest()[:8]
                target = skills/slug; target.mkdir()
                if kind == 'skill':
                    # Include support scripts/assets alongside skill instructions.
                    shutil.copytree(file.parent,target,dirs_exist_ok=True,symlinks=True)
                title = f'Ruflo {kind}: {relative.with_suffix("")}'
                text = body(file.read_text(errors='replace'))
                heading = ('This is a role guide, not an automatically spawned Claude agent. Use Devin-native delegation only if available.\n\n' if kind=='agent' else '')
                heading += 'Host adaptation: Claude Code tool names, model settings, permissions, UI and $ARGUMENTS are not Devin APIs. Use available Devin tools and explicit user arguments; never invent an unavailable tool or report an unexecuted action. Resolve plugin-relative scripts from the installed plugin directory, not the project directory.\n\n'
                (target/'SKILL.md').write_text('---\nname: '+slug+'\ndescription: '+json.dumps(title)+'\n---\n\n'+heading+text)
                count += 1
        native = {k:old[k] for k in ['name','version','author','homepage','license','keywords'] if k in old}
        native['description'] = 'Devin compatibility edition. '+old.get('description','')
        native['repository'] = 'https://github.com/ruvnet/ruflo'
        native['skills'] = './devin-skills/'
        save(root/'.devin-plugin/plugin.json',native)
        # Use Devin's plugin-root variable only in Devin-specific MCP manifest.
        mcp = root/'.mcp.json'
        mcp_config = json.loads(mcp.read_text()) if mcp.exists() else None
        if is_root:
            mcp_config = {'mcpServers':{'ruflo':{'command':'node','args':['${DEVIN_PLUGIN_ROOT}/devin-adapter/mcp.cjs'],'env':{'CLAUDE_FLOW_MCP_TRANSPORT':'stdio'}}}}
            (adapter/'mcp.cjs').write_text("process.env.CLAUDE_PROJECT_DIR=process.env.DEVIN_PROJECT_DIR||process.cwd();\nrequire('../plugins/ruflo-core/scripts/mcp-launch.cjs');\n")
        if mcp_config:
            devin_mcp = json.loads(json.dumps(mcp_config).replace('${CLAUDE_PLUGIN_ROOT}','${DEVIN_PLUGIN_ROOT}'))
            save(root/'.devin-plugin/mcp.json',devin_mcp)
        records.append({'path':str(root.relative_to(output)),'name':native['name'],'skills':count,'events':list(hooks),
                        'unsupportedEvents':skipped,'functionModules':document.get('modules',[]),
                        'mcpConfig':bool(mcp_config),'userConfigRequiresManualSetup':bool(old.get('userConfig'))})
    save(output/'DEVIN-COMPATIBILITY.json',{'upstream':'https://github.com/ruvnet/ruflo','commit':sha,'plugins':records,
        'validation':'Adapter unit tests and static checks only; Devin host not available.',
        'limitations':['Claude function hooks and UI modules are preserved but not executed.','Prompt/agent hooks are not executed.','Cloud plugin lifecycle support depends on Devin host.','MCP registration may require manual import of .devin-plugin/mcp.json.','Model settings, permissions, secret store and userConfig are not migrated.','Async command hooks execute synchronously within bounded timeout.']})
    shutil.copy2(HERE/'README.ru.md',output/'DEVIN-README.ru.md')
    shutil.copy2(HERE/'test.mjs',output/'devin-adapter/test.mjs')
    return records
if __name__ == '__main__':
    p=argparse.ArgumentParser(); p.add_argument('source',type=pathlib.Path); p.add_argument('output',type=pathlib.Path); p.add_argument('--zip',type=pathlib.Path)
    a=p.parse_args(); records=build(a.source.resolve(),a.output.resolve())
    print(f'Adapted {len(records)} plugin manifests; {sum(r["skills"] for r in records)} skill entries')
    if a.zip:
        with zipfile.ZipFile(a.zip,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
            for f in sorted(a.output.rglob('*')):
                if f.is_symlink():
                    import os, stat
                    info=zipfile.ZipInfo(str(pathlib.Path('ruflo-devin')/f.relative_to(a.output)))
                    info.create_system=3; info.external_attr=(stat.S_IFLNK | 0o777) << 16
                    z.writestr(info,os.readlink(f))
                elif f.is_file(): z.write(f,pathlib.Path('ruflo-devin')/f.relative_to(a.output))
        print(a.zip, a.zip.stat().st_size)
