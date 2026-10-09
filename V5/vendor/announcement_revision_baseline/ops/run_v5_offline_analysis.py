#!/usr/bin/env python3
"""Adopt verified recovery evidence for offline V5 analysis only; never capture."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlencode

APP_ROOT=Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:sys.path.insert(0,str(APP_ROOT))
from infrastructure.owned_io import SafeRoot
from ops.run_v5_private_announcement import PrivateOwner,_absolute,_no_symlink,_raw,_verify_app,SENTINEL_BASE


def sha(raw):return hashlib.sha256(raw).hexdigest()


def verify_recovery(root,expected_sha):
    root=_absolute(root);_no_symlink(root);io=SafeRoot(root)
    if not isinstance(expected_sha,str) or not re.fullmatch('[0-9a-f]{64}',expected_sha):
        raise ValueError('OFFLINE_ANALYSIS_RECOVERY_SHA_REQUIRED')
    raw=io.read_bytes('recovery_receipt.json')
    if sha(raw)!=expected_sha:raise ValueError('OFFLINE_ANALYSIS_RECOVERY_SHA_MISMATCH')
    receipt=json.loads(raw);marker=json.loads(io.read_bytes('OFFLINE_RECOVERY.json'))
    if (receipt.get('status')!='OFFLINE_TERMINAL_EVIDENCE_VERIFIED'
            or marker.get('network_allowed') is not False or receipt.get('network_allowed') is not False
            or marker.get('derived_root')!=str(root) or receipt.get('derived_root')!=str(root)
            or marker.get('source_root')!=receipt.get('source_root')
            or marker.get('source_run_id')!=receipt.get('source_run_id')):
        raise ValueError('OFFLINE_ANALYSIS_RECOVERY_BINDING_INVALID')
    policy=io.read_bytes('transport_policy.json')
    if (sha(policy)!=receipt.get('source_policy_sha256')
            or sha(policy)!=marker.get('source_policy_sha256') or json.loads(policy).get('state')!='BLOCKED'):
        raise ValueError('OFFLINE_ANALYSIS_BLOCKED_POLICY_CHANGED')
    identity_raw=io.read_bytes('original/v5_owner_identity.json');source_identity=json.loads(identity_raw)
    if (sha(identity_raw)!=receipt.get('source_identity_sha256')
            or sha(identity_raw)!=marker.get('source_identity_sha256')
            or source_identity.get('private_root')!=receipt.get('source_root')):
        raise ValueError('OFFLINE_ANALYSIS_SOURCE_IDENTITY_CHANGED')
    forbidden=source_identity.get('forbidden_roots')
    if not isinstance(forbidden,list) or not forbidden:raise ValueError('OFFLINE_ANALYSIS_FORBIDDEN_ROOTS_MISSING')
    for value in forbidden:
        banned=_absolute(value)
        if root==banned or root.is_relative_to(banned) or banned.is_relative_to(root):
            raise ValueError('OFFLINE_ANALYSIS_FORBIDDEN_ROOT')
    for name,expected in receipt['original_files'].items():
        if sha(io.read_bytes('original/'+name))!=expected:raise ValueError('OFFLINE_ANALYSIS_ORIGINAL_COPY_CHANGED')
    for name,expected in receipt['recovered_files'].items():
        if sha(io.read_bytes(name))!=expected:raise ValueError('OFFLINE_ANALYSIS_EVIDENCE_CHANGED')
    run=receipt['source_run_id']
    if not re.fullmatch('[0-9a-f]{32}',run):raise ValueError('OFFLINE_ANALYSIS_RUN_INVALID')
    prefix='announcement_agent_runs/'+run+'/evidence'
    capture=json.loads(io.read_bytes(prefix+'/capture_receipt.json'))
    catalog=json.loads(io.read_bytes(prefix+'/catalog_read.json'))
    from v4.manager_research.workspace_announcements import validate_terminal_body_capture
    terminal=validate_terminal_body_capture(root/prefix,catalog,capture['target_trade_date'],capture['publication_date'],expected_run_id=run)
    return root,io,receipt,capture,catalog,terminal


class OfflineAnalysisOwner(PrivateOwner):
    IDENTITY='offline_analysis_owner_identity.json'
    def __init__(self,root,recovery_sha256,*,adopt=False):
        from v4.manager_research.store import ManagerResearchStore
        self.root,self.io,self.recovery,self.capture,self.catalog,self.terminal=verify_recovery(root,recovery_sha256)
        self.recovery_sha256=recovery_sha256
        self.identity={'schema':'v5.announcement_offline_analysis_owner.v1','private_root':str(self.root),
            'source_root':self.recovery['source_root'],'source_run_id':self.recovery['source_run_id'],
            'recovery_receipt_sha256':recovery_sha256,'blocked_policy_sha256':self.recovery['source_policy_sha256'],
            'app_manifest_sha256':_verify_app(),'network_allowed':False,'capture_allowed':False}
        self._check_state_tree()
        if adopt:self._write_once(self.IDENTITY,_raw(self.identity))
        elif json.loads(self.io.read_bytes(self.IDENTITY))!=self.identity:
            raise ValueError('OFFLINE_ANALYSIS_OWNER_IDENTITY_MISMATCH')
        self.store=ManagerResearchStore(self.root)
        self.capture_enabled=False;self.gate=None;self.factory=None;self._material_store=None

    def _write_once(self,name,raw):
        try:self.io.write_bytes(name,raw,require_absent=True)
        except FileExistsError:
            if self.io.read_bytes(name)!=raw:raise ValueError('OFFLINE_ANALYSIS_ARTIFACT_CONFLICT')

    def begin_capture(self,*args,**kwargs):raise ValueError('OFFLINE_ANALYSIS_CAPTURE_FORBIDDEN')

    def _verify_evidence(self):
        return verify_recovery(self.root,self.recovery_sha256)

    def _binding_provenance(self):
        return {}

    def get_announcement_date_catalog(self,target,publication):
        if target!=self.capture['target_trade_date'] or publication!=self.capture['publication_date']:
            raise ValueError('OFFLINE_ANALYSIS_DATE_MISMATCH')
        self._verify_evidence()
        return json.loads(self.io.read_bytes('announcement_agent_runs/'+self.recovery['source_run_id']+'/evidence/catalog_read.json'))

    def _verify_registered(self):
        from v4.manager_research.workspace_announcements import validate_registered_handoff
        from v4.manager_research.announcement_analysis import validate_product
        prefix='announcement_agent_runs/'+self.recovery['source_run_id']+'/evidence/'
        manifest=json.loads(self.io.read_bytes(prefix+'handoff_manifest.v1.json'))
        bound=validate_registered_handoff(self.store,self.recovery['source_run_id'],manifest['sha256'],manifest['product_sha256'])
        validate_product(bound['product'],target_trade_date=self.capture['target_trade_date'],
            publication_date=self.capture['publication_date'],catalog=self.catalog['catalog'])
        return {'status':'REGISTERED_HANDOFF_VERIFIED','product_sha256':manifest['product_sha256'],
                'handoff_manifest_sha256':manifest['sha256'],'evidence_run_id':self.recovery['source_run_id']}

    def _publish_binding(self):
        from v4.manager_research.announcement_analysis import product_path
        query=urlencode({'date':self.capture['target_trade_date'],'publication_date':self.capture['publication_date']})
        readback=self.request(SENTINEL_BASE,'/api/v4/manager/research/announcements/analysis?'+query)
        if readback.get('analysis',{}).get('status')!='VERIFIED':raise ValueError('OFFLINE_ANALYSIS_IMPORT_NOT_VERIFIED')
        product=product_path(self.store,self.capture['target_trade_date'],self.capture['publication_date'])
        owner_receipt=product.with_name('owner_import_receipt.v1.json')
        self._write_once('offline_import_readback.json',_raw(readback))
        binding={'schema':'v5.announcement_offline_analysis_binding.v1','status':'PRIVATE_OWNER_READBACK_VERIFIED',
            'owner_root':str(self.root),'target_trade_date':self.capture['target_trade_date'],
            'publication_date':self.capture['publication_date'],'evidence_run_id':self.recovery['source_run_id'],
            'product_path':str(product.relative_to(self.root)),
            'product_file_sha256':sha(self.io.read_bytes(str(product.relative_to(self.root)))),
            'product_sha256':readback['analysis']['product_sha256'],
            'owner_import_receipt_path':str(owner_receipt.relative_to(self.root)),
            'owner_import_receipt_file_sha256':sha(self.io.read_bytes(str(owner_receipt.relative_to(self.root)))),
            'readback_path':'offline_import_readback.json','readback_file_sha256':sha(self.io.read_bytes('offline_import_readback.json')),
            'recovery_receipt_sha256':self.recovery_sha256,'blocked_policy_sha256':self.recovery['source_policy_sha256'],
            'network_allowed':False,'capture_allowed':False,'manager_ui_integrated':False,
            **self._binding_provenance()}
        self._write_once('manager_binding.v1.json',_raw(binding))
        return binding

    def execute(self,argv):
        if not argv or argv[0] not in {'prepare','build-reviewed','register-handoff','verify','import','readback'}:
            raise ValueError('OFFLINE_ANALYSIS_COMMAND_FORBIDDEN')
        self._verify_evidence()
        command=argv[0]
        if command=='verify':
            if len(argv)!=1:raise ValueError('OFFLINE_ANALYSIS_BOUND_ARGUMENT_OVERRIDE')
            with self.exclusive():return self._verify_registered()
        forbidden={'--target-date','--publication-date','--evidence-run-id','--catalog-read','--body-corpus','--body-capture-evidence-root'}
        if any(token.split('=',1)[0] in forbidden for token in argv):raise ValueError('OFFLINE_ANALYSIS_BOUND_ARGUMENT_OVERRIDE')
        tokens=list(argv);prefix=self.root/'announcement_agent_runs'/self.recovery['source_run_id']/'evidence'
        if command in {'prepare','build-reviewed','register-handoff','readback'}:
            tokens+=['--target-date',self.capture['target_trade_date'],'--publication-date',self.capture['publication_date']]
        if command in {'import','register-handoff'}:tokens+=['--evidence-run-id',self.recovery['source_run_id']]
        if command in {'prepare','build-reviewed'}:
            tokens+=['--catalog-read',str(prefix/'catalog_read.json'),'--body-corpus',str(prefix/'body_corpus.json'),
                     '--body-capture-evidence-root',str(prefix)]
        result=super().execute(tokens)
        self._verify_evidence()
        if command=='import':
            with self.exclusive():result['manager_binding']=self._publish_binding()
        return result


def main():
    def deny(event,args):
        if event in {'socket.connect','socket.connect_ex','socket.getaddrinfo','socket.bind','socket.sendto','subprocess.Popen','os.system'}:
            raise RuntimeError('OFFLINE_ANALYSIS_NETWORK_OR_PROCESS_FORBIDDEN')
    sys.addaudithook(deny)
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recovery-root',type=Path,required=True)
    parser.add_argument('--recovery-receipt-sha256',required=True)
    options,argv=parser.parse_known_args()
    if argv and argv[0]=='--':argv=argv[1:]
    if argv==['adopt']:
        owner=OfflineAnalysisOwner(options.recovery_root,options.recovery_receipt_sha256,adopt=True)
        result={'status':'OFFLINE_ANALYSIS_OWNER_ADOPTED','identity':owner.identity}
    else:
        owner=OfflineAnalysisOwner(options.recovery_root,options.recovery_receipt_sha256)
        result=owner.execute(argv)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True))

if __name__=='__main__':main()
