"""V192 missing-view completion at the two existing completion boundaries.

No acquisition, selection or GET computation. Publication uses the existing
A_LONG inode and original daily owner's serializer; canonical modules survive.
"""
from __future__ import annotations
import argparse
import copy
import fcntl
import json
import os
from pathlib import Path

from ops import research_panel_daily_product as owner
from ops import materialize_workbench_v192_assets as assets

FLAGS=owner.FLAGS


def prepare_completed(context,product,manifest,observation_date,*,output_root=None):
    """Called only with a completed numeric product, never all5808 computation."""
    verified=assets.original_model_reader(os.environ['V4_SHARED_PACKAGE_ROOT'],
        os.environ['V4_SHARED_DATA_ROOT'],product['data_date'],observation_date)
    missing=sorted({r['ts_code'] for r in verified.rows}-{r['symbol'] for r in product['rows']})
    # Empty symbols means canonical scope to the old score owner. Never call
    # that owner with an empty extension scope.
    if not missing:return dict(status='NO_MISSING_MODEL_VIEWS',numeric_manifest=manifest,**FLAGS)
    base=Path(output_root) if output_root else context.root/'v192_assets/derived'
    # Preserve validated recurrence across days. The original score owner
    # independently checks rules, basis, dates and the complete price prefix.
    identity=dict(numeric_manifest=manifest,model_artifact_sha256=verified.run.verification['artifact_sha256'],
        model_manifest_sha256=verified.run.verification['manifest_sha256'],
        selector_sha256=context.identity['selector_artifact_sha256'],owner_sha256=owner.sha(Path(assets.__file__)),
        renderer_sha256=owner.sha(Path(assets.renderer.__file__)),score_owner_sha256=owner.sha(Path(assets.score.__file__)),symbols=missing)
    destination=base.resolve()/str(context.target)/owner.digest(identity)/'score_action/stock_cache'
    index_path=context.root/'index.json'
    index=json.loads(index_path.read_bytes()) if index_path.is_file() else {}
    current=index.get('v192_assets',{}).get(str(context.target),{})
    if current.get('module'):
        accepted=assets.score.checked(current['module'])
        if accepted.get('identity')==identity and accepted.get('status')=='READY' and accepted.get('completed_symbols')==missing:
            for key in ('manifest','receipt'):assets.score.checked(accepted['charts'][key])
            cache=assets.score.checked(accepted['score_action']['index'])
            for ref in cache['items'].values():assets.score.checked(ref)
            context.unchanged()
            context._v192_asset_reuse=dict(status='NOOP',computed=0,reused=len(missing))
            return current
    for day,descriptor in sorted(index.get('v192_assets',{}).items(),reverse=True):
        if day>=str(context.target) or not descriptor.get('module'):continue
        module=assets.score.checked(descriptor['module'])
        prior=assets.score.checked(module['score_action']['index'])
        for symbol in set(missing)&set(prior['items']):
            row=assets.score.checked(prior['items'][symbol])
            if str(row.get('trade_date',''))>=str(context.target):raise ValueError('V192_FUTURE_RECURRENCE_REJECTED')
            owner.save(destination/symbol/(owner.digest(row['cache_identity'])+'.json'),row,immutable=True)
    return assets.prepare(context,product,manifest,verified,base,symbols=missing)


def attach(index,event,descriptor,root):
    """Only the V192 module pointer and completion digest change."""
    day=descriptor.get('data_date')
    if not descriptor.get('module'):return
    if index.get('dates',{}).get(day)!=descriptor['numeric_manifest']:raise ValueError('V192_NUMERIC_MOVED')
    module=assets.score.checked(descriptor['module'])
    ref=owner.save(Path(root)/'v192_assets/manifests'/(descriptor['module']['sha256']+'.json'),module,immutable=True)
    final={**descriptor,'module':ref}
    index.setdefault('v192_assets',{})[day]=final
    if event.get('data_date')==day:
        event['v192_assets']=final
        event['event_id']=owner.digest({k:v for k,v in event.items() if k!='event_id'})


def at_numeric_completion(context,product,manifest):
    """Find the existing next-observation model artifact, never guess a date."""
    shared=Path(os.environ['V4_SHARED_DATA_ROOT'])
    catalog=json.loads((shared/'latest.json').read_bytes())
    role='A_SHARE_V192_PREMARKET_POOL_V3'
    for key,entry in sorted(catalog.get('entries',{}).items(),reverse=True):
        parts=key.split('/')
        if len(parts)!=2 or parts[1]!=role or parts[0]<=product['data_date']:continue
        # The strict existing reader verifies signal D, observation O, selector,
        # source, receipt and artifact. No catalog hint authorizes a display.
        try:return prepare_completed(context,product,manifest,parts[0])
        except ValueError as error:
            if 'signal' not in str(error).lower():raise
    return dict(status='MODEL_NOT_READY',numeric_manifest=manifest,**FLAGS)


def publication_plan(descriptor,root,stage,lock_path):
    root=Path(root).resolve();stage=Path(stage).resolve()
    if stage==root or stage.is_relative_to(root):raise ValueError('V192_STAGE_MUST_BE_ISOLATED')
    ir=owner.reference(root/'index.json');er=owner.reference(root/'events/latest.json')
    index=assets.score.checked(ir);event=assets.score.checked(er);day=descriptor['data_date']
    if index['dates'].get(day)!=descriptor['numeric_manifest']:raise ValueError('V192_NUMERIC_MOVED')
    module=assets.score.checked(descriptor['module'])
    staged=owner.save(stage/'module.json',module,immutable=True)
    target=root/'v192_assets/manifests'/(descriptor['module']['sha256']+'.json')
    final={**descriptor,'module':dict(path=str(target),sha256=staged['sha256'])}
    after=copy.deepcopy(index);after.setdefault('v192_assets',{})[day]=final
    updated=copy.deepcopy(event)
    if updated.get('data_date')==day:
        updated['v192_assets']=final;updated['event_id']=owner.digest({k:v for k,v in updated.items() if k!='event_id'})
    lock=Path(lock_path);st=lock.lstat()
    if lock.is_symlink() or not lock.is_file():raise ValueError('V192_EXISTING_A_LONG_REQUIRED')
    plan=dict(status='PREPARED_NOT_PUBLISHED',target_root=str(root),stage=str(stage),descriptor=final,
        expected_index=ir,expected_event=er,staged_index=owner.save(stage/'index.json',after),
        staged_event=owner.save(stage/'event.json',updated),immutable_files={str(target):staged},
        shared_owner_lock=dict(path=str(lock),device=st.st_dev,inode=st.st_ino),
        owner_publisher=owner.reference(Path(owner.__file__)),**FLAGS)
    owner.save(stage/'PUBLICATION_PLAN.json',plan);return plan


def publish(plan,*,shared_fd=None):
    """Root calls after review, or the existing preselection completion calls.

    Block on the original lane lock; reprepare after a changed CAS, never merge
    a stale index or overwrite numeric/score/company/other module pointers.
    """
    owner.checked(plan['owner_publisher']);lock=plan['shared_owner_lock']
    fd=shared_fd if shared_fd is not None else os.open(lock['path'],os.O_RDONLY|os.O_NOFOLLOW)
    try:
        if shared_fd is None:fcntl.flock(fd,fcntl.LOCK_EX)
        held=os.fstat(fd);current=os.stat(lock['path'],follow_symlinks=False)
        if (held.st_dev,held.st_ino)!=(lock['device'],lock['inode']) or (current.st_dev,current.st_ino)!=(held.st_dev,held.st_ino):raise ValueError('V192_A_LONG_INODE_MOVED')
        root=Path(plan['target_root'])
        owner.checked(plan['expected_index']);owner.checked(plan['expected_event'])
        before=assets.score.checked(plan['expected_index'])
        if before.get('v192_assets',{}).get(plan['descriptor']['data_date'])==plan['descriptor']:
            return dict(status='NOOP',descriptor=plan['descriptor'],**FLAGS)
        for target,ref in plan['immutable_files'].items():owner.save(target,assets.score.checked(ref),immutable=True)
        index=assets.score.checked(plan['staged_index']);event=assets.score.checked(plan['staged_event'])
        after=owner.save(root/'index.json',index)
        try:receipt=owner.save(root/'events/latest.json',event)
        except Exception:
            if owner.reference(root/'index.json')==after:owner.save(root/'index.json',before)
            raise
        result=dict(status='PUBLISHED_V192_ASSETS',index=after,event=receipt,descriptor=plan['descriptor'],**FLAGS)
        owner.save(Path(plan['stage'])/'PUBLICATION_RECEIPT.json',result);return result
    finally:
        if shared_fd is None:os.close(fd)


def after_preselection(source_date,observation_date):
    """Runs after publication even when the existing V192 artifact was reused."""
    lock=Path(os.environ['V4_DATA_ROOT']).parent/'dispatcher/scheduler_lane_owners/A_LONG.lock'
    fd=os.open(lock,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        # Serialize original chart/cache writes with the numeric owner too.
        fcntl.flock(fd,fcntl.LOCK_EX)
        return _after_preselection_locked(source_date,observation_date,lock,fd)
    finally:os.close(fd)


def _after_preselection_locked(source_date,observation_date,lock,fd):
    root=Path(os.environ['V4_A_SHARE_DAILY_PRODUCT_ROOT'])/'daily_products/a_share'
    index=json.loads((root/'index.json').read_bytes());ref=index.get('dates',{}).get(str(source_date))
    if ref is None:return dict(status='NUMERIC_NOT_READY',**FLAGS)
    product=assets.score.checked(assets.score.checked(ref)['artifact'])
    context=owner.SourceContext(Path(os.environ['V4_STORAGE_PAIR_DATA_ROOT']),int(source_date),
        source_config=(assets.score.checked(product['source_config']),product['source_config']))
    context.root=root
    descriptor=prepare_completed(context,product,ref,observation_date)
    if not descriptor.get('module'):return descriptor
    stage=root.parent.parent/'v192_asset_publication'/descriptor['module']['sha256']
    return publish(publication_plan(descriptor,root,stage,lock),shared_fd=fd)


def main():
    p=argparse.ArgumentParser();p.add_argument('operation',choices=['prepare-publication','publish'])
    p.add_argument('--descriptor',type=Path);p.add_argument('--root',type=Path);p.add_argument('--stage',type=Path);p.add_argument('--lock',type=Path);p.add_argument('--plan',type=Path)
    a=p.parse_args()
    result=(publication_plan(json.loads(a.descriptor.read_bytes()),a.root,a.stage,a.lock) if a.operation=='prepare-publication'
        else publish(json.loads(a.plan.read_bytes())))
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()
