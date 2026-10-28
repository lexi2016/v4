"""Run the pinned existing 15:30 materializer against a pre-existing offline replay seed."""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path

APP_ROOT=Path(__file__).resolve().parents[1]


def main(argv=None) -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-root',type=Path,required=True)
    parser.add_argument('--trade-date',required=True)
    parser.add_argument('--replay-spec',type=Path,required=True)
    parser.add_argument('--replay-spec-sha256',required=True)
    parser.add_argument('--sandbox-identity',type=Path,required=True)
    parser.add_argument('--receipt',type=Path,required=True)
    args=parser.parse_args(argv)
    raw=args.replay_spec.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=args.replay_spec_sha256:
        raise ValueError('MATERIALIZER_REPLAY_SPEC_SHA_MISMATCH')
    spec=json.loads(raw)
    if spec.get('trade_date')!=args.trade_date:
        raise ValueError('MATERIALIZER_REPLAY_DATE_MISMATCH')
    from v4.manager_research.activation_canary import claim_canary_sandbox_identity
    claimed=claim_canary_sandbox_identity(args.sandbox_identity,'materializer',data_root=args.state_root,
        receipt_path=args.receipt,app_root=APP_ROOT,argv=list(argv) if argv is not None else __import__('sys').argv[1:])
    from v4.manager_research.materializer_replay import execute_offline_replay
    result=execute_offline_replay(spec,state_root=args.state_root)
    output={**result,'sandbox_identity':claimed}
    from infrastructure.owned_io import SafeRoot
    SafeRoot(args.receipt.parent).write_bytes(args.receipt.name,
        (json.dumps(output,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode(),require_absent=True)
    summary={key:output[key] for key in (
        'schema_version','status','materializer_result','snapshot_fetch_calls','external_process_calls',
        'network_calls','input_unchanged','input_identity_sha256','sandbox_identity',
        'production_allowed','buy_gate_updated','orders_sent','RESEARCH_ONLY')}
    print(json.dumps(summary,ensure_ascii=False,sort_keys=True))
    return 0 if result['status']=='SAFE_REPLAY_SUCCEEDED' else 2


if __name__=='__main__': raise SystemExit(main())
