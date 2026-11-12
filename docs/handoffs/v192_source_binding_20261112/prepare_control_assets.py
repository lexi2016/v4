"""Prepare existing policy/pin/reader-attestation identities for inactive R3."""
import copy,hashlib,json,plistlib
from pathlib import Path
HERE=Path(__file__).resolve().parent
BASE=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/v4-storage-compaction-20261112-r1')

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def load(p):return json.loads(Path(p).read_bytes())
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2,sort_keys=True)+'\n')
def main():
    plan=load(HERE/'INACTIVE_CANDIDATES_R3.json');dest=Path(plan['candidate_root']);control=dest/'main-control';control.mkdir(exist_ok=True)
    policy_path=BASE/'main-control/research_storage_policy.json'
    assert sha(policy_path)=='7d0c4c367f864e0d84a37aeb517b446a5eb6a8cf8f06cf84676d82764f28b499'
    policy=load(policy_path);pins=load(policy['managed_pin_inventory']['path']);att=load(policy['single_generation_lifecycle']['reader_inventory']['path'])
    assert sha(policy['managed_pin_inventory']['path'])==policy['managed_pin_inventory']['sha256']
    assert sha(policy['single_generation_lifecycle']['reader_inventory']['path'])==policy['single_generation_lifecycle']['reader_inventory']['sha256']
    for role,record in plan['roles'].items():
        p=Path(record['prepared_plist']['path']);v=plistlib.loads(p.read_bytes());v['EnvironmentVariables']['V4_RELEASE_ID']=record['binding']['release_id']
        p.write_bytes(plistlib.dumps(v));p.chmod(0o600)
    stage=plan['roles']['stage'];stage_live=stage['original_plist']['path'];stage_sha=sha(stage['prepared_plist']['path'])
    def rebase(value):
        if isinstance(value,list):return [rebase(x)for x in value]
        if not isinstance(value,dict):return value
        out={k:rebase(v)for k,v in value.items()}
        for key in ['path','expected_main_app_root']:
            text=out.get(key)
            if isinstance(text,str):
                for role in ['main','stage']:
                    old=str(BASE/role/'app');new=plan['roles'][role]['binding']['app_root']
                    if text==old or text.startswith(old+'/'):
                        out[key]=new+text[len(old):]
                        if key=='path' and 'sha256'in out:out['sha256']=sha(out[key])
        if out.get('path')==stage_live and 'sha256'in out:out['sha256']=stage_sha
        if out.get('plist_path')==stage_live and 'plist_sha256'in out:out['plist_sha256']=stage_sha
        return out
    pins=rebase(pins);att=rebase(att)
    assert pins['expected_main_app_root']==plan['roles']['main']['binding']['app_root']
    save(control/'research_storage_pins.json',pins);save(control/'reader-attestation.json',att)
    policy['managed_pin_inventory']=dict(path=str(control/'research_storage_pins.json'),sha256=sha(control/'research_storage_pins.json'))
    policy['single_generation_lifecycle']['reader_inventory']=dict(path=str(control/'reader-attestation.json'),sha256=sha(control/'reader-attestation.json'))
    save(control/'research_storage_policy.json',policy)
    main_record=plan['roles']['main'];p=Path(main_record['prepared_plist']['path']);v=plistlib.loads(p.read_bytes());env=v['EnvironmentVariables']
    env['V4_RESEARCH_RETENTION_POLICY']=str(control/'research_storage_policy.json');env['V4_RESEARCH_RETENTION_POLICY_SHA256']=sha(control/'research_storage_policy.json')
    p.write_bytes(plistlib.dumps(v));p.chmod(0o600)
    for record in plan['roles'].values():record['prepared_plist']['sha256']=sha(record['prepared_plist']['path'])
    plan['control']=dict(base_policy=dict(path=str(policy_path),sha256=sha(policy_path)),prepared_policy=dict(path=str(control/'research_storage_policy.json'),sha256=sha(control/'research_storage_policy.json')),
        pin_inventory=policy['managed_pin_inventory'],reader_attestation=policy['single_generation_lifecycle']['reader_inventory'])
    save(HERE/'INACTIVE_CANDIDATES_R3.json',plan)
    print(json.dumps(dict(status='PREPARED_NOT_ACTIVATED',control=str(control),policy_limits_and_permissions_unchanged=True)))
if __name__=='__main__':main()
