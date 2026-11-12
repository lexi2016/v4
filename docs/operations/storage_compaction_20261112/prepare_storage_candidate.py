"""Inactive Main storage delta and Stage owner-only repin from actual LKG.

Reuse the prior reviewed clone/inventory/attestation preparation helpers. Only
this task's three Main paths and Stage control identity may change. No activation.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys

PACKET=Path(__file__).resolve().parent
WORKTREE=PACKET.parents[2]
helper=PACKET.parent/'prepool_repair_20261112/prepare_main_stage_candidate.py'
spec=importlib.util.spec_from_file_location('prepool_candidate_helpers',helper)
h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate-root',type=Path,required=True)
    parser.add_argument('--evidence-root',type=Path,required=True)
    args=parser.parse_args();root=args.candidate_root
    h.require(root.is_absolute() and not root.exists(),'NEW_ABSOLUTE_CANDIDATE_REQUIRED')
    ml=Path.home()/'Library/LaunchAgents/com.lexi.v4.scheduler.plist'
    sl=Path.home()/'Library/LaunchAgents/com.lexi.stage-center.scheduler.plist'
    mr,sr=ml.read_bytes(),sl.read_bytes();mp,sp=plistlib.loads(mr),plistlib.loads(sr)
    me,se=mp['EnvironmentVariables'],sp['EnvironmentVariables']
    oldm,olds=Path(me['V4_APP_ROOT']),Path(se['V4_APP_ROOT'])
    oms,oss=Path(me['V4_RELEASE_MANIFEST_PATH']),Path(se['V4_RELEASE_MANIFEST_PATH'])
    h.require(h.sha(oms)==me['V4_RELEASE_MANIFEST_SHA256']=='1ecc6373c11eb36ff09881d925be20607e612ce2eab8a2c19961f16513b99643','CURRENT_PREPOOL_MAIN_REQUIRED')
    h.require(h.sha(oss)==se['V4_RELEASE_MANIFEST_SHA256']=='6fd32ec201f928cd96ef73227381b948d9d3a3d27bad45863295d3fe7bf5b94a','CURRENT_PREPOOL_STAGE_REQUIRED')
    binding_path=PACKET/'SOURCE_BINDING.json';binding=h.load(binding_path)
    for name,item in binding['main_delta'].items():
        src=WORKTREE/name
        h.require(h.sha(src)==item['after_sha256'],'STORAGE_SOURCE_DRIFT:'+name)
        before=oldm/name
        h.require((h.sha(before) if before.exists() else None)==item['live_before_sha256'],'STORAGE_LKG_PREIMAGE_DRIFT:'+name)
    policy_path=Path(me['V4_RESEARCH_RETENTION_POLICY']);policy=h.load(policy_path)
    h.require(h.sha(policy_path)==me['V4_RESEARCH_RETENTION_POLICY_SHA256'],'POLICY_DRIFT')
    pr=policy['managed_pin_inventory'];ar=policy['single_generation_lifecycle']['reader_inventory']
    h.require(h.sha(pr['path'])==pr['sha256'] and h.sha(ar['path'])==ar['sha256'],'CONTROL_REF_DRIFT')
    pins,att=h.load(pr['path']),h.load(ar['path'])
    for source in pins['source_bindings']:h.require(h.sha(source['path'])==source['sha256'],'SOURCE_PIN_DRIFT:'+source['path'])
    for consumer in att['consumers']:
        for source in consumer.get('source_refs',[]):h.require(h.sha(source['path'])==source['sha256'],'READER_SOURCE_DRIFT')
    stage_readers=[c for c in att['consumers'] if c['label']==sp['Label']]
    h.require(len(stage_readers)==1 and stage_readers[0]['plist_sha256']==h.sha(sl),'CURRENT_STAGE_READER_REQUIRED')
    oldc=h.load(se['STAGE_CENTER_CONFIG']);old_owner=copy.deepcopy(oldc['research_owner_binding'])
    h.require(old_owner==dict(app_root=str(oldm),release_id=me['V4_RELEASE_ID'],manifest_path=str(oms),manifest_sha256=h.sha(oms)),'STAGE_CURRENT_OWNER_DRIFT')
    h.require(len(oldc['research_historical_owner_bindings'])==11,'EXPECTED_ELEVEN_HISTORICAL_OWNERS')
    ma,sa=root/'main/app',root/'stage/app';mb=h.clone_inventory(oldm,ma,h.load(oms))
    for name in binding['main_delta']:
        dst=ma/name;dst.parent.mkdir(parents=True,exist_ok=True)
        if dst.exists():os.chmod(dst,0o644)
        shutil.copy2(WORKTREE/name,dst)
    mm=h.with_inventory(h.load(oms),ma)
    before={e['path']:e for e in mb};after={e['path']:e for e in mm['application_inventory']['entries']}
    changed=sorted(k for k in set(before)|set(after) if before.get(k)!=after.get(k))
    h.require(changed==sorted(binding['main_delta']),'EXACT_STORAGE_MAIN_DELTA_REQUIRED')
    now=datetime.now(timezone.utc).isoformat();mid,sid=root.name+'-main',root.name+'-stage'
    commit=subprocess.check_output(['git','-C',str(WORKTREE),'rev-parse','HEAD'],text=True).strip()
    for name in binding['main_delta']:
        committed=subprocess.check_output(['git','-C',str(WORKTREE),'show',commit+':'+name])
        h.require(__import__('hashlib').sha256(committed).hexdigest()==binding['main_delta'][name]['after_sha256'],'COMMITTED_STORAGE_BYTES_REQUIRED')
    mm.update(app_root=str(ma),release_id=mid,candidate=root.name,source_root=str(WORKTREE),source_commit=commit,
        parent_release_root=str(oms.parent),parent_manifest_sha256=h.sha(oms),generated_at=now,
        activation_status='PREPARED_NOT_ACTIVATED',deployment_status='PREPARED')
    mm['storage_compaction']=dict(source_binding=h.ref(binding_path),source_script=h.ref(__file__),
        mode='BYTE_PATH_SHA_PRESERVING_NATIVE_MAINTENANCE',pending='ORIGINAL_COMPLETION_EVENT_ONLY',
        independent_review='REQUIRED_BEFORE_ACTIVATION',business_flags_unchanged=True)
    ms=h.save(root/'main/release-manifest.json',mm)
    sb=h.clone_inventory(olds,sa,h.load(oss));config=copy.deepcopy(oldc)
    config['research_owner_binding']=dict(app_root=str(ma),release_id=mid,manifest_path=ms['path'],manifest_sha256=ms['sha256'])
    config['research_historical_owner_bindings'].append(old_owner);config['release_id']=sid
    h.require(len({x['app_root'] for x in [config['research_owner_binding'],*config['research_historical_owner_bindings']]})==13,'OWNER_ROOT_DUPLICATE')
    h.require(config['research_transition_owner_binding']==oldc['research_transition_owner_binding'],'TRANSITION_CHANGED')
    cp=sa/'stage_center_tick_config.json';os.chmod(cp,0o644);h.save(cp,config)
    sm=h.with_inventory(h.load(oss),sa);stage_changed=h.changed_paths(sb,sm['application_inventory']['entries'])
    h.require(stage_changed==['stage_center_tick_config.json'],'STAGE_CODE_CHANGED')
    sm.update(app_root=str(sa),release_id=sid,candidate=root.name,parent_release_root=str(oss.parent),
        parent_manifest_sha256=h.sha(oss),generated_at=now,activation_status='PREPARED_NOT_ACTIVATED',deployment_status='PREPARED')
    sm['storage_main_owner_repin']=dict(source_script=h.ref(__file__),previous_history_count=11,historical_count=12,
        transition_unchanged=True,code_bytes_changed=False)
    ss=h.save(root/'stage/release-manifest.json',sm)
    def remap(value):
        if isinstance(value,str):
            for old,new in [(oldm,ma),(olds,sa)]:
                if value==str(old) or value.startswith(str(old)+'/'):return str(new)+value[len(str(old)):]
            return value
        if isinstance(value,list):return [remap(x) for x in value]
        if isinstance(value,dict):return {k:remap(x) for k,x in value.items()}
        return value
    proposed_s=remap(copy.deepcopy(sp));proposed_s['EnvironmentVariables'].update(V4_APP_ROOT=str(sa),V4_RELEASE_ID=sid,
        V4_RELEASE_MANIFEST_PATH=ss['path'],V4_RELEASE_MANIFEST_SHA256=ss['sha256'],STAGE_CENTER_CONFIG=str(cp))
    proposed_s['WorkingDirectory']=str(sa);spp=root/'stage/proposed.plist';spp.write_bytes(plistlib.dumps(proposed_s,sort_keys=False));(root/'stage/before.plist').write_bytes(sr)
    pin_changes=[]
    for index,source in enumerate(pins['source_bindings']):
        old=copy.deepcopy(source)
        if source['path']==str(sl):source['sha256']=h.sha(spp)
        else:source.update(h.ref(Path(remap(source['path']))))
        if source!=old:pin_changes.append(dict(index=index,before=old,proposed=copy.deepcopy(source)))
    pins.update(expected_main_app_root=str(ma),generated_at=now)
    newpins=h.save(root/'main-control/research_storage_pins.json',pins)
    for consumer in att['consumers']:
        if consumer['label']==sp['Label']:consumer['plist_sha256']=h.sha(spp)
        consumer['source_refs']=[h.ref(Path(remap(r['path']))) for r in consumer.get('source_refs',[])]
    newatt=h.save(root/'main-control/reader-attestation.json',att)
    policy['managed_pin_inventory']=newpins;policy['single_generation_lifecycle']['reader_inventory']=newatt
    newpolicy=h.save(root/'main-control/research_storage_policy.json',policy)
    proposed_m=remap(copy.deepcopy(mp));proposed_m['EnvironmentVariables'].update(V4_APP_ROOT=str(ma),V4_RELEASE_ID=mid,
        V4_RELEASE_MANIFEST_PATH=ms['path'],V4_RELEASE_MANIFEST_SHA256=ms['sha256'],V4_RESEARCH_RETENTION_POLICY=newpolicy['path'],V4_RESEARCH_RETENTION_POLICY_SHA256=newpolicy['sha256'])
    proposed_m['WorkingDirectory']=str(ma);mpp=root/'main-control/proposed.plist';mpp.write_bytes(plistlib.dumps(proposed_m,sort_keys=False));(root/'main-control/before.plist').write_bytes(mr)
    h.require(ml.read_bytes()==mr and sl.read_bytes()==sr and h.sha(policy_path)==me['V4_RESEARCH_RETENTION_POLICY_SHA256'],'LIVE_IDENTITY_CHANGED_DURING_PREPARE')
    out=dict(status='PREPARED_NOT_ACTIVATED',root=str(root),source_commit=commit,source_binding=h.ref(binding_path),source_script=h.ref(__file__),
        main=dict(app_root=str(ma),manifest=ms,inventory_changed=changed,live_plist=str(ml),before_plist=h.ref(root/'main-control/before.plist'),
            proposed_plist=h.ref(mpp),before_policy=h.ref(policy_path),proposed_policy=newpolicy,proposed_pins=newpins,proposed_reader_attestation=newatt),
        stage=dict(app_root=str(sa),manifest=ss,inventory_changed=stage_changed,live_plist=str(sl),before_plist=h.ref(root/'stage/before.plist'),
            proposed_plist=h.ref(spp),config=h.ref(cp),previous_history_count=11,historical_count=12,transition_unchanged=True,code_bytes_changed=False),
        pin_changes=pin_changes,no_live_actions=True,RESEARCH_ONLY=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)
    h.save(root/'PREPARE_RECEIPT.json',out);h.save(args.evidence_root/'STORAGE_MAIN_STAGE_PREPARE.json',out)
    print(json.dumps(dict(status=out['status'],root=str(root),source_commit=commit,main_changed=changed,stage_changed=stage_changed)))


if __name__=='__main__':main()
