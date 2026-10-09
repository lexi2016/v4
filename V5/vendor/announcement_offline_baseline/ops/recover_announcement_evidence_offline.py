#!/usr/bin/env python3
"""Byte-preserving, offline-only projection of an existing BLOCKED capture."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys

APP_ROOT=Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:sys.path.insert(0,str(APP_ROOT))
from infrastructure.owned_io import SafeRoot
from ops.run_v5_private_announcement import _absolute,_no_symlink,_raw


# Deterministically reconstructed from the verified 874 handoff manifests.
TRUSTED_SOURCE_APP_SHA256='7b9e27770331c67734bac30c17cc36a76dba32d34be3cbeed64378eff85384f7'
SOURCE_COMMIT='0382f753929365048d231a7252d9c328d40f8522'


def sha(raw):return hashlib.sha256(raw).hexdigest()


def _validate_source_identity(src,source,output,policy,source_app,identity_sha256):
    identity_raw=src.read_bytes('v5_owner_identity.json')
    if sha(identity_raw)!=identity_sha256:raise ValueError('RECOVERY_SOURCE_IDENTITY_SHA_MISMATCH')
    identity=json.loads(identity_raw)
    if not isinstance(identity,dict) or identity.get('schema')!='v5.announcement_private_owner.v1':
        raise ValueError('RECOVERY_SOURCE_IDENTITY_INVALID')
    if identity.get('private_root')!=str(source):raise ValueError('RECOVERY_SOURCE_IDENTITY_ROOT_MISMATCH')
    parent_value=identity.get('private_parent')
    if not isinstance(parent_value,str):raise ValueError('RECOVERY_SOURCE_IDENTITY_PARENT_INVALID')
    parent=_absolute(parent_value);_no_symlink(parent)
    if (str(parent)!=parent_value or parent==Path(parent.anchor) or parent==source
            or not source.is_relative_to(parent) or not parent.is_dir()):
        raise ValueError('RECOVERY_SOURCE_IDENTITY_PARENT_INVALID')
    values=identity.get('forbidden_roots')
    if not isinstance(values,list) or not values or any(not isinstance(v,str) for v in values):
        raise ValueError('RECOVERY_SOURCE_FORBIDDEN_ROOTS_INVALID')
    forbidden=[]
    for value in values:
        path=_absolute(value);_no_symlink(path)
        if str(path)!=value:raise ValueError('RECOVERY_SOURCE_FORBIDDEN_ROOTS_INVALID')
        forbidden.append(path)
    forbidden.extend([_absolute(Path.home()/'Library/Application Support/com.lexi.v4.local'),
                      _absolute(Path.home()/'Desktop/学习/v4_app')])
    for path in forbidden:
        if source==path or source.is_relative_to(path) or path.is_relative_to(source):
            raise ValueError('RECOVERY_SOURCE_FORBIDDEN_ROOT')
        if output==path or output.is_relative_to(path) or path.is_relative_to(output):
            raise ValueError('RECOVERY_OUTPUT_FORBIDDEN_ROOT')
    if (identity.get('source_commit')!=SOURCE_COMMIT
            or identity.get('app_manifest_sha256')!=TRUSTED_SOURCE_APP_SHA256
            or policy.get('schema')!='v5.announcement_transport_policy.v1'
            or policy.get('app_manifest_sha256')!=TRUSTED_SOURCE_APP_SHA256):
        raise ValueError('RECOVERY_SOURCE_APP_MANIFEST_BINDING_INVALID')
    history=policy.get('history')
    if (not isinstance(history,list) or not history
            or any(not isinstance(item,dict) or item.get('app_manifest_sha256')!=TRUSTED_SOURCE_APP_SHA256 for item in history)
            or history[-1]!={k:v for k,v in policy.items() if k!='history'}):
        raise ValueError('RECOVERY_POLICY_HISTORY_BINDING_INVALID')
    app=_absolute(source_app);_no_symlink(app)
    if output==app or output.is_relative_to(app) or app.is_relative_to(output):
        raise ValueError('RECOVERY_OUTPUT_OVERLAPS_SOURCE_APP')
    appio=SafeRoot(app);raw=appio.read_bytes('V5_OWNER_APP_MANIFEST.json')
    if sha(raw)!=TRUSTED_SOURCE_APP_SHA256:raise ValueError('RECOVERY_SOURCE_APP_MANIFEST_SHA_MISMATCH')
    manifest=json.loads(raw)
    if manifest.get('schema')!='v5.announcement_owner_app.v1':raise ValueError('RECOVERY_SOURCE_APP_MANIFEST_INVALID')
    for entry in manifest['files']:
        if sha(appio.read_bytes(entry['path']))!=entry['sha256']:
            raise ValueError('RECOVERY_SOURCE_APP_FILE_SHA_MISMATCH')
    return identity_raw,app



def _same_json_structure(left,right):
    # bool is a subclass of int in Python; JSON value identity must be stricter.
    if type(left) is not type(right):return False
    if isinstance(left,dict):
        return left.keys()==right.keys() and all(_same_json_structure(left[key],right[key]) for key in left)
    if isinstance(left,list):
        return len(left)==len(right) and all(_same_json_structure(a,b) for a,b in zip(left,right))
    return left==right


def _inventory(io,relative):
    result={}
    def walk(path):
        with io.directory(path) as fd:
            for name in sorted(os.listdir(fd)):
                child=path+'/'+name
                mode=os.stat(name,dir_fd=fd,follow_symlinks=False).st_mode
                if stat.S_ISDIR(mode):walk(child)
                elif stat.S_ISREG(mode):result[child]=sha(io.read_bytes(child))
                else:raise ValueError('RECOVERY_SOURCE_LINK_OR_SPECIAL_FILE')
    walk(relative)
    return result


def recover(source_root,output_root,run_id,policy_sha256,batch_sha256,*,source_app,identity_sha256):
    # No provider, budget reset, source writes, owner initialization or API call.
    from v4.manager_research.workspace_announcements import validate_terminal_body_capture
    from ops.run_manager_daily_announcement import _evidence_run_id
    source=_absolute(source_root);output=_absolute(output_root)
    _no_symlink(source);_no_symlink(output)
    if (source==output or output.is_relative_to(source) or source.is_relative_to(output)
            or output.exists()):
        raise ValueError('RECOVERY_OUTPUT_MUST_BE_NEW_DISJOINT_DIRECTORY')
    if not re.fullmatch('[0-9a-f]{32}',run_id):raise ValueError('RECOVERY_RUN_ID_INVALID')
    if any(not re.fullmatch('[0-9a-f]{64}',x) for x in (policy_sha256,batch_sha256,identity_sha256)):
        raise ValueError('RECOVERY_EXPECTED_SHA_REQUIRED')
    src=SafeRoot(source);prefix='announcement_agent_runs/'+run_id+'/evidence'
    policy_raw=src.read_bytes('transport_policy.json');policy=json.loads(policy_raw)
    if sha(policy_raw)!=policy_sha256:raise ValueError('RECOVERY_POLICY_SHA_MISMATCH')
    identity_raw,source_app=_validate_source_identity(src,source,output,policy,source_app,identity_sha256)
    if policy.get('state')!='BLOCKED' or not policy.get('accounting',{}).get('admission_stop_reason'):
        raise ValueError('RECOVERY_REQUIRES_PRESERVED_BLOCKED_POLICY')
    batch_raw=src.read_bytes(prefix+'/body_batch/batch_receipt.json');batch=json.loads(batch_raw)
    if sha(batch_raw)!=batch_sha256:raise ValueError('RECOVERY_BATCH_SHA_MISMATCH')
    catalog_raw=src.read_bytes(prefix+'/catalog_read.json');catalog=json.loads(catalog_raw)
    capture_raw=src.read_bytes(prefix+'/capture_receipt.json');capture=json.loads(capture_raw)
    target=batch['target_trade_date'];publication=batch['publication_date']
    if (policy.get('target_trade_date')!=target or policy.get('publication_date')!=publication
            or capture.get('evidence_run_id')!=run_id
            or capture.get('target_trade_date')!=target or capture.get('publication_date')!=publication
            or capture.get('status')!=batch.get('status')
            or capture.get('catalog_run_id')!=catalog.get('catalog',{}).get('run_id')
            or capture.get('catalog_product_sha256')!=catalog.get('catalog',{}).get('sha256')
            or capture.get('catalog_read_file_sha256')!=sha(catalog_raw)
            or _evidence_run_id(target,publication,catalog['catalog'])!=run_id):
        raise ValueError('RECOVERY_SOURCE_RUN_BINDING_INVALID')
    replacements={}
    for name,key in (('body_corpus.json','body_corpus_sha256'),
                     ('body_corpus_manifest.json','body_corpus_manifest_sha256')):
        raw=src.read_bytes(prefix+'/body_batch/'+name)
        if sha(raw)!=batch.get(key):raise ValueError('RECOVERY_AUTHORITATIVE_BODY_SHA_MISMATCH')
        replacements[name]=raw
    replacements['body_batch_receipt.json']=batch_raw
    old_keys={'body_corpus.json':'body_corpus_file_sha256',
        'body_corpus_manifest.json':'body_corpus_manifest_file_sha256',
        'body_batch_receipt.json':'body_batch_receipt_sha256'}
    # Permit only the observed serialization defect, never changed JSON values.
    for name,raw in replacements.items():
        old=src.read_bytes(prefix+'/'+name)
        if not _same_json_structure(json.loads(old),json.loads(raw)) or sha(old)!=capture.get(old_keys[name]):
            raise ValueError('RECOVERY_NOT_SERIALIZATION_ONLY')
    original_files=_inventory(src,prefix)
    original_files['transport_policy.json']=policy_sha256
    original_files['v5_owner_identity.json']=sha(identity_raw)
    marker={'schema':'v5.announcement_offline_recovery.v1','network_allowed':False,
        'source_root':str(source),'derived_root':str(output),'source_run_id':run_id,
        'source_identity_sha256':sha(identity_raw),'source_app_root':str(source_app),
        'source_app_manifest_sha256':TRUSTED_SOURCE_APP_SHA256,'source_policy_sha256':policy_sha256,
        'source_batch_receipt_sha256':batch_sha256,'source_state':'BLOCKED',
        'semantic_catalog':'READER_OUTPUT_REQUIRED','status':'UNVERIFIED'}
    with SafeRoot(output.parent).directory() as fd:os.mkdir(output.name,mode=0o700,dir_fd=fd)
    dst=SafeRoot(output)
    dst.write_bytes('OFFLINE_RECOVERY.json',_raw(marker),require_absent=True)
    for relative,expected in original_files.items():
        raw=src.read_bytes(relative)
        if sha(raw)!=expected:raise ValueError('RECOVERY_SOURCE_CHANGED')
        dst.write_bytes('original/'+relative,raw,require_absent=True)
        if relative.startswith(prefix+'/'):
            name=relative[len(prefix)+1:]
            if name not in (*replacements,'capture_receipt.json'):
                dst.write_bytes(relative,raw,require_absent=True)
    # Keep the exact BLOCKED budget/history at the recovery root as well.
    dst.write_bytes('transport_policy.json',policy_raw,require_absent=True)
    for name,raw in replacements.items():dst.write_bytes(prefix+'/'+name,raw,require_absent=True)
    derived=dict(capture)
    for name,key in old_keys.items():derived[key]=sha(replacements[name])
    derived['offline_recovery']={'original_capture_receipt_sha256':sha(capture_raw),
        'authoritative_batch_receipt_sha256':batch_sha256,'source_policy_sha256':policy_sha256,
        'network_requests':0,'original_status':capture['status'],'original_run_id':run_id,
        'note':'NEW_DERIVED_RECEIPT_ORIGINAL_PRESERVED_NOT_RESEALED'}
    dst.write_bytes(prefix+'/capture_receipt.json',_raw(derived),require_absent=True)
    terminal=validate_terminal_body_capture(output/prefix,catalog,target,publication,expected_run_id=run_id)
    # Re-read immutable originals and copied bytes before publishing verification.
    if _inventory(src,prefix)!={k:v for k,v in original_files.items() if k.startswith(prefix+'/')}:
        raise ValueError('RECOVERY_SOURCE_CHANGED')
    for relative,expected in original_files.items():
        if sha(src.read_bytes(relative))!=expected or sha(dst.read_bytes('original/'+relative))!=expected:
            raise ValueError('RECOVERY_SOURCE_OR_COPY_CHANGED')
    receipt={**marker,'status':'OFFLINE_TERMINAL_EVIDENCE_VERIFIED','terminal':terminal,
        'original_files':original_files,'recovered_files':_inventory(dst,prefix),
        'original_capture_receipt_sha256':sha(capture_raw),
        'derived_capture_receipt_sha256':sha(dst.read_bytes(prefix+'/capture_receipt.json')),
        'network_requests':0,'readers_run':False,'reviewer_run':False,'import_run':False}
    dst.write_bytes('recovery_receipt.json',_raw(receipt),require_absent=True)
    return receipt


def prepare_recovered(root,semantic_catalog):
    from ops import run_manager_daily_announcement as daily
    root=_absolute(root);semantic=_absolute(semantic_catalog)
    _no_symlink(root);_no_symlink(semantic)
    if not semantic.is_relative_to(root):raise ValueError('RECOVERY_READER_OUTPUT_OUTSIDE_ROOT')
    io=SafeRoot(root)
    marker=json.loads(io.read_bytes('OFFLINE_RECOVERY.json'))
    receipt=json.loads(io.read_bytes('recovery_receipt.json'))
    if (marker.get('derived_root')!=str(root) or marker.get('network_allowed') is not False
            or receipt.get('status')!='OFFLINE_TERMINAL_EVIDENCE_VERIFIED'
            or sha(io.read_bytes('transport_policy.json'))!=receipt.get('source_policy_sha256')):
        raise ValueError('RECOVERY_VERIFICATION_REQUIRED')
    for relative,expected in receipt['recovered_files'].items():
        if sha(io.read_bytes(relative))!=expected:raise ValueError('RECOVERY_EVIDENCE_CHANGED')
    prefix='announcement_agent_runs/'+receipt['source_run_id']+'/evidence'
    capture=json.loads(io.read_bytes(prefix+'/capture_receipt.json'))
    # A real reader must supply this; do not manufacture classifications.
    io.read_bytes(semantic.relative_to(root).as_posix())
    args=daily._parser().parse_args(['prepare','--target-date',capture['target_trade_date'],
        '--publication-date',capture['publication_date'],'--catalog-read',str(root/prefix/'catalog_read.json'),
        '--body-corpus',str(root/prefix/'body_corpus.json'),'--body-capture-evidence-root',str(root/prefix),
        '--semantic-catalog',str(semantic)])
    return daily._build(args,reviewed=False)


def main():
    def deny(event,args):
        if event in {'socket.connect','socket.connect_ex','socket.getaddrinfo','socket.bind','socket.sendto','subprocess.Popen','os.system'}:
            raise RuntimeError('OFFLINE_RECOVERY_NETWORK_OR_PROCESS_FORBIDDEN')
    sys.addaudithook(deny)
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',type=Path)
    parser.add_argument('--source-app',type=Path)
    parser.add_argument('--identity-sha256')
    parser.add_argument('--output-root',type=Path)
    parser.add_argument('--run-id')
    parser.add_argument('--policy-sha256')
    parser.add_argument('--batch-sha256')
    parser.add_argument('--prepare-root',type=Path)
    parser.add_argument('--semantic-catalog',type=Path)
    args=parser.parse_args()
    capture_args=(args.source_root,args.output_root,args.run_id,args.policy_sha256,args.batch_sha256)
    if args.prepare_root is not None:
        if any(x is not None for x in capture_args) or args.source_app is not None or args.identity_sha256 is not None or args.semantic_catalog is None:
            parser.error('prepare requires only --prepare-root and --semantic-catalog')
        result=prepare_recovered(args.prepare_root,args.semantic_catalog)
    else:
        if any(x is None for x in capture_args) or args.source_app is None or args.identity_sha256 is None or args.semantic_catalog is not None:
            parser.error('recovery requires source-root/source-app/output/run and policy/batch/identity SHA values')
        result=recover(*capture_args,source_app=args.source_app,identity_sha256=args.identity_sha256)
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()
