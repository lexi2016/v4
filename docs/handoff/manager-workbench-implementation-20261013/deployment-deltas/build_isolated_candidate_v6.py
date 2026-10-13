"""Use the existing active-base delta builder; candidate only, never publish."""
from pathlib import Path
import hashlib
import json
import re
import shutil
import sys
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
sys.path.insert(0,str(ROOT))
from ops.api_release_integration import read_active_release,build_integrated_app,_base_binding,_diff_proof,DELTA_SCHEMA_VERSION


def build():
    plist=Path('/Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist')
    active=read_active_release(plist)
    recorded=json.loads((HERE/'preimages.json').read_text())
    frozen=next(r for r in recorded if r.get('kind')=='api')
    if active['app_root']!=frozen['app_root'] or active['release_manifest_sha256']!=frozen['manifest_sha256'] or active['api_plist_sha256']!=frozen['plist_sha256']:
        raise ValueError('ACTIVE_API_DRIFT_REQUIRES_REBASE')
    source=HERE/'api-delta-source-v6';source.mkdir(exist_ok=True)
    relative='apps/api/v35_api/app.py'
    paths={relative:HERE/'api-active-candidate'/relative}
    for path in (ROOT/'v4/manager_workbench').rglob('*.py'):
        if '__pycache__' not in path.parts:paths[str(path.relative_to(ROOT))]=path
    for relative in ['apps/web/src/manager-selection/main.ts','apps/web/manager-selection/index.html']:
        paths[relative]=ROOT/relative
    for path in (ROOT/'apps/web/src/manager-workbench').rglob('*'):
        if path.is_file() and '__tests__' not in path.parts and path.suffix in {'.ts','.vue','.css'}:
            paths[str(path.relative_to(ROOT))]=path
    web_dist=HERE/'.tmp/web-dist-v6'
    if not web_dist.exists():raise ValueError('NEW_MANAGER_FRONTEND_BUILD_REQUIRED')
    # Include only the manager entry and its emitted dependency closure. The
    # full workspace build must not replace unrelated active pages or bundles.
    pending=[web_dist/'manager-selection/index.html'];seen=set()
    while pending:
        path=pending.pop()
        if path in seen:continue
        seen.add(path)
        if not path.is_file():raise ValueError('MANAGER_ASSET_DEPENDENCY_MISSING')
        paths['apps/web/dist/'+str(path.relative_to(web_dist))]=path
        for filename in re.findall(r'[A-Za-z0-9_.-]+\.(?:js|css|woff2?|svg|png)',path.read_text()):
            dependency=web_dist/'assets'/filename
            if dependency.is_file() and dependency not in seen:pending.append(dependency)
    for relative in ['contracts/us_equity_calendar.py' ,'contracts/us_equity_calendar_2026.json']:
        paths[relative]=ROOT/relative
    entries=[]
    for relative,path in sorted(paths.items()):
        target=source/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
        before_path=Path(active['app_root'])/relative;before=before_path.read_bytes() if before_path.exists() else None
        after=path.read_bytes();before_sha=hashlib.sha256(before).hexdigest() if before is not None else None;after_sha=hashlib.sha256(after).hexdigest()
        if before_sha==after_sha:continue
        diff,hunks=_diff_proof(before,after) if before is not None else (None,None)
        entries.append(dict(path=relative,before_sha256=before_sha,after_sha256=after_sha,unified_diff_sha256=diff,unified_diff_hunk_count=hunks))
    delta=HERE/'api-integration-delta-v6-receipt.json';delta.write_text(json.dumps(dict(schema_version=DELTA_SCHEMA_VERSION,base=_base_binding(active),entries=entries),indent=2)+'\n')
    candidate=HERE/'isolated-api-candidate-v6';candidate.mkdir(exist_ok=True)
    result=build_integrated_app(active_api_plist_path=plist,source_root=source,candidate_root=candidate,delta_receipt_path=delta,
        explicit_untracked_paths=[e['path'] for e in entries if e['before_sha256'] is None])
    after=read_active_release(plist)
    if after['application_inventory_sha256']!=active['application_inventory_sha256']:raise ValueError('ACTIVE_API_DRIFT_DURING_BUILD')
    (HERE/'isolated-candidate-build-v6-receipt.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'candidate_app':str(candidate/'app'),'delta_count':len(entries),'preserved_non_delta_count':result['non_delta_entry_count']}))

if __name__=='__main__':build()
