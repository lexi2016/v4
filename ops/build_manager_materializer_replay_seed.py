"""Create a no-producer replay seed/spec from an already persisted natural 15:30 input witness."""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path


def main(argv=None) -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-state-root',type=Path,required=True)
    parser.add_argument('--destination-root',type=Path,required=True)
    parser.add_argument('--trade-date',required=True)
    parser.add_argument('--materializer-app-root',type=Path,required=True)
    parser.add_argument('--materializer-sha256',required=True)
    parser.add_argument('--universe-root',type=Path,required=True)
    parser.add_argument('--news-owner-root',type=Path,required=True)
    parser.add_argument('--universe-owner-root',type=Path,required=True)
    parser.add_argument('--universe-owner-sha256',required=True)
    parser.add_argument('--rebound-authority-root',type=Path,required=True)
    parser.add_argument('--receipt',type=Path,required=True)
    args=parser.parse_args(argv)
    from v4.manager_research.materializer_replay import build_replay_seed, validate_replay_spec
    seed=args.destination_root/'state_seed'
    seed_receipt=build_replay_seed(args.source_state_root.resolve(),seed.resolve(),args.trade_date)
    snapshot=json.loads((seed/f'workbench_research/{args.trade_date}/inputs/1530_futu_snapshot.json').read_bytes())
    available=snapshot['available_at']
    spec={
        'schema_version':'v4.manager_close_offline_replay_spec.v1','trade_date':args.trade_date,
        'clock_iso':available,'materializer_app_root':str(args.materializer_app_root.resolve()),
        'materializer_source_sha256':args.materializer_sha256,'data_root':str((args.destination_root/'data').resolve()),
        'universe_root':str(args.universe_root.resolve()),'news_owner_root':str(args.news_owner_root.resolve()),
        'universe_owner_root':str(args.universe_owner_root.resolve()),'universe_owner_sha256':args.universe_owner_sha256,
        'rebound_authority_root':str(args.rebound_authority_root.resolve()),
    }
    (args.destination_root/'data').mkdir(parents=True,exist_ok=True)
    normalized=validate_replay_spec(spec,state_root=seed)
    spec_path=args.destination_root/'replay-spec.json'
    spec_raw=(json.dumps(normalized,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode();spec_path.write_bytes(spec_raw)
    output={'schema_version':'v4.manager_close_offline_replay_bundle.v1','status':'READY','seed':seed_receipt,
        'replay_spec':str(spec_path.resolve()),'replay_spec_sha256':hashlib.sha256(spec_raw).hexdigest(),
        'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}
    args.receipt.parent.mkdir(parents=True,exist_ok=True)
    args.receipt.write_text(json.dumps(output,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
    print(json.dumps(output,ensure_ascii=False,sort_keys=True))
    return 0


if __name__=='__main__': raise SystemExit(main())
