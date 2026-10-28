"""Render an exact, reviewable binding for the existing announcement worker.

It does not edit launchd or enable anything.  The output defaults to disabled;
Codex may render a second enabled copy only after the shared-root canary passes.
"""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
from infrastructure.owned_io import SafeRoot
from infrastructure.scheduling.manager_announcement_supervisor import BINDING_SCHEMA,binding_inventory,validate_binding


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--app-root',required=True);p.add_argument('--manager-state-root',required=True);p.add_argument('--security-master-root',required=True)
    p.add_argument('--python',required=True);p.add_argument('--output',required=True);p.add_argument('--enabled',action='store_true')
    p.add_argument('--activation-receipt')
    p.add_argument('--policy',default='BALANCED_V1',choices=('BALANCED_V1','LOW_LOAD_V1'));p.add_argument('--priority-code',action='append',default=[])
    p.add_argument('--preopen-lead-seconds',type=int,default=180)
    args=p.parse_args(argv)
    app=Path(args.app_root).expanduser().resolve();py=Path(args.python).expanduser();resolved=py.resolve();out=Path(args.output).expanduser().resolve()
    activation=None
    if args.enabled:
        if not args.activation_receipt:
            raise ValueError('ANNOUNCEMENT_ACTIVATION_RECEIPT_REQUIRED')
        receipt=Path(args.activation_receipt).expanduser()
        if not receipt.is_absolute() or '..' in receipt.parts or receipt.resolve()!=receipt:
            raise ValueError('ANNOUNCEMENT_ACTIVATION_RECEIPT_PATH_NOT_EXACT')
        raw=SafeRoot(receipt.parent).read_bytes(receipt.name,max_bytes=8*1024*1024)
        activation={'path':str(receipt),'sha256':hashlib.sha256(raw).hexdigest()}
    value={'schema_version':BINDING_SCHEMA,'enabled':bool(args.enabled),'policy_status':'PROPOSAL_ONLY','policy':args.policy,
      'production_allowed':False,'buy_gate_updated':False,'orders_sent':False,'research_only':True,
      'app_root':str(app),'manager_state_root':str(Path(args.manager_state_root).expanduser().resolve()),
      'security_master_root':str(Path(args.security_master_root).expanduser().resolve()),'python':str(py),'python_resolved':str(resolved),
      'python_sha256':hashlib.sha256(resolved.read_bytes()).hexdigest(),'priority_codes':list(dict.fromkeys(args.priority_code)),
      'preopen_plan':{'enabled':True,'lead_seconds':args.preopen_lead_seconds,'status':'PROPOSAL_ONLY'},'files':binding_inventory(app)}
    if activation is not None:value['activation_receipt']=activation
    validate_binding(value,app);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2))
    print(json.dumps({'status':'RENDERED_DISABLED' if not args.enabled else 'RENDERED_ENABLED_CANARY_VALIDATED','path':str(out),'file_count':len(value['files'])},ensure_ascii=False))
    return 0
if __name__=='__main__':raise SystemExit(main())
