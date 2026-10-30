#!/usr/bin/env python3
"""Compact, resumable Angr recovery for a bounded set of x86 direct-call targets.

One JSONL.GZ and one status CSV per invocation. Records contain callee targets
so interrupted batches can be salvaged without losing the discovered edges.
"""
from __future__ import annotations
import argparse, csv, gc, gzip, json, logging, struct
from collections import deque
from pathlib import Path


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--exe',type=Path,required=True)
    ap.add_argument('--seeds',type=Path,required=True)
    ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--max-region',type=lambda x:int(x,0),default=0x400)
    ap.add_argument('--max-blocks',type=int,default=40)
    ap.add_argument('--max-functions',type=int,default=100)
    args=ap.parse_args()
    import angr
    logging.getLogger('angr').setLevel(logging.ERROR)
    exports=[]
    project=angr.Project(str(args.exe),auto_load_libs=False)
    ranges=[(s.min_addr,s.max_addr+1) for s in project.loader.main_object.sections if s.is_executable]
    def executable(a):return any(lo<=a<hi for lo,hi in ranges)
    def tail_jump(a):
        try:
            b=project.loader.memory.load(a,10)
            if len(b)>=5 and b[0]==0xe9:return a+5+struct.unpack('<i',b[1:5])[0]
            if len(b)>=10 and b[0]==0xe8 and b[5]==0xe9:return a+10+struct.unpack('<i',b[6:10])[0]
        except Exception:pass
        return None
    seeds=sorted({int(line.split()[0],16) for line in args.seeds.read_text().splitlines() if line.strip()})
    args.out.mkdir(parents=True,exist_ok=True)
    rows=[]
    with gzip.open(args.out/'records.jsonl.gz','wt',encoding='utf-8',newline='\n') as out:
        for idx,addr in enumerate(seeds[:args.max_functions],1):
            status,error,code='ok','','';blocks=0;callees=set();tail=tail_jump(addr)
            end=addr+args.max_region
            if tail is not None and executable(tail):end=max(end,min(addr+args.max_region,tail+min(0x800,args.max_region)))
            try:
                cfg=project.analyses.CFGFast(regions=[(min(addr,tail) if tail is not None and executable(tail) else addr,end)],function_starts=[addr],start_at_entry=False,symbols=False,function_prologues=False,force_complete_scan=False,resolve_indirect_jumps=False,data_references=False,cross_references=False,normalize=True,exceptions=False)
                func=project.kb.functions.get(addr)
                if func is None:raise RuntimeError('no CFG function at target')
                blocks=len(func.block_addrs)
                for ba in func.block_addrs:
                    try:
                        for ins in project.factory.block(ba,size=0x100).capstone.insns:
                            if ins.mnemonic=='call' and ins.operands and ins.operands[0].type==2:
                                t=int(ins.operands[0].imm)
                                if t!=addr and executable(t):callees.add(t)
                    except Exception:continue
                if tail is not None and tail!=addr and executable(tail):callees.add(tail)
                if blocks>args.max_blocks:status='too_complex'
                else:
                    dec=project.analyses.Decompiler(func,cfg=cfg,fail_fast=False)
                    code=getattr(getattr(dec,'codegen',None),'text','') or ''
                    if not code:status='no_pseudocode'
            except Exception as exc:
                status='error';error=(type(exc).__name__+': '+str(exc)).replace('\n',' ')[:500]
            r={'entry_va':f'0x{addr:08x}','status':status,'cfg_blocks':blocks,'code':code,'callee_targets':[f'0x{x:08x}' for x in sorted(callees)],'tail_jump_target':f'0x{tail:08x}' if tail is not None else '','error':error}
            out.write(json.dumps(r,ensure_ascii=False,separators=(',',':'))+'\n');out.flush()
            rows.append({'entry_va':r['entry_va'],'status':status,'cfg_blocks':str(blocks),'callee_count':str(len(callees)),'callee_targets':' | '.join(r['callee_targets']),'tail_jump_target':r['tail_jump_target'],'error':error})
            if idx%3==0:
                project=None;gc.collect();project=angr.Project(str(args.exe),auto_load_libs=False);ranges=[(s.min_addr,s.max_addr+1) for s in project.loader.main_object.sections if s.is_executable]
                print(f'reloaded after {idx} functions',flush=True)
    with (args.out/'status.csv').open('w',newline='',encoding='utf-8') as f:
        fields=['entry_va','status','cfg_blocks','callee_count','callee_targets','tail_jump_target','error']
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
    print(f'wrote {len(rows)} records: {args.out}',flush=True)

if __name__=='__main__':main()
