"""Four fixed human-authorized administrative dispositions; never execution proof.

This CLI only writes private backups and one immutable receipt. Original task
records, processes, locks and services are never changed. Release continuation
must separately pin the receipt and the same immutable PREPARED products.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from prepare_release import digest, exact, json_bytes, read_json, require, sha

AUTHORIZATION_PATH = Path('/Users/lexi/.codex/worktrees/us-hk-selection-closure-20261023/v4_app/.superpowers/sdd/2026-10-23-us-hk-selection-closure/scratch/deployment/authorized-four-recovery/AUTHORIZATION.json')
AUTHORIZATION_SHA256 = 'f3fb7b7d34fd07cb9afa60fcdad293f5becdc5b76f57049483f225d524eda5df'
DISPOSITION = 'MANUALLY_ABANDONED_OR_INTERRUPTED_EXECUTION_UNKNOWN'


def authority(pin):
    require(pin == dict(path=str(AUTHORIZATION_PATH),sha256=AUTHORIZATION_SHA256),'FOUR_AUTHORITY_NOT_EXACT')
    value=read_json(pin['path'],pin['sha256'])
    require(value.get('schema')=='v4.us_hk.explicit_user_recovery_authorization.v1' and
            value.get('verbatim_answer')=='授权处置这 4 条旧任务并继续发布' and
            value.get('authorized_disposition')=='人工放弃／中断；执行状态未证实','FOUR_HUMAN_AUTHORITY_REQUIRED')
    records=value.get('records',[])
    require(len(records)==4 and len({r['path'] for r in records})==4 and
            [r['kind'] for r in records].count('HK_workspace')==3 and
            [r['kind'] for r in records].count('Workbench')==1,'FOUR_RECORD_SET_INVALID')
    return value


def original(record):
    path=exact(record['path']);require(path.is_file() and path.stat().st_size==record['observed_bytes'],'FOUR_ORIGINAL_SIZE_DRIFT')
    # Bound every read to the authorized metadata size, never a raw panel/context.
    require(0<record['observed_bytes']<=1471,'FOUR_ORIGINAL_UNBOUNDED')
    with path.open('rb') as stream:raw=stream.read(record['observed_bytes']+1)
    require(len(raw)==record['observed_bytes'] and digest(raw)==record['sha256'],'FOUR_ORIGINAL_SHA_DRIFT')
    row=json.loads(raw)
    if record['kind']=='HK_workspace':
        require(row.get('schema_version')=='v4.manager_research.workspace_attempt.v1' and
                row.get('run_id')==record['run_id']==path.stem and
                row.get('target_trade_date')==record['target_date']==path.parent.name and
                row.get('state')=='RUNNING' and row.get('finished_at') is None,'FOUR_HK_IDENTITY_DRIFT')
    else:
        require(row.get('job_id')==row.get('run_id')==record['job_id']==path.stem and
                row.get('state')=='INTERRUPTED' and row.get('failure_code')=='PROCESS_IDENTITY_UNVERIFIED' and
                row.get('retryable') is True and row.get('finished_at') is None,'FOUR_WORKBENCH_IDENTITY_DRIFT')
    return raw


def disposition_private_root(value):
    """A new immutable generation for exactly this product pair and helper set."""
    identity=dict(authority=value['authority'],prepared_products=sorted(value['prepared_products'],key=lambda p:p['path']),
        helper_sha256={name:value['helper_sha256'][name] for name in ('activate_release.py','recover_legacy_activity.py')})
    generation=digest(json.dumps(identity,sort_keys=True,separators=(',',':'),allow_nan=False).encode())
    return AUTHORIZATION_PATH.parent/('private-originals-'+generation)


def capsule(pin):
    require(isinstance(pin,dict) and set(pin)=={'path','sha256'},'FOUR_CAPSULE_PIN_REQUIRED')
    value=read_json(pin['path'],pin['sha256'])
    require(value.get('schema')=='v4.us_hk.legacy_disposition_capsule.v1' and value.get('verdict')=='PASS' and
            value.get('authorized_actions')==['administrative_disposition'],'FOUR_OPERATION_AUTHORITY_REQUIRED')
    auth=authority(value.get('authority'))
    for name in ('recover_legacy_activity.py','activate_release.py'):
        require(value.get('helper_sha256',{}).get(name)==sha(Path(__file__).with_name(name)),'FOUR_HELPER_UNREVIEWED')
    products=value.get('prepared_products',[])
    require(len(products)==2 and len({p['sha256'] for p in products})==2,'FOUR_PRODUCTS_REQUIRED')
    roles=[]
    for product in products:
        require(set(product)=={'path','sha256'},'FOUR_PRODUCT_PIN_SHAPE')
        prepared=read_json(product['path'],product['sha256']);scope=read_json(prepared['scope_path'],prepared['scope_sha256'])
        require(prepared.get('schema')=='v4.us_hk.release_prepared.v1' and prepared.get('state')=='PREPARED' and
                prepared.get('mode')==scope.get('mode')=='RELEASE','FOUR_PRODUCT_SCOPE_MISMATCH')
        roles.append(scope.get('role'))
    require(sorted(roles)==['api','scheduler'],'FOUR_API_SCHEDULER_PRODUCTS_REQUIRED')
    root=exact(value['private_root'],exists=False)
    require(root==disposition_private_root(value) and root.parent.exists() and
            not any(Path(r['path']).is_relative_to(root) or root.is_relative_to(Path(r['path'])) for r in auth['records']),
            'FOUR_PRIVATE_ROOT_INVALID')
    return value,auth,root


def private_file(path,raw):
    """Exclusive durable creation; an exact partial prior run can be resumed."""
    if path.exists():
        exact(path);require(path.is_file() and path.stat().st_mode & 0o777==0o600 and path.stat().st_size==len(raw) and path.read_bytes()==raw,'FOUR_PRIVATE_COLLISION')
        return
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
    fd=os.open(path.parent,os.O_RDONLY)
    try:os.fsync(fd)
    finally:os.close(fd)


def expected_receipt(pin,value,auth,root):
    records=[dict(r,backup_path=str(root/(str(i)+'-'+r['sha256']+'.original.json'))) for i,r in enumerate(auth['records'])]
    return dict(schema='v4.us_hk.legacy_disposition.v1',disposition=DISPOSITION,execution_state='UNKNOWN',
        original_records_changed=False,completion_or_idle_proven=False,authority=value['authority'],
        operator_capsule=pin,prepared_products=value['prepared_products'],records=records,
        original_total_bytes=sum(r['observed_bytes'] for r in records))


def verify_disposition(pin,prepared_sha,scope_sha):
    require(isinstance(pin,dict) and set(pin)=={'path','sha256'},'FOUR_RECEIPT_PIN_REQUIRED')
    receipt=read_json(pin['path'],pin['sha256'])
    value,auth,root=capsule(receipt.get('operator_capsule'))
    require(exact(pin['path'])==root/'DISPOSITION.json' and receipt==expected_receipt(receipt['operator_capsule'],value,auth,root),
            'FOUR_RECEIPT_BINDING_MISMATCH')
    require(root.stat().st_mode & 0o777==0o700 and Path(pin['path']).stat().st_mode & 0o777==0o600,'FOUR_EVIDENCE_NOT_PRIVATE')
    products=[read_json(p['path'],p['sha256']) for p in receipt['prepared_products'] if p['sha256']==prepared_sha]
    require(len(products)==1 and products[0]['scope_sha256']==scope_sha,'FOUR_RECEIPT_OTHER_PRODUCT')
    for record in receipt['records']:
        raw=original(record);backup=exact(record['backup_path'])
        require(backup.is_file() and backup.stat().st_mode & 0o777==0o600 and backup.stat().st_size==len(raw) and backup.read_bytes()==raw,'FOUR_ORIGINAL_BACKUP_DRIFT')
    return receipt


def recover(pin):
    value,auth,root=capsule(pin)
    raws=[original(r) for r in auth['records']]  # Validate all four before any write.
    if not root.exists():root.mkdir(mode=0o700)
    require(root.is_dir() and root.stat().st_mode & 0o777==0o700,'FOUR_EVIDENCE_NOT_PRIVATE')
    receipt=expected_receipt(pin,value,auth,root)
    allowed={'DISPOSITION.json',*(Path(r['backup_path']).name for r in receipt['records'])}
    require({p.name for p in root.iterdir()}<=allowed,'FOUR_PRIVATE_ROOT_UNEXPECTED_FILE')
    for record,raw in zip(receipt['records'],raws):private_file(Path(record['backup_path']),raw)
    # Recheck originals after backups; no stale snapshot becomes a disposition.
    require([original(r) for r in auth['records']]==raws,'FOUR_ORIGINAL_CAS_DRIFT')
    private_file(root/'DISPOSITION.json',json_bytes(receipt))
    for product in receipt['prepared_products']:
        prepared=read_json(product['path'],product['sha256'])
        verify_disposition(dict(path=str(root/'DISPOSITION.json'),sha256=sha(root/'DISPOSITION.json')),
            product['sha256'],prepared['scope_sha256'])
    return receipt


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capsule',required=True);parser.add_argument('--capsule-sha256',required=True)
    args=parser.parse_args();result=recover(dict(path=args.capsule,sha256=args.capsule_sha256))
    print(json.dumps(dict(disposition=result['disposition'],execution_state='UNKNOWN',original_records_changed=False)))


if __name__=='__main__':main()
