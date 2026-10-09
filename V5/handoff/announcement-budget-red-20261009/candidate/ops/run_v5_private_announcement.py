#!/usr/bin/env python3
"""Private V5 binding of the original full announcement owner/CLI contracts.

No HTTP server or V4 API client. Live capture is opt-in; offline is the default.
"""
from __future__ import annotations
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import sys
import threading
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

APP_ROOT=Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0,str(APP_ROOT))
SENTINEL_BASE='http://127.0.0.1:0'
IDENTITY='v5_owner_identity.json'
POLICY='transport_policy.json'


def _raw(value: Any) -> bytes:
    return (json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()


def _absolute(path: str | Path) -> Path:
    return Path(os.path.abspath(Path(path).expanduser()))


def _no_symlink(path: Path) -> None:
    for component in (path,*path.parents):
        if component.is_symlink():
            raise ValueError('V5_OWNER_SYMLINK_FORBIDDEN')


def _verify_app() -> str:
    raw=(APP_ROOT/'V5_OWNER_APP_MANIFEST.json').read_bytes()
    manifest=json.loads(raw)
    if manifest.get('schema')!='v5.announcement_owner_app.v1':
        raise ValueError('V5_OWNER_APP_MANIFEST_INVALID')
    for entry in manifest['files']:
        rel=Path(entry['path'])
        if rel.is_absolute() or '..' in rel.parts:
            raise ValueError('V5_OWNER_APP_PATH_INVALID')
        path=APP_ROOT/rel
        _no_symlink(path)
        if hashlib.sha256(path.read_bytes()).hexdigest()!=entry['sha256']:
            raise ValueError('V5_OWNER_APP_SOURCE_SHA_MISMATCH')
    return hashlib.sha256(raw).hexdigest()


def _reject_offline_recovery(path: Path) -> None:
    for component in (path,*path.parents):
        marker=component/'OFFLINE_RECOVERY.json'
        if marker.exists() or marker.is_symlink():
            raise ValueError('V5_OWNER_OFFLINE_RECOVERY_NETWORK_FORBIDDEN')


class PrivateOwner:
    def __init__(self, root: Path, private_parent: Path, forbidden_roots: list[Path],
                 *, initialize: bool=False, capture_enabled: bool=False,
                 provider_factory: Any=None):
        from infrastructure.owned_io import SafeRoot
        from v4.manager_research.store import ManagerResearchStore
        from v4.manager_research.materials import MaterialStore
        from v4.manager_research.hkex_provider import HkexOfficialProvider
        self.root=_absolute(root)
        _reject_offline_recovery(self.root)
        parent=_absolute(private_parent)
        known_v4 = [Path.home()/'Library/Application Support/com.lexi.v4.local',
                    Path.home()/'Desktop/学习/v4_app']
        if not forbidden_roots:
            raise ValueError('V5_OWNER_V4_ROOT_BINDING_REQUIRED')
        forbidden=sorted({_absolute(p) for p in [*forbidden_roots,*known_v4]})
        if not forbidden or parent==Path(parent.anchor) or self.root==parent or not self.root.is_relative_to(parent):
            raise ValueError('V5_OWNER_PRIVATE_ROOT_REQUIRED')
        _no_symlink(parent);_no_symlink(self.root)
        if not parent.is_dir():
            raise ValueError('V5_OWNER_PRIVATE_PARENT_MISSING')
        if any(self.root==p or self.root.is_relative_to(p) or p.is_relative_to(self.root) for p in forbidden):
            raise ValueError('V5_OWNER_V4_ROOT_FORBIDDEN')
        self.identity={'schema':'v5.announcement_private_owner.v1','private_root':str(self.root),
            'private_parent':str(parent),'forbidden_roots':[str(p) for p in forbidden],
            'app_manifest_sha256':_verify_app(),'source_commit':'0382f753929365048d231a7252d9c328d40f8522'}
        self.io=SafeRoot(self.root)
        if initialize:
            self.root.mkdir(exist_ok=False)
            self.io.write_bytes(IDENTITY,_raw(self.identity),require_absent=True)
            self.io.ensure_directory('materials')
        else:
            if json.loads(self.io.read_bytes(IDENTITY))!=self.identity:
                raise ValueError('V5_OWNER_IDENTITY_MISMATCH')
            if not all((self.root/name).is_dir() for name in ('materials','jobs','products','receipts')):
                raise ValueError('V5_OWNER_LAYOUT_MISSING')
        self.store=ManagerResearchStore(self.root)
        self._material_store=MaterialStore(self.root/'materials')
        self.factory=provider_factory or HkexOfficialProvider
        self.source_provider=self.factory(material_store=self._material_store,timeout=20.0)
        self.capture_enabled=capture_enabled
        self.gate=None
        self._journal_lock=threading.Lock()
        self._capture_meta=None
        self._capture_history=[]

    @contextmanager
    def exclusive(self):
        with self.io.kernel_lock('.locks/v5-owner.mutex',timeout=0):
            yield

    def _read_policy(self):
        try:return json.loads(self.io.read_bytes(POLICY))
        except FileNotFoundError:return None

    def _checkpoint(self):
        with self._journal_lock:
            snapshot=self.gate.accounting_snapshot()
            state=dict(self._capture_meta)
            if snapshot['admission_stop_reason']:
                state['state']='BLOCKED'
            state.update(accounting=snapshot,requests=self.gate.requests,
                updated_at=datetime.now(timezone.utc).isoformat(),
                app_manifest_sha256=self.identity['app_manifest_sha256'])
            state['history']=[*self._capture_history,dict(state)]
            self.io.write_bytes(POLICY,_raw(state))

    def begin_capture(self,target: str,publication: str):
        _reject_offline_recovery(self.root)
        if not self.capture_enabled:
            raise ValueError('V5_OWNER_CAPTURE_NOT_ENABLED')
        from ops.manager_announcement_body_batch import (SharedCaptureGate,MAX_SECONDS,
            MAX_NETWORK_REQUESTS,MAX_RESPONSE_BYTES,REQUEST_INTERVAL_SECONDS)
        from v4.manager_research.announcement_source import MAX_EASTMONEY_RESPONSE_BYTES
        previous=self._read_policy()
        history=[]
        if previous is not None:
            history=previous.get('history',[previous])
            if not isinstance(history,list) or not history or any(not isinstance(item,dict) for item in history):
                raise ValueError('V5_OWNER_CAPTURE_HISTORY_INVALID')
            if (previous.get('state')!='FINISHED' or previous.get('accounting',{}).get('admission_stop_reason')
                    or any(item.get('state')!='FINISHED'
                        or item.get('accounting',{}).get('admission_stop_reason')
                        or item.get('target_trade_date')==target
                        or item.get('publication_date')==publication for item in history)):
                raise ValueError('V5_OWNER_PRIOR_CAPTURE_OR_POLICY_REQUIRES_REVIEW')
        self._capture_history=history
        owner=self
        class OwnerGate(SharedCaptureGate):
            def before_request(self):
                super().before_request()
                try:owner._checkpoint()
                except BaseException:
                    super().end_request()
                    raise
            def record_http_policy(self,policy):
                super().record_http_policy(policy)
                owner._checkpoint()
            def mark_transport_unknown(self):
                super().mark_transport_unknown()
                owner._checkpoint()
            def end_request(self):
                super().end_request()
                owner._checkpoint()
        self.gate=OwnerGate(seconds=MAX_SECONDS,max_requests=MAX_NETWORK_REQUESTS,
            max_bytes=MAX_RESPONSE_BYTES,interval=REQUEST_INTERVAL_SECONDS)
        self.gate.set_response_limits(per_response=MAX_EASTMONEY_RESPONSE_BYTES,total=MAX_RESPONSE_BYTES)
        self._capture_meta={'schema':'v5.announcement_transport_policy.v1','state':'STARTED',
            'capture_id':uuid4().hex,'target_trade_date':target,'publication_date':publication,
            'started_at':datetime.now(timezone.utc).isoformat(),'automatic_retry':False}
        self.source_provider._capture_policy=self.gate
        self._checkpoint()  # Persist before any request; crash cannot open a fresh run.

    def finish_capture(self,success: bool):
        self._capture_meta['state']='FINISHED' if success else 'FAILED'
        self._checkpoint()

    def get_announcement_date_catalog(self,target,publication):
        from v4.manager_research.workspace_announcements import read_date_catalog
        return read_date_catalog(self,target,publication)

    def get_announcement_analysis(self,target,publication):
        from v4.manager_research.announcement_analysis import read
        return read(self,target,publication)

    def import_announcement_analysis(self,product):
        from v4.manager_research.announcement_analysis import import_product
        return import_product(self,product)

    def _import_registered(self,payload):
        from v4.manager_research.workspace_announcements import (validate_registered_handoff,
            validate_agent_judgment_receipt,validate_owner_analysis_import_receipt)
        from v4.manager_research.announcement_analysis import product_path
        from v4.manager_research.workspace_projection import FLAGS,digest
        if not isinstance(payload,bytes) or len(payload)>16*1024*1024:
            raise ValueError('V5_OWNER_IMPORT_ENVELOPE_INVALID')
        envelope=json.loads(payload)
        if (not isinstance(envelope,dict) or set(envelope)!={'schema_version','evidence_run_id','handoff_manifest_sha256','product_sha256'}
                or envelope['schema_version']!='v4.manager_research.announcement_analysis_import_ref.v1'):
            raise ValueError('V5_OWNER_IMPORT_ENVELOPE_INVALID')
        registered=validate_registered_handoff(self.store,envelope['evidence_run_id'],
            envelope['handoff_manifest_sha256'],envelope['product_sha256'])
        product=registered['product']
        agent=validate_agent_judgment_receipt(product.get('agent_judgment_receipt'),product)
        imported=self.import_announcement_analysis(product)
        analysis=imported.get('analysis',{})
        if analysis.get('status')!='VERIFIED' or analysis.get('product_sha256')!=product['sha256']:
            raise ValueError('ANNOUNCEMENT_ANALYSIS_IMPORT_READBACK_FAILED')
        path=product_path(self.store,product['target_trade_date'],product['publication_date']).with_name('owner_import_receipt.v1.json')
        with self.store._transaction(product['target_trade_date'],'announcement-owner-import-receipt'):
            existing=self.store._read(path)
            if existing is not None:
                receipt=validate_owner_analysis_import_receipt(existing,product)
                if any(receipt.get(key)!=agent.get(key) for key in ('parent_task_id','parent_run_id')):
                    raise ValueError('ANNOUNCEMENT_ANALYSIS_OWNER_RECEIPT_CONFLICT')
            else:
                # Preserve the original contract owner label. The separate V5
                # identity proves this is private candidate state, never V4 state.
                receipt={'schema_version':'v4.manager_research.announcement_analysis_owner_import.v1',
                    'status':'VERIFIED','target_trade_date':product['target_trade_date'],
                    'publication_date':product['publication_date'],'product_sha256':product['sha256'],
                    'parent_task_id':agent['parent_task_id'],'parent_run_id':agent['parent_run_id'],
                    'available_at':datetime.now(timezone.utc).isoformat(timespec='microseconds'),
                    'owner':'ManagerResearchJobService.import_announcement_analysis',**FLAGS}
                receipt['sha256']=digest(receipt)
                self.store._write_atomic(path,receipt)
        validate_owner_analysis_import_receipt(receipt,product)
        result=self.get_announcement_analysis(product['target_trade_date'],product['publication_date'])
        if result.get('analysis',{}).get('product_sha256')!=product['sha256']:
            raise ValueError('ANNOUNCEMENT_ANALYSIS_FINAL_READBACK_FAILED')
        result.update(owner_import_receipt=receipt,import_status=imported.get('import_status'),
            handoff_manifest_sha256=envelope['handoff_manifest_sha256'],evidence_run_id=envelope['evidence_run_id'])
        return result

    def request(self,api_base,path,*,method='GET',payload=None):
        from v4.manager_research import workspace_announcements as announcements
        from v4.manager_research.announcement_analysis import product_path
        from ops.run_manager_daily_announcement import _publication_iso
        if api_base!=SENTINEL_BASE:
            raise ValueError('V5_OWNER_EXTERNAL_API_FORBIDDEN')
        parsed=urlsplit(path)
        if parsed.scheme or parsed.netloc or parsed.fragment:
            raise ValueError('V5_OWNER_ROUTE_INVALID')
        query=parse_qs(parsed.query,keep_blank_values=True)
        if any(len(values)!=1 for values in query.values()):
            raise ValueError('V5_OWNER_QUERY_INVALID')
        route=parsed.path
        if route=='/api/v4/manager/research/announcements/analysis/import' and method=='POST' and not query:
            return self._import_registered(payload)
        catalog=route in {'/api/v4/manager/research/announcements','/api/v4/manager/research/announcements/refresh'}
        expected={'date','publication_date','source_scope'} if catalog else {'date','publication_date'}
        if set(query)!=expected:
            raise ValueError('V5_OWNER_QUERY_INVALID')
        target=query['date'][0];publication=_publication_iso(query['publication_date'][0])
        if catalog:
            if query['source_scope'][0]!='EASTMONEY_HK_DATE_CATALOG':
                raise ValueError('V5_OWNER_FULL_DATE_CATALOG_REQUIRED')
            if route.endswith('/refresh') and method=='POST':
                if self.gate is None or not self.capture_enabled:
                    raise ValueError('V5_OWNER_CAPTURE_NOT_ENABLED')
                return announcements.refresh_eastmoney_date_catalog(self,target,publication)
            if not route.endswith('/refresh') and method=='GET':
                return self.get_announcement_date_catalog(target,publication)
        if route=='/api/v4/manager/research/announcements/analysis' and method=='GET':
            result=self.get_announcement_analysis(target,publication)
            receipt=self.store._read(product_path(self.store,target,publication).with_name('owner_import_receipt.v1.json'))
            if receipt is not None:
                announcements.validate_owner_analysis_import_receipt(receipt,{'target_trade_date':target,
                    'publication_date':publication,'sha256':result.get('analysis',{}).get('product_sha256')})
                result['owner_import_receipt']=receipt
            return result
        raise ValueError('V5_OWNER_ROUTE_FORBIDDEN')

    def _private_relative(self,path):
        path=_absolute(path)
        if path==self.root or not path.is_relative_to(self.root):
            raise ValueError('V5_OWNER_ARTIFACT_OUTSIDE_PRIVATE_ROOT')
        return path.relative_to(self.root).as_posix()

    def _check_state_tree(self):
        # Reject pre-existing links anywhere, including derived paths not in argv.
        # Actual output operations below also use descriptor-relative O_NOFOLLOW;
        # this preflight alone is not relied on against a late directory link.
        _no_symlink(self.root)
        def fail(error):raise error
        for directory,dirs,files in os.walk(self.root,followlinks=False,onerror=fail):
            for name in (*dirs,*files):
                if (Path(directory)/name).is_symlink():
                    raise ValueError('V5_OWNER_SYMLINK_FORBIDDEN')

    def _private_mkdir(self,path):
        if _absolute(path)==self.root:return
        self.io.ensure_directory(self._private_relative(path))

    def _private_write_new(self,path,raw):
        self.io.write_bytes(self._private_relative(path),raw,require_absent=True)

    def _private_atomic_json(self,path,value):
        from ops.manager_announcement_body_batch import json_bytes,digest
        raw=json_bytes(value)
        self.io.write_bytes(self._private_relative(path),raw)
        return digest(raw)

    def validate_paths(self,args):
        for name in ('catalog_read','semantic_catalog','body_corpus','body_capture_evidence_root',
                     'review_receipt','reviewer_output','decisions','out'):
            value=getattr(args,name,None)
            if value is None:continue
            path=_absolute(value);_no_symlink(path)
            if not path.is_relative_to(self.root):
                raise ValueError('V5_OWNER_ARTIFACT_OUTSIDE_PRIVATE_ROOT')

    def execute(self,argv):
        from ops import run_manager_daily_announcement as daily
        from ops import manager_announcement_body_batch as body
        if not argv:raise ValueError('V5_OWNER_COMMAND_REQUIRED')
        if any(token.split('=',1)[0] in {'--api-base','--research-state-root'} for token in argv):
            raise ValueError('V5_OWNER_BOUND_ARGUMENT_OVERRIDE_FORBIDDEN')
        command=argv[0];tokens=list(argv)
        if command in {'capture','import','readback'}:tokens+=['--api-base',SENTINEL_BASE]
        if command in {'capture','import','register-handoff'}:tokens+=['--research-state-root',str(self.root)]
        args=daily._parser().parse_args(tokens)
        self.validate_paths(args)
        if command=='capture' and args.resume_evidence_run_id:
            raise ValueError('V5_OWNER_CAPTURE_RESUME_REQUIRES_REVIEW')
        old_request=daily._request;old_capture=body.run_capture
        old_mkdir=daily._mkdir;old_write_new=daily._write_new
        old_body_mkdir=body._mkdir_output;old_atomic_json=body.atomic_json
        def private_body(*args,**kwargs):
            kwargs['capture_gate']=self.gate
            kwargs['api_overrides']={**kwargs.get('api_overrides',{}),'HkexOfficialProvider':self.factory}
            return old_capture(*args,**kwargs)
        with self.exclusive():
            self._check_state_tree()
            daily._request=self.request
            daily._mkdir=self._private_mkdir
            daily._write_new=self._private_write_new
            body._mkdir_output=self._private_mkdir
            body.atomic_json=self._private_atomic_json
            body.run_capture=private_body
            started=False
            succeeded=False
            try:
                if command=='capture':
                    self.begin_capture(daily.date_token(args.target_date),daily._publication_iso(args.publication_date))
                    started=True
                    result=daily._capture(args)
                    succeeded=True
                elif command=='prepare':result=daily._build(args,reviewed=False)
                elif command=='build-reviewed':result=daily._build(args,reviewed=True)
                elif command=='register-handoff':result=daily._register_handoff(args)
                elif command=='import':result=daily._import(args)
                else:result=daily._readback(args)
                return {**result,'v5_private_owner':self.identity}
            finally:
                daily._request=old_request
                daily._mkdir=old_mkdir;daily._write_new=old_write_new
                body._mkdir_output=old_body_mkdir;body.atomic_json=old_atomic_json
                body.run_capture=old_capture
                if started:self.finish_capture(succeeded)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--private-parent',type=Path,required=True)
    parser.add_argument('--forbid-root',type=Path,action='append',required=True)
    parser.add_argument('--initialize',action='store_true')
    parser.add_argument('--allow-network-capture',action='store_true')
    options,argv=parser.parse_known_args()
    if options.initialize and argv:
        raise ValueError('V5_OWNER_INITIALIZE_IS_SEPARATE')
    if options.allow_network_capture and (not argv or argv[0]!='capture' or options.initialize):
        raise ValueError('V5_OWNER_NETWORK_FLAG_ONLY_FOR_CAPTURE')
    def audit(event,args):
        if event in {'socket.connect','socket.connect_ex'}:
            address=args[1]
            loopback = True
            if isinstance(address, tuple):
                try: loopback = ipaddress.ip_address(address[0]).is_loopback
                except ValueError: loopback = str(address[0]).lower() == 'localhost'
            if not options.allow_network_capture or loopback or (isinstance(address,tuple) and address[1] in {8873,8910}):
                raise RuntimeError('V5_OWNER_NETWORK_FORBIDDEN')
        if event in {'socket.getaddrinfo','socket.sendto'} and not options.allow_network_capture:
            raise RuntimeError('V5_OWNER_NETWORK_FORBIDDEN')
        if event in {'socket.bind','subprocess.Popen','os.system'}:
            raise RuntimeError('V5_OWNER_SUBPROCESS_FORBIDDEN')
    sys.addaudithook(audit)
    owner=PrivateOwner(options.root,options.private_parent,options.forbid_root,
        initialize=options.initialize,capture_enabled=options.allow_network_capture)
    if options.initialize:
        if argv:raise ValueError('V5_OWNER_INITIALIZE_IS_SEPARATE')
        result={'status':'PRIVATE_OWNER_INITIALIZED','identity':owner.identity}
    else:result=owner.execute(argv)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True))
    return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except (ValueError,RuntimeError,OSError) as exc:
        print(json.dumps({'status':'FAILED','reason':str(exc) if str(exc).replace('_','').isalnum() else type(exc).__name__}))
        raise SystemExit(2)
