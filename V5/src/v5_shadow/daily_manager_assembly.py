"""Seal actual post-owner inputs/cutoff once, then reuse original manager owner."""
import copy
from datetime import datetime,timezone,timedelta
import hashlib
import json
import os
from pathlib import Path
from v5_shadow.digests import sha256_json
from v5_shadow.module_api import _open_directory,_read_at
from v5_shadow.module_artifacts import _directory,_write_once
from v5_shadow.run_ledger import locked,_read,_write,MARKER


def product_reference(row):
    state=row.get('state') or {}
    attempts=state.get('attempts') or []
    return (attempts[-1].get('product_reference') if attempts and attempts[-1].get('readback_verified') is True else None)


def assemble_manager_request(template,lanes,ledger_root,registration):
    from v5_shadow.manager_plan import _snapshot
    now=datetime.now(timezone.utc);target=now.astimezone(timezone(timedelta(hours=8))).strftime('%Y%m%d')
    if template['target_date']!=target:raise ValueError('DAILY_MANAGER_TEMPLATE_TARGET')
    request=copy.deepcopy(template)
    request.update(action='refresh',view='auto',selection_date=None,announcement_date=None)
    # Preserve other original bound owner files, but never silently reuse an old
    # US product or rebound observation when this day's lane has no readback.
    files={name:raw for name,raw in _snapshot(request['inputs']['manager']).items()
           if not name.startswith('us_mapping_research/')}
    request.pop('rebound_observation',None);request.pop('announcement_offline_owner',None)
    for row in lanes:
        ref=product_reference(row)
        if not ref:continue
        lane=row['lane']
        if lane=='us_mapping':
            if ref['target_date']!=target:raise ValueError('DAILY_MANAGER_US_TARGET')
            run=ref['run_id']
            import re
            if not re.fullmatch('[0-9a-f]{32}',run):raise ValueError('DAILY_MANAGER_US_RUN')
            root=_open_directory(ref['manager_output_root'])
            day=None;runs=None
            try:
                parent=os.open('us_mapping_research',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=root)
                try:day=os.open(target,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=parent)
                finally:os.close(parent)
                runs=os.open('runs',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=day)
                raw=_read_at(runs,None,run+'.json');daily=json.loads(raw)
                unsigned=dict(daily);digest=unsigned.pop('artifact_sha256')
                if digest!=ref['artifact_sha256'] or sha256_json(unsigned)!=digest or daily['run_id']!=run:
                    raise ValueError('DAILY_MANAGER_US_ARTIFACT')
                pointer=_read_at(day,None,'latest.json');head=json.loads(pointer)
                if head['run_id']!=run or head['artifact_sha256']!=digest:raise ValueError('DAILY_MANAGER_US_HEAD_CHANGED')
                prefix='us_mapping_research/'+target+'/'
                files[prefix+'runs/'+run+'.json']=raw;files[prefix+'latest.json']=pointer
            finally:
                for fd in (runs,day,root):
                    if fd is not None:os.close(fd)
        elif lane=='rebound' and ref.get('reference'):
            request['rebound_observation']=dict(root=ref['root'],reference=ref['reference'])
        elif lane=='announcement' and ref.get('binding'):
            if ref['binding']['target_date']!=target:raise ValueError('DAILY_MANAGER_ANNOUNCEMENT_TARGET')
            request['announcement_offline_owner']=ref['binding']
    hashes={name:hashlib.sha256(raw).hexdigest() for name,raw in files.items()}
    digest=sha256_json(hashes);root=_open_directory(ledger_root);staging=None;version=None
    try:
        if _read_at(root,None,'.v5-daily-run-ledger')!=MARKER:raise ValueError('DAILY_MANAGER_LEDGER_MARKER')
        staging=_directory(root,'manager_inputs');version=_directory(staging,digest)
        for name,raw in files.items():
            parent=os.dup(version)
            try:
                for component in Path(name).parts[:-1]:
                    child=_directory(parent,component);os.close(parent);parent=child
                _write_once(parent,Path(name).name,raw)
            finally:os.close(parent)
    finally:
        for fd in (version,staging,root):
            if fd is not None:os.close(fd)
    request['inputs']['manager']=dict(root=str(Path(ledger_root)/'manager_inputs'/digest),files=hashes)
    request.pop('now',None)
    # Stable logical inputs select the sealed request; repeated ticks do not
    # manufacture a new cutoff/run. New actual inputs produce another version.
    identity=dict(registration,lane='manager_plan',target_date=target,input_sha256=sha256_json(request),
        research_cutoff=target[:4]+'-'+target[4:6]+'-'+target[6:]+'T08:45:00+08:00')
    with locked(ledger_root,identity) as (fd,key):
        name='request-'+key+'.json';saved=_read(fd,name)
        if saved is not None:return saved
        request['now']=now.isoformat();_write(fd,name,request);return request
