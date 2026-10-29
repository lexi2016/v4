"""Exact active Main clone and four-file overlay; never activates services."""
from pathlib import Path
import hashlib,json,os,plistlib,shutil,subprocess,sys
SOURCE=Path(__file__).resolve().parents[3]
EVIDENCE=Path('/Users/lexi/Desktop/学习/因子工厂/research/a_daily_1530_20261029_r1')
PLIST=Path('/Users/lexi/Library/LaunchAgents/com.lexi.v4.scheduler.plist')
BASE=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/a-chain-natural-repair-20261029-r3-main/app')
CANDIDATE=EVIDENCE/'candidate/a-daily-1530-20261029-r1-main'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    contract=json.loads((EVIDENCE/'CONTRACT_R2.json').read_text())
    raw=PLIST.read_bytes(); plist=plistlib.loads(raw)
    assert plist['WorkingDirectory']==str(BASE),'ACTIVE_ROOT_DRIFT'
    assert raw==(EVIDENCE/'active_main_plist.preimage').read_bytes(),'ACTIVE_PLIST_DRIFT'
    for p,h in contract['baseline_sha256'].items(): assert sha(BASE/p)==h,('BASELINE_DRIFT',p)
    assert not CANDIDATE.exists(),'CANDIDATE_EXISTS'
    assert shutil.disk_usage(EVIDENCE).free>1024**3,'INSUFFICIENT_SPACE'
    CANDIDATE.mkdir(parents=True)
    # APFS copy-on-write clone preserves the established release baseline.
    subprocess.run(['/bin/cp','-cR',str(BASE),str(CANDIDATE/'app')],check=True)
    overlay=[]
    for p,h in contract['baseline_sha256'].items():
        shutil.copy2(SOURCE/p,CANDIDATE/'app'/p)
        overlay.append({'path':p,'before_sha256':h,'after_sha256':sha(SOURCE/p)})
    for test in ('test_a_daily_1530_schedule.py','test_a_daily_1530_migration.py'):
        shutil.copy2(SOURCE/'tests'/test,CANDIDATE/'app/tests'/test)
    manifest=json.loads((BASE.parent/'release-manifest.json').read_text())
    manifest.update(release_id=CANDIDATE.name,source_root=str(SOURCE),parent_release_root=str(BASE.parent),
                    activation_status='NOT_ACTIVATED',schedule_delta=overlay)
    for row in manifest.get('app_files',[]):
        f=CANDIDATE/'app'/row['path']
        if row['path'] in contract['baseline_sha256']:
            row.update(sha256=sha(f),size=f.stat().st_size)
    encoded=(json.dumps(manifest,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
    (CANDIDATE/'release-manifest.json').write_bytes(encoded)
    # Inner legacy manifest is retained as baseline bytes, avoiding self-hash.
    # The outer release manifest owns the candidate inventory.
    sys.path.insert(0,str(SOURCE))
    from ops.api_release_integration import inventory_tree,inventory_digest
    entries=inventory_tree(CANDIDATE/'app')
    manifest['app_root']=str(CANDIDATE/'app')
    manifest['candidate']={'root':str(CANDIDATE),'app_root':str(CANDIDATE/'app'),'release_id':CANDIDATE.name,'module_role':'main'}
    manifest['application_inventory']={'entries':entries,'entry_count':len(entries),'aggregate_sha256':inventory_digest(entries)}
    (CANDIDATE/'release-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
    def replace(v):
        if isinstance(v,str):return v.replace(str(BASE.parent),str(CANDIDATE)).replace(BASE.parent.name,CANDIDATE.name)
        if isinstance(v,list):return [replace(x) for x in v]
        if isinstance(v,dict):return {k:replace(x) for k,x in v.items()}
        return v
    staged=replace(plist)
    staged["EnvironmentVariables"]["V4_RELEASE_MANIFEST_SHA256"]=sha(CANDIDATE/"release-manifest.json")
    (EVIDENCE/'candidate_main.plist').write_bytes(plistlib.dumps(staged))
    # These immutable preimages are the rollback and activation CAS identities.
    receipt={'status':'PREPARED_NOT_ACTIVATED','candidate_root':str(CANDIDATE),'source_root':str(SOURCE),
        'active_root':str(BASE),'active_plist_sha256':hashlib.sha256(raw).hexdigest(),
        'candidate_plist_sha256':sha(EVIDENCE/'candidate_main.plist'),'rollback_plist':str(EVIDENCE/'active_main_plist.preimage'),
        'overlay':overlay,'RESEARCH_ONLY':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}
    (EVIDENCE/'preparation_receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'status':receipt['status'],'candidate_root':str(CANDIDATE),'overlay_count':len(overlay)}))
if __name__=='__main__':main()
