"""Root's post-stage original-loader read-only probe; no run_sync/provider."""
from pathlib import Path
import hashlib,importlib,json,os,sys

def audit(event,args):
    if event in {'socket.connect','socket.connect_ex','socket.sendto','socket.getaddrinfo'}:raise RuntimeError('PROBE_NETWORK_FORBIDDEN')
    if event=='open':
        path,mode,flags=args
        if (isinstance(mode,str) and any(c in mode for c in 'wax+')) or (isinstance(flags,int) and flags&(os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND)):raise RuntimeError('PROBE_FILE_WRITE_FORBIDDEN')

def main():
    main_app,component=map(Path,sys.argv[1:3]);entry=component/'a_sync/app/ops/a_share_daily_sync.py';root=component/'a_sync/component'
    sys.addaudithook(audit);sys.path.insert(0,str(main_app))
    from ops.macos_research_panel_daily_authority import _load_authority_module
    import ops.macos_research_panel_daily_authority as caller
    assert Path(caller.__file__)==main_app/'ops/macos_research_panel_daily_authority.py'
    m=_load_authority_module(entry,'lifecycle_materialized_original_strict_entry')
    assert Path(m.__file__)==root/'ops/a_share_daily_sync.py'
    # Facade run_sync lazily imports this exact helper; import it read-only
    # using that same module name, without calling run_sync.
    helper=importlib.import_module('ops._a_share_daily_sync_parts.sync_workflow')
    assert Path(helper.__file__)==root/'ops/_a_share_daily_sync_parts/sync_workflow.py'
    assert len(m._PINS)==15 and m._COMPONENT_MANIFEST_SHA=='67d3abe86e6035a4b2461941b07a57aee096e6be05c95d32f498c8e90fe7c1ef'
    assert os.environ['V35_A_SYNC_SEED_ADJUSTMENT_INPUTS']==str(root/'seed-evidence-descriptor.json')
    assert m.LIFECYCLE_NOTES_SHA256=='8f90adb3aac2791ed373949e227fcd4efd16d3cd294bcc111e2ba4674e9b906a'
    assert hashlib.sha256((root/'ops/a_share_lifecycle_notes.json').read_bytes()).hexdigest()==m.LIFECYCLE_NOTES_SHA256
    print(json.dumps({'status':'MATERIALIZED_ORIGINAL_STRICT_LOADER_PASS','entry':str(entry),'caller':caller.__file__,'facade':m.__file__,'workflow':helper.__file__,'pins':len(m._PINS),'seed_path':os.environ['V35_A_SYNC_SEED_ADJUSTMENT_INPUTS'],'component_manifest_sha256':m._COMPONENT_MANIFEST_SHA,'provider_calls':0,'network_calls':0,'business_execution':False},sort_keys=True))
if __name__=='__main__':main()
