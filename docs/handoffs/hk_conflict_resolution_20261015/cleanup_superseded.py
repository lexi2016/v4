"""Same-volume rename of the exact seven never-activated candidate roots only."""
from pathlib import Path
from contextlib import ExitStack
from datetime import datetime,timezone
import hashlib,json,os,subprocess,sys

H=Path(__file__).resolve().parent;ROOT=H.parents[2];sys.path.insert(0,str(ROOT))
from ops.api_release_integration import shared_api_release_lock
from infrastructure.interprocess_lock import owned_interprocess_lock
PENDING=Path('/Users/lexi/Desktop/待删除')
DEST=PENDING/'港股口径裁决_20261015_废弃代码候选'
RELEASES=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases')
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def now():return datetime.now(timezone.utc).isoformat()
def inspect(root):
    manifest=root/'release-manifest.json';files=[p for p in root.rglob('*') if p.is_file()]
    return dict(root_inode=root.stat().st_ino,device=root.stat().st_dev,manifest_inode=manifest.stat().st_ino,
        manifest_sha256=sha(manifest),file_count=len(files),file_bytes=sum(p.stat().st_size for p in files))
def main():
    assert json.loads((H/'ONLINE_REVIEW.json').read_text())['verdict']=='PASS'
    frozen=json.loads((H/'SUPERSEDED_CANDIDATES.json').read_text());items=frozen['candidates'];assert len(items)==7
    allowed={f'hk-history-adjudication-{role}-20261015-r{rev}' for role,revs in [('api',[1,2,3]),('scheduler',[1,2]),('shared',[1,2])] for rev in revs}
    assert {Path(item['root']).name for item in items}==allowed
    assert PENDING.is_dir() and not PENDING.is_symlink() and not DEST.exists()
    result=dict(status='PREFLIGHT',started_at=now(),method='SAME_VOLUME_OS_RENAME',raw_or_current_or_rollback_roots_moved=False,
        service_commands_executed=[],source_copied=False,source_deleted=False,items=[])
    with ExitStack() as stack:
        stack.enter_context(shared_api_release_lock(Path('/Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist')))
        for name in ['.com.lexi.v35.scheduler.release.lock','com.lexi.v35.scheduler.release.lock']:
            stack.enter_context(owned_interprocess_lock(Path('/Users/lexi/Library/LaunchAgents')/name,timeout_seconds=2,timeout_message='SCHEDULER_RELEASE_LOCK_BUSY'))
        plists=list(Path('/Users/lexi/Library/LaunchAgents').glob('*.plist'))+[H/'api.plist.staged',H/'scheduler.plist.staged']
        launch={str(p):p.read_bytes() for p in plists}
        online=json.loads((H/'ONLINE_RECEIPT.json').read_text())
        for role,d in online['services'].items():
            path=Path('/Users/lexi/Library/LaunchAgents')/('com.lexi.v35.api-only.plist' if role=='api' else 'com.lexi.v35.scheduler.plist')
            assert sha(path)==d['plist_sha256'],'Live binding changed before bounded cleanup'
        ps=subprocess.run(['ps','-axo','pid=,command='],capture_output=True,text=True,check=True).stdout
        domain=subprocess.run(['launchctl','print',f'gui/{os.getuid()}'],capture_output=True,text=True,check=True).stdout
        for item in items:
            root=Path(item['root']);target=DEST/root.name
            assert root.parent==RELEASES and root.is_dir() and not root.is_symlink()
            assert not target.exists() and root.stat().st_dev==PENDING.stat().st_dev
            assert all(str(root).encode() not in raw for raw in launch.values()),'Active/staged launch reference'
            assert str(root) not in ps and str(root) not in domain,'Active process/loaded launch reference'
            opened=subprocess.run(['lsof','-nP','+D',str(root),'-Fpcfn'],capture_output=True,text=True)
            assert opened.returncode==1 and not opened.stdout.strip(),'Candidate still has active open files'
            state=inspect(root);assert state['file_bytes']==item['file_bytes']
            result['items'].append(dict(original_root=str(root),target_root=str(target),before=state,
                active_launch_or_staged_reference=False,active_process_or_open_file_reference=False,
                checked_user_launch_plist_count=len(plists)-2,ever_activated=False))
        DEST.mkdir()
        try:
            for item in result['items']:
                root,target=Path(item['original_root']),Path(item['target_root'])
                os.rename(root,target);item['renamed_at']=now();item['after']=inspect(target)
                assert item['before']==item['after'] and not root.exists()
                item['same_volume_inode_manifest_size_preserved']=True
                (H/'CLEANUP_RECEIPT.json').write_text(json.dumps(result,sort_keys=True,ensure_ascii=False,indent=2)+'\n')
            result.update(status='COMPLETE',finished_at=now(),moved_root_count=7,total_file_bytes=sum(i['before']['file_bytes'] for i in result['items']))
        except BaseException as error:
            result.update(status='PARTIAL_STOPPED_NO_BLIND_RETRY',failure=type(error).__name__,finished_at=now());raise
        finally:(H/'CLEANUP_RECEIPT.json').write_text(json.dumps(result,sort_keys=True,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(status=result['status'],moved_root_count=7,total_file_bytes=result['total_file_bytes'],destination=str(DEST)),ensure_ascii=False))

if __name__=='__main__':main()
