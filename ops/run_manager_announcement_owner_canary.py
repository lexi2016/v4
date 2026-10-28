"""Invoke the existing announcement owner once against an isolated Manager state root.

This is not a scheduler or a second collector. It exists only so the shared-root
compatibility canary can exercise the real HKEX provider/store writer while the
normal 15:30 materializer writes a separate isolated copy. It never edits a
binding or LaunchAgent and preserves all research/trading safety flags.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

APP_ROOT=Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0,str(APP_ROOT))


def main(argv=None) -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-root',type=Path,required=True)
    parser.add_argument('--security-master-root',type=Path,required=True)
    parser.add_argument('--trade-date',required=True)
    parser.add_argument('--sandbox-identity',type=Path,required=True)
    parser.add_argument('--receipt',type=Path,required=True)
    args=parser.parse_args(argv)
    root=args.state_root.expanduser()
    master=args.security_master_root.expanduser()
    receipt=args.receipt.expanduser()
    try:
        from v4.manager_research.activation_canary import claim_canary_sandbox_identity
        sandbox_identity=claim_canary_sandbox_identity(args.sandbox_identity,'announcement',
            data_root=root,receipt_path=receipt,app_root=APP_ROOT,security_master_root=master,argv=argv or sys.argv[1:])
    except (OSError,ValueError,TypeError) as exc:
        raise ValueError('ANNOUNCEMENT_CANARY_SANDBOX_IDENTITY_INVALID') from exc
    root=Path(sandbox_identity['data_root'])
    master=Path(master)
    from v4.manager_research.materials import MaterialStore
    from v4.manager_research.store import ManagerResearchStore
    from v4.manager_research.hkex_provider import HkexOfficialProvider
    from v4.manager_research.service import ManagerResearchJobService
    materials=MaterialStore(root/'materials')
    provider=HkexOfficialProvider(material_store=materials,timeout=5)
    service=ManagerResearchJobService(ManagerResearchStore(root),None,provider,
        material_store=materials,workspace_security_master_root=master)
    try:
        result=service.refresh_announcements(args.trade_date)
        readback=service.get_announcements(args.trade_date)
        if not isinstance(result,dict) or not isinstance(readback,dict):
            raise ValueError('ANNOUNCEMENT_CANARY_READBACK_INVALID')
        output={
            'schema_version':'v4.manager_research.announcement_owner_canary.v2',
            'status':readback.get('status'),
            'attempt':readback.get('attempt'),
            'coverage':readback.get('coverage'),
            'gaps':readback.get('gaps'),
            'sandbox_identity':sandbox_identity,
            'production_allowed':False,'buy_gate_updated':False,'orders_sent':False,
        }
        from infrastructure.owned_io import SafeRoot
        SafeRoot(receipt.parent).write_bytes(receipt.name,
            (json.dumps(output,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode('utf-8'),require_absent=True)
        print(json.dumps(output,ensure_ascii=False,sort_keys=True))
        return 0 if readback.get('status') in {'PARTIAL','SUCCEEDED','SUCCEEDED_EMPTY'} else 2
    finally:
        service.close()


if __name__=='__main__':
    raise SystemExit(main())
