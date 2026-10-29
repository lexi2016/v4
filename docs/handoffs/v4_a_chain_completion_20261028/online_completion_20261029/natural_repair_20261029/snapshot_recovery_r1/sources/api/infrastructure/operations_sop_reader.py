"""Read-only fixed V4 SOP documents; no caller-supplied filesystem paths."""
from datetime import datetime,timezone
from pathlib import Path
import hashlib,os,stat
from infrastructure.owned_io import SafeRoot

CANONICAL_ROOT=Path('/Users/lexi/Desktop/学习/v4_app')
DOCUMENTS={
    'overview':('SOP 总览','docs/SOP.md'),
    'stage-selection':('阶段选股运行规程','docs/operations/STAGE_SELECTION_SOP.md'),
    'repair-20261028-29':('2026-10-28／29 阶段修复记录','docs/operations/records/2026-10-28_29-stage-selection-repair.md'),
}

def read_sop(document='overview'):
    if document not in DOCUMENTS:raise KeyError('UNKNOWN_SOP_DOCUMENT')
    title,relative=DOCUMENTS[document];root=CANONICAL_ROOT
    if root.resolve(strict=True)!=root or root.is_symlink():raise ValueError('SOP_CANONICAL_ROOT_ALIAS')
    path=root/relative
    if path.resolve(strict=True)!=path or path.is_symlink():raise ValueError('SOP_DOCUMENT_ALIAS')
    before=path.lstat()
    if not stat.S_ISREG(before.st_mode):raise ValueError('SOP_NOT_REGULAR_FILE')
    raw=SafeRoot(root).read_bytes(relative,max_bytes=512*1024);after=path.lstat()
    if (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns):raise ValueError('SOP_CHANGED_REFRESH_REQUIRED')
    return {'status':'READ_OK','id':document,'title':title,'relative_path':relative,'content':raw.decode('utf-8'),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'updated_at':datetime.fromtimestamp(after.st_mtime,timezone.utc).isoformat(),'observed_at':datetime.now(timezone.utc).isoformat(),'write_performed':False}
