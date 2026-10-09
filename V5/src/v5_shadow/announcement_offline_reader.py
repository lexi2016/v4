"""Pinned OfflineAnalysisOwner transport; never capture/import/adopt."""
import sys
from pathlib import Path
if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ast
import copy
import hashlib
import json
import os
import subprocess
from v5_shadow.contracts import aware
from v5_shadow.digests import canonical_bytes,sha256_json,MAX_JSON_BYTES
APP=Path(__file__).resolve().parents[2]/'vendor/announcement_offline_baseline'
PIN='0ff96e3c5bc48c67fada2b979a9862b7778c9a33c1983cdc0ab180ea85125ab5'
REVISION_APP=APP.with_name('announcement_revision_baseline')
REVISION_PIN='da392a57bf93dd9a5b4355d934e267a7c5c4fe495e90779364627e8a8f118d8a'


def sources(app=None,pin=None):
    app=APP if app is None else app;pin=PIN if pin is None else pin
    raw=(app/'V5_OWNER_APP_MANIFEST.json').read_bytes()
    if hashlib.sha256(raw).hexdigest()!=pin:raise ValueError('OFFLINE_MANAGER_APP_PIN')
    for entry in json.loads(raw)['files']:
        path=app/entry['path']
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest()!=entry['sha256']:raise ValueError('OFFLINE_MANAGER_APP_BYTES')


CONSUMER_FUNCTIONS=('validate_registered_handoff','validate_owner_analysis_import_receipt',
                    '_analysis_time_refs','read_analysis_consumption')


def install_consumer_contract(module):
    """Augment offline owner with exact pinned manager checks, not old terminal code.

    Keep the new retained-page validator and analysis owner. Replace only the
    registered handoff/owner receipt checks with the strengthened manager source,
    and add its missing consumption function. No source file is modified.
    """
    from v5_shadow.manager_plan import _sources, PIN as consumer_pin
    raw=_sources()['v4/manager_research/workspace_announcements.py']
    tree=ast.parse(raw)
    definitions={node.name:node for node in tree.body if isinstance(node,ast.FunctionDef)}
    selected=[definitions[name] for name in CONSUMER_FUNCTIONS]
    compiled=ast.fix_missing_locations(ast.Module(body=selected,type_ignores=[]))
    exec(compile(compiled,'<pinned-manager-announcement-consumption>','exec'),module.__dict__)
    return consumer_pin


def read_owner(binding,cutoff,*,default_analysis=False):
    revision='revision_manifest_sha256' in binding
    app,pin=(REVISION_APP,REVISION_PIN) if revision else (APP,PIN)
    sources(app,pin);request=dict(binding=binding,cutoff=cutoff)
    if default_analysis:request['default_analysis']=True
    child=subprocess.run([sys.executable,'-I','-B',str(Path(__file__).resolve())],input=canonical_bytes(request),
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=120,
        env={k:v for k,v in os.environ.items() if not k.startswith(('V4_','V35_'))})
    if len(child.stdout)>MAX_JSON_BYTES:raise ValueError('OFFLINE_MANAGER_RESPONSE_LIMIT')
    try:result=json.loads(child.stdout)
    except ValueError as error:raise ValueError('OFFLINE_MANAGER_CHILD_RESPONSE') from error
    if child.returncode:raise ValueError(result.get('reason','OFFLINE_MANAGER_READ_FAILED'))
    from v5_shadow.manager_plan import PIN as consumer_pin
    if (result.get('app_manifest_sha256')!=pin or result.get('consumer_source_capsule_sha256')!=consumer_pin
            or result.get('request_sha256')!=sha256_json(request)):raise ValueError('OFFLINE_MANAGER_CHILD_IDENTITY')
    sources(app,pin);return result


def install_transport(service,announcements,binding,result,error):
    old_catalog=service.get_announcement_date_catalog;old_analysis=service.get_announcement_analysis
    old_consumption=announcements.read_analysis_consumption
    def selected(target,publication):return target==binding['target_date'] and publication==binding['publication_date']
    def get(key,target,publication,old):
        if not selected(target,publication):return old(target,publication)
        if error is not None:raise ValueError(error)
        return copy.deepcopy(result[key])
    service.get_announcement_date_catalog=lambda target,publication:get('catalog',target,publication,old_catalog)
    service.get_announcement_analysis=lambda target,publication=None:get('analysis',target,publication,old_analysis)
    def consumption(owner,target,publication,*,cutoff=None,analysis_readback=None):
        if owner is not service or not selected(target,publication):return old_consumption(owner,target,publication,cutoff=cutoff,analysis_readback=analysis_readback)
        reason=error
        if reason is None and (cutoff is None or aware(cutoff)!=aware(result['cutoff'])):reason='OFFLINE_MANAGER_EXACT_CUTOFF_REQUIRED'
        if reason is not None:
            failed=old_consumption(owner,target,publication,cutoff=cutoff,analysis_readback={})
            failed.update(status='NOT_CONSUMED_INVALID',validation_status='CANNOT_CONFIRM',consumed=False,
                failure_stage='SOURCE_READBACK',gaps=[reason],research_references=[])
            return failed
        return copy.deepcopy(result['consumption'])
    announcements.read_analysis_consumption=consumption


def _worker(request):
    global APP,PIN
    revision='revision_manifest_sha256' in request['binding']
    if revision:APP,PIN=REVISION_APP,REVISION_PIN
    sources();sys.path.insert(0,str(APP))
    from infrastructure.owned_io import SafeRoot
    from ops.run_v5_offline_analysis import OfflineAnalysisOwner,verify_recovery
    from ops.run_v5_private_announcement import SENTINEL_BASE
    from v4.manager_research import workspace_announcements as announcements
    consumer_pin=install_consumer_contract(announcements)
    from urllib.parse import urlencode
    from v5_shadow.composition import no_symlinks
    from datetime import datetime,timezone
    binding=request['binding'];root=no_symlinks(binding['root'])
    if aware(request['cutoff'])>datetime.now(timezone.utc):raise ValueError('OFFLINE_MANAGER_FUTURE_CUTOFF')
    original_init=SafeRoot.__init__
    allowed_roots={root}
    if revision:allowed_roots.add(root.parent.parent)
    def init(io,path):
        if Path(path).absolute() not in allowed_roots:raise ValueError('OFFLINE_MANAGER_ROOT_NOT_BOUND')
        original_init(io,path)
    def existing_directory(io,relative=None):
        with io.directory(relative,create=False):pass
    SafeRoot.__init__=init;SafeRoot.ensure_directory=existing_directory
    def audit(event,args):
        if event.startswith(('socket.','subprocess.','os.exec','os.spawn','os.posix_spawn')) or event in ('os.system','os.fork','os.forkpty'):raise PermissionError('OFFLINE_MANAGER_NETWORK_OR_PROCESS_DENIED')
        if event in ('os.mkdir','os.remove','os.rename','os.rmdir','os.chmod','os.link','os.symlink','os.truncate','os.utime','os.chown','os.lchown','os.fchown','os.fchmod','os.setxattr','os.removexattr'):raise PermissionError('OFFLINE_MANAGER_WRITE_DENIED')
        if event=='open' and args[2] & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND):raise PermissionError('OFFLINE_MANAGER_WRITE_DENIED')
    sys.addaudithook(audit)
    io=SafeRoot(root);raw=io.read_bytes('manager_binding.v1.json')
    if hashlib.sha256(raw).hexdigest()!=binding['binding_sha256']:raise ValueError('OFFLINE_MANAGER_BINDING_SHA')
    declared=json.loads(raw)
    if (declared.get('schema')!='v5.announcement_offline_analysis_binding.v1' or declared.get('status')!='PRIVATE_OWNER_READBACK_VERIFIED'
            or declared.get('owner_root')!=str(root) or declared.get('target_trade_date')!=binding['target_date'] or declared.get('publication_date')!=binding['publication_date']
            or declared.get('network_allowed') is not False or declared.get('capture_allowed') is not False or declared.get('manager_ui_integrated') is not False):raise ValueError('OFFLINE_MANAGER_BINDING_IDENTITY')
    if revision:
        from ops.run_v5_decision_revision import DecisionRevisionOwner
        def existing_once(owner,name,raw):
            if owner.io.read_bytes(name)!=raw:raise ValueError('OFFLINE_REVISION_EXISTING_IDENTITY')
        DecisionRevisionOwner._write_once=existing_once
        if declared.get('revision_manifest_sha256')!=binding['revision_manifest_sha256']:
            raise ValueError('OFFLINE_REVISION_BINDING_SHA')
        owner=DecisionRevisionOwner(root,binding['revision_manifest_sha256'])
        if declared.get('decision_revision')!=owner.revision['decision_revision']:
            raise ValueError('OFFLINE_REVISION_PARENT_BINDING')
    else:owner=OfflineAnalysisOwner(root,declared['recovery_receipt_sha256'])
    if declared['evidence_run_id']!=owner.recovery['source_run_id'] or declared['blocked_policy_sha256']!=owner.recovery['source_policy_sha256']:raise ValueError('OFFLINE_MANAGER_RECOVERY_IDENTITY')
    target=binding['target_date'];publication=binding['publication_date']
    prefix=f"workspace_announcements/{target}/eastmoney_date_catalog/{publication.replace('-','')}/"
    expected=[('product_path',prefix+'analysis.v1.json','product_file_sha256'),
        ('owner_import_receipt_path',prefix+'owner_import_receipt.v1.json','owner_import_receipt_file_sha256'),
        ('readback_path','offline_import_readback.json','readback_file_sha256')]
    def check_products():
        for field,path,digest in expected:
            if declared[field]!=path:raise ValueError('OFFLINE_MANAGER_PRODUCT_PATH')
            if hashlib.sha256(io.read_bytes(path)).hexdigest()!=declared[digest]:raise ValueError('OFFLINE_MANAGER_PRODUCT_SHA')
    check_products();owner._verify_registered()
    catalog=owner.get_announcement_date_catalog(target,publication)
    analysis=owner.request(SENTINEL_BASE,'/api/v4/manager/research/announcements/analysis?'+urlencode({'date':target,'publication_date':publication}))
    if (analysis.get('analysis',{}).get('status')!='VERIFIED' or analysis['analysis']['product_sha256']!=declared['product_sha256']
            or analysis!=json.loads(io.read_bytes('offline_import_readback.json'))):raise ValueError('OFFLINE_MANAGER_ANALYSIS_READBACK_MISMATCH')
    consumption=announcements.read_analysis_consumption(owner,target,publication,cutoff=request['cutoff'],analysis_readback=analysis)
    if request.get('default_analysis') is True:
        # Real default read, not an EXPLICIT payload with its label rewritten.
        # The offline app intentionally ships no calendar because its CLI only
        # accepts explicit dates. Bind the existing manager's verified calendar.
        from types import ModuleType
        from v5_shadow.manager_plan import CAPSULE, _sources
        _sources()
        if 'contracts' in sys.modules:raise ValueError('OFFLINE_DEFAULT_CALENDAR_NAMESPACE_OCCUPIED')
        package=ModuleType('contracts');package.__path__=[str(CAPSULE/'contracts')]
        sys.modules['contracts']=package
        from v4.manager_research.announcement_analysis import read
        analysis=read(owner,target,None)
        if (analysis.get('date_selection_basis')!='PREVIOUS_HK_TRADING_SESSION'
                or analysis.get('publication_date')!=publication
                or analysis.get('analysis',{}).get('status')!='VERIFIED'
                or analysis['analysis']['product_sha256']!=declared['product_sha256']):
            raise ValueError('OFFLINE_DEFAULT_ANALYSIS_DATE_OR_PRODUCT')
    if revision:owner._verify_evidence()
    else:verify_recovery(root,declared['recovery_receipt_sha256'])
    check_products()
    if io.read_bytes('manager_binding.v1.json')!=raw:raise ValueError('OFFLINE_MANAGER_BINDING_CHANGED')
    sources()
    return dict(catalog=catalog,analysis=analysis,consumption=consumption,cutoff=request['cutoff'],
        binding_sha256=binding['binding_sha256'],app_manifest_sha256=PIN,consumer_source_capsule_sha256=consumer_pin,request_sha256=sha256_json(request))


if __name__=='__main__':
    try:
        raw=sys.stdin.buffer.read(MAX_JSON_BYTES+1)
        if len(raw)>MAX_JSON_BYTES:raise ValueError('OFFLINE_MANAGER_REQUEST_LIMIT')
        print(canonical_bytes(_worker(json.loads(raw))).decode())
    except Exception as error:
        print(canonical_bytes(dict(reason=str(error) if isinstance(error,ValueError) else 'OFFLINE_MANAGER_READ_FAILED:'+type(error).__name__)).decode())
        raise SystemExit(1)
