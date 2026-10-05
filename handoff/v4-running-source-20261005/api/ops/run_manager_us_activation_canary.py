"""Invoke the existing US producer once in an isolated owned data root, then read it through Manager.

This is an activation canary, not a new producer.  It calls
``ops.us_market_digest.materialize_us_market_phase`` and verifies that the
existing Manager exact-session reader consumes the same payload/receipt/
manifest identity.  The data root must contain the explicit sandbox marker.
"""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
from datetime import datetime

APP_ROOT=Path(__file__).resolve().parents[1]


def tree_manifest(root: Path) -> dict[str,str]:
    return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob('*')) if p.is_file() and not p.is_symlink()}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root',required=True)
    parser.add_argument('--us-session-date',required=True)
    parser.add_argument('--target-hk-date',required=True)
    parser.add_argument('--manager-cutoff',required=True)
    parser.add_argument('--capture-phase',default='POST_CLOSE',choices=('POST_CLOSE','PRE_OPEN'))
    parser.add_argument('--allow-late-post-close',action='store_true')
    parser.add_argument('--sandbox-identity',required=True)
    parser.add_argument('--receipt',required=True)
    args=parser.parse_args(argv)
    try:
        from v4.manager_research.activation_canary import claim_canary_sandbox_identity
        sandbox_identity=claim_canary_sandbox_identity(args.sandbox_identity,'us',
            data_root=args.data_root,receipt_path=args.receipt,app_root=APP_ROOT,
            argv=argv or __import__('sys').argv[1:])
    except (OSError,ValueError,TypeError) as exc:
        raise ValueError('US_CANARY_SANDBOX_IDENTITY_INVALID') from exc
    root=Path(sandbox_identity['data_root']); receipt=Path(sandbox_identity['receipt_path'])
    source_before=tree_manifest(APP_ROOT)
    from ops.us_market_digest import materialize_us_market_phase
    producer=materialize_us_market_phase(data_root=root,trade_date=args.us_session_date,
        capture_phase=args.capture_phase,allow_late_post_close=args.allow_late_post_close,
        us_session_date=args.us_session_date)
    payload=producer.get('payload') if isinstance(producer,dict) else None
    snapshot=payload.get('market_snapshot') if isinstance(payload,dict) else None
    from v4.manager_research.us_market_bridge import ResearchPeripheralUsMarketReader, project_us_market
    reader=ResearchPeripheralUsMarketReader(root)
    bridge=project_us_market(reader,args.target_hk_date,{'research_cutoff':args.manager_cutoff})
    _,lineage=reader.read_exact_session(args.us_session_date)
    from v4.manager_research.activation_canary import evaluate_us_activation
    evidence={
      'producer_invoked':True,
      'producer_status':snapshot.get('status') if isinstance(snapshot,dict) else producer.get('market_snapshot_status'),
      'payload_sha256':producer.get('payload_sha256'),
      'reader_lineage':lineage,
      'bridge_status':bridge.get('status'),
      'expected_us_session':bridge.get('expected_us_session'),
      'producer_us_session':args.us_session_date,
      'source_unchanged':tree_manifest(Path(__file__).resolve().parents[1])==source_before,
      'bridge_coverage':bridge.get('coverage'),
      'bridge_gaps':bridge.get('gaps'),
      'producer_reused':producer.get('reused'),
    }
    decision=evaluate_us_activation(evidence)
    output={'schema_version':'v4.manager_research.us_activation_canary.v2','decision':decision,'producer':{k:v for k,v in producer.items() if k!='payload'},'bridge':bridge,
            'sandbox_identity':sandbox_identity,
            'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}
    from infrastructure.owned_io import SafeRoot
    SafeRoot(receipt.parent).write_bytes(receipt.name,
        (json.dumps(output,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode('utf-8'),require_absent=True)
    print(json.dumps(output,ensure_ascii=False,sort_keys=True))
    return 0 if decision['status']=='PASS' else 2

if __name__=='__main__':raise SystemExit(main())
