"""Prepare only manager increments on pinned canonical/active preimages.

Does not publish or change active files. Generic release integration performs
candidate inventory, delta application, drift checks and publication separately.
"""
from pathlib import Path
import difflib
import hashlib
import json

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]


def api_patch(text):
    for line in ['from apps.api.v35_api.manager_research_router import create_manager_research_router\n',
                 'from apps.api.v35_api.manager_workbench_router import create_manager_workbench_router, ManagerWorkbenchResearchReader\n',
                 '_MANAGER_RESEARCH_RUNTIME_PACKAGE = "_v4_manager_research_runtime"\n']:
        if text.count(line)!=1:raise ValueError('API_MANAGER_PREIMAGE_CHANGED')
        text=text.replace(line,'')
    start=text.index('def _load_manager_research_components()')
    end=text.index('def _strict_date(',start)
    text=text[:start]+text[end:]
    prefix, body = text.split('def create_app(',1)
    signature, rest = body.split(') -> FastAPI:',1)
    text=prefix+'def create_app('+signature+'    manager_workbench_config: Any | None = None,\n) -> FastAPI:'+rest
    start=text.index('    # V4 manager research is a separate date/input keyed job lane.')
    end=text.index('    preview_root = ',start)
    replacement='''    # The new manager is the sole manager write owner in this application.
    from v4.manager_workbench.binding import api_config, assemble_api
    manager_config = api_config(
        manager_root=_resolve_manager_research_state_root(manager_research_state_root, data_root),
        shared_root=(os.environ.get("V4_MANAGER_SCREEN_AUTHORITY_ROOT")
                     or os.environ.get("V4_MANAGER_SECURITY_MASTER_ROOT") or shared_data_root),
        stage_root=configured_selection_root,
        us_root=store.root,
        relation_root=Path(__file__).resolve().parents[3],
        injected=manager_workbench_config,
    )
    assemble_api(app, config=manager_config)

'''
    return text[:start]+replacement+text[end:]


def scheduler_patch(text):
    needle='        announcement_hook = AnnouncementCycleHook.from_environment(clock=now)'
    if text.count(needle)!=1:raise ValueError('SCHEDULER_MANAGER_PREIMAGE_CHANGED')
    replacement='''        if os.environ.get("V4_MANAGER_WORKBENCH_CONFIG_PATH", "").strip():
            # Fail closed: never initialize the old capture owner on this branch.
            from v4.manager_workbench.supervisor import WorkbenchHook
            announcement_hook = WorkbenchHook.from_environment(clock=now)
        else:
            announcement_hook = AnnouncementCycleHook.from_environment(clock=now)'''
    return text.replace(needle,replacement)


def prepare():
    records=[]
    for name,relative,patch in [('canonical','apps/api/v35_api/app.py',api_patch),('api-active','apps/api/v35_api/app.py',api_patch),
                              ('canonical','ops/run_v35_macos_scheduler_daemon.py',scheduler_patch),('scheduler-active','ops/run_v35_macos_scheduler_daemon.py',scheduler_patch)]:
        before=(HERE/(name+'-before')/relative).read_bytes()
        after=patch(before.decode()).encode()
        path=HERE/(name+'-candidate')/relative
        path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(after)
        diff=''.join(difflib.unified_diff(before.decode().splitlines(keepends=True),after.decode().splitlines(keepends=True),fromfile='a/'+relative,tofile='b/'+relative))
        delta=HERE/(name+'-'+Path(relative).stem+'.patch');delta.write_text(diff)
        records.append(dict(base=name,path=relative,before_sha256=hashlib.sha256(before).hexdigest(),after_sha256=hashlib.sha256(after).hexdigest(),delta=delta.name))
        if name=='canonical':(ROOT/relative).write_bytes(after)
    (HERE/'delta-receipt.json').write_text(json.dumps(records,indent=2)+'\n')
    return records


if __name__=='__main__':prepare()
