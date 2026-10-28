#!/usr/bin/env python3
"""Read-only exact source identity check; NOT an atomic apply or deployment tool.

A successful observation does not reserve the paths. The local single-writer
must retain its lock and recheck immediately before applying an exact patch.
No git operation, overwrite, directory creation, or baseline update occurs.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys

_SPEC=importlib.util.spec_from_file_location('_v4_size_tool_for_pins',Path(__file__).with_name('code_size_gate.py'))
if _SPEC is None or _SPEC.loader is None:
    raise ImportError('missing packaged code_size_gate.py')
_gate=importlib.util.module_from_spec(_SPEC);_SPEC.loader.exec_module(_gate)


def absent(root:Path,relative:str)->bool:
    """Absence of a new leaf is permitted; absence of root is not evidence."""
    root=Path(os.path.abspath(root))
    parts=root.parts[1:]
    fd=os.open('/',os.O_RDONLY|os.O_DIRECTORY|os.O_CLOEXEC)
    try:
        for part in parts:
            child=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=fd)
            os.close(fd);fd=child
        rel=_gate._path(relative).split('/')
        for part in rel[:-1]:
            try:
                child=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=fd)
            except FileNotFoundError:
                return True
            os.close(fd);fd=child
        try:os.stat(rel[-1],dir_fd=fd,follow_symlinks=False)
        except FileNotFoundError:return True
        return False
    finally:os.close(fd)


def check(root:Path,pins:dict,mode:str)->dict:
    if mode not in {'before','after'}:raise ValueError('INVALID_MODE')
    if not isinstance(pins,dict) or pins.get('schema')!='v4.bigcode.source_pins.v1' or not isinstance(pins.get('files'),list) or not pins['files']:
        raise ValueError('INVALID_PINS')
    rows=[];seen=set();budget=[_gate.MAX_TOTAL_BYTES]
    for item in pins['files']:
        relative=_gate._path(item.get('path'))
        if relative.casefold() in seen:raise ValueError('DUPLICATE_PIN_PATH')
        seen.add(relative.casefold())
        if _gate._category(relative)=='excluded':raise ValueError('PIN_IN_EXCLUDED_AREA')
        expected=item[mode]
        row={'path':relative,'mode':mode,'expected':expected,'match':False}
        try:
            if expected is None:
                row['observed']='ABSENT' if absent(root,relative) else 'EXISTS'
                row['match']=row['observed']=='ABSENT'
            else:
                if type(expected.get('bytes')) is not int or expected['bytes']<0 or not isinstance(expected.get('sha256'),str) or len(expected['sha256'])!=64:
                    raise ValueError('INVALID_PIN_IDENTITY')
                raw=_gate._read_source(root,relative,budget)
                observed={'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
                row['observed']=observed;row['match']=observed==expected
        except (OSError,ValueError) as error:
            row['error']=type(error).__name__+': '+str(error)
        rows.append(row)
    return {'schema':'v4.bigcode.source_state.v1','status':'MATCH_'+mode.upper() if all(r['match'] for r in rows) else 'MISMATCH',
            'root_observation':str(Path(os.path.abspath(root))),'observation_only':True,
            'atomic_cas_performed':False,'deployment_authorized':False,'rows':rows}


def main(argv=None)->int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--pins',type=Path,default=Path(__file__).resolve().parents[1]/'SOURCE_PINS.json')
    parser.add_argument('--mode',choices=['before','after'],required=True)
    args=parser.parse_args(argv)
    try:
        result=check(args.root,_gate.load_json(args.pins),args.mode)
        print(json.dumps(result,ensure_ascii=False,indent=2,sort_keys=True))
        return 0 if result['status'].startswith('MATCH_') else 3
    except (OSError,ValueError,KeyError,TypeError) as error:
        print(json.dumps({'status':'ERROR','error':str(error)},ensure_ascii=False));return 2

if __name__=='__main__':raise SystemExit(main())
