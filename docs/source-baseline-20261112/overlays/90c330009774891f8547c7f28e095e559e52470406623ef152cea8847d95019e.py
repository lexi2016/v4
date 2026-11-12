"""Read-only fixed V4 SOP documents; no caller-supplied filesystem paths."""
from datetime import datetime,timezone
from pathlib import Path
import hashlib,os,stat
from infrastructure.owned_io import SafeRoot

CANONICAL_ROOT=Path('/Users/lexi/Desktop/学习/v4_app')
DOCUMENTS={
    'runtime-data-recovery':('运行链补数据与复用规程','docs/operations/RUNTIME_DATA_RECOVERY_SOP.md'),
    'overview':('SOP 总览','docs/SOP.md'),
    'stage-selection':('阶段选股运行规程','docs/operations/STAGE_SELECTION_SOP.md'),
    'repair-20261028-29':('2026-10-28／29 阶段修复记录','docs/operations/records/2026-10-28_29-stage-selection-repair.md'),
}

def _sealed_root(relative):
    """Runtime-controlled identity, never an HTTP caller-supplied path."""
    app=os.environ.get('V4_APP_ROOT');manifest=os.environ.get('V4_RELEASE_MANIFEST_PATH')
    if not app and not manifest:return CANONICAL_ROOT,None
    root=Path(app or '');seal=Path(manifest or '')
    if (not root.is_absolute() or root.resolve(strict=True)!=root
        or root!=Path(__file__).resolve().parents[1] or seal!=root.parent/'release-manifest.json'):
        raise ValueError('SOP_RELEASE_FIXED_PATH_MISMATCH')
    raw=SafeRoot(root.parent).read_bytes('release-manifest.json',max_bytes=16*1024*1024)
    digest=hashlib.sha256(raw).hexdigest()
    if digest!=os.environ.get('V4_RELEASE_MANIFEST_SHA256'):raise ValueError('SOP_RELEASE_MANIFEST_SHA_MISMATCH')
    import json
    record=json.loads(raw)
    if (record.get('app_root')!=str(root) or record.get('release_id')!=os.environ.get('V4_RELEASE_ID')
        or record.get('RESEARCH_ONLY') is not True or any(record.get(k) is not False for k in
            ('production_allowed','buy_gate_updated','orders_sent'))):raise ValueError('SOP_RELEASE_IDENTITY_MISMATCH')
    inventory=record.get('application_inventory',{});entries=inventory.get('entries',[])
    if (inventory.get('entry_count')!=len(entries) or hashlib.sha256(json.dumps(entries,ensure_ascii=False,
        sort_keys=True,separators=(',',':')).encode()).hexdigest()!=inventory.get('aggregate_sha256')):
        raise ValueError('SOP_RELEASE_INVENTORY_INVALID')
    matches=[e for e in entries if e.get('path')==relative and e.get('kind')=='file']
    if len(matches)!=1:raise ValueError('SOP_DOCUMENT_NOT_SEALED')
    return root,matches[0]

def read_sop(document='overview'):
    if document not in DOCUMENTS:raise KeyError('UNKNOWN_SOP_DOCUMENT')
    title,relative=DOCUMENTS[document];root,pin=_sealed_root(relative)
    if root.resolve(strict=True)!=root or root.is_symlink():raise ValueError('SOP_CANONICAL_ROOT_ALIAS')
    path=root/relative
    if path.resolve(strict=True)!=path or path.is_symlink():raise ValueError('SOP_DOCUMENT_ALIAS')
    before=path.lstat()
    if not stat.S_ISREG(before.st_mode):raise ValueError('SOP_NOT_REGULAR_FILE')
    raw=SafeRoot(root).read_bytes(relative,max_bytes=512*1024);after=path.lstat()
    if pin and (pin['sha256']!=hashlib.sha256(raw).hexdigest() or pin['size']!=len(raw)):
        raise ValueError('SOP_DOCUMENT_SHA_MISMATCH')
    if (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns):raise ValueError('SOP_CHANGED_REFRESH_REQUIRED')
    return {'status':'READ_OK','id':document,'title':title,'relative_path':relative,'content':raw.decode('utf-8'),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'updated_at':datetime.fromtimestamp(after.st_mtime,timezone.utc).isoformat(),'observed_at':datetime.now(timezone.utc).isoformat(),'write_performed':False}
