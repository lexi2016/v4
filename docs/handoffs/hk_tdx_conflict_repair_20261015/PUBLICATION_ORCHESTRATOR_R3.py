"""Call existing HK publishers and stores only; never run the paired A producer.

Production invocation is gated by the independent candidate receipt and the
exact publication plan. No command in this file is run while preparing it.
"""
from pathlib import Path
import argparse, hashlib, json, os, sys, math

H = Path(__file__).resolve().parent
ROLE = 'HK_CONNECT_D1_TOP100_0_2'
POOL = 'hkconnect_d1_top100'

def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()

def complete_consumer_identity(payload, pool, *, policy, signal_date, target_date):
    """Add only optional source pins from the mapper's same verified run."""
    result = dict(payload)
    verification = pool.run.verification
    if (pool.run.receipt.get('status') != 'READY' or verification.get('status') != 'READY'
            or len(pool.rows) != 100 or len({r['code_norm'] for r in pool.rows}) != 100
            or [int(r['rank']) for r in pool.rows] != list(range(1,101))
            or any(not math.isfinite(float(r['score_prob_active'])) for r in pool.rows)
            or any(str(r.get('signal_date') or '') != signal_date
                or str(r.get('target_date') or '') != target_date for r in pool.rows)
            or result.get('status') not in {'STRICT_0_2_READY','HK_0_2_TOP100_READY','READY'}):
        raise ValueError('HK_PUBLICATION_NOT_EXACT_READY100')
    proof = pool.run.manifest['provenance']['history_resolution_proof']
    policy.verify_proof(proof,end=signal_date,consumer='HK_FROZEN_SCORE_PRICE121_TRADE_CURRENT_V1',
        codes=[r['code_norm'] for r in pool.rows])
    for field,value in dict(signal_date=signal_date,target_date=target_date,stage_selection_eligible=True).items():
        if field in result and result[field] != value:
            raise ValueError('HK_PUBLICATION_MAPPER_DATE_OR_ADMISSION_MISMATCH')
        result[field] = value
    if (result.get('pool_id') != POOL or result.get('market') != 'HK'
            or result.get('source_role') != 'SHARED_VERIFIED_HK_0_2'
            or result.get('source_sha256') != verification['artifact_sha256']
            or result.get('source_run_id') != verification['run_id']):
        raise ValueError('HK_PUBLICATION_MAPPER_SOURCE_MISMATCH')
    for field, key in [('source_artifact_sha256', 'artifact_sha256'), ('source_manifest_sha256', 'manifest_sha256'),
                       ('source_receipt_sha256', 'receipt_sha256')]:
        value = verification[key]
        if field in result and result[field] != value:
            raise ValueError('HK_PUBLICATION_MAPPER_PIN_MISMATCH')
        result[field] = value
    return result

def verify_published_pool(pool, row):
    assert pool.run.receipt['status']=='READY' and len(pool.rows)==100
    assert len({r['code_norm'] for r in pool.rows})==100
    assert [int(r['rank']) for r in pool.rows]==list(range(1,101))
    scores=[float(r['score_prob_active']) for r in pool.rows]
    assert all(math.isfinite(v) for v in scores) and scores==sorted(scores,reverse=True)
    token=pool.run.manifest['provenance']['history_resolution_proof']
    assert hashlib.sha256(token.encode()).hexdigest()==row['expected_proof_sha256']

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=['shared', 'consumer'])
    parser.add_argument('--target', choices=['20261015', '20261016'], required=True)
    args = parser.parse_args()
    review = json.loads((H/'CANDIDATE_REVIEW_COMBINED_R3.json').read_bytes())
    assert review['verdict'] == 'PASS' and review['findings'] == []
    pub = json.loads((H/'PUBLICATION_COMBINED_R3.json').read_bytes())
    plan = json.loads((H/'PUBLICATION_STATE_PLAN_R3.json').read_bytes())
    row = plan['targets'][args.target]
    owner = Path(plan['owner']); shared = Path(plan['shared_root']); data = Path(plan['consumer_root'])
    # Real publication always consumes the installed pointer, never a test override.
    assert 'V4_HK_HISTORY_RESOLUTION_POINTER' not in os.environ
    assert hashlib.sha256((owner/'history_resolution_latest.json').read_bytes()).hexdigest() == plan['prepared_pointer_sha256']
    sys.path.insert(0, pub['shared']['app_root'])
    from shared_data import hk_0_2 as hk
    from shared_data.hk_history_resolution import policy_for_shared
    from shared_data.store import SafeRootStore
    assert Path(hk.__file__) == Path(pub['shared']['app_root'])/'shared_data/hk_0_2.py'
    policy = policy_for_shared(shared)
    assert policy.manifest_sha256 == plan['resolution_manifest_sha256']
    assert policy.current_panel_sha256 == plan['current_panel_sha256']
    if args.phase == 'shared':
        store = SafeRootStore(shared)
        # Existing publisher takes the shared-store lock and enforces the full
        # seven-field previous identity, or rejects a competing create slot.
        if row['shared_expected_previous'] is None:
            assert store._load_latest()['entries'].get(args.target+'/'+ROLE) is None
        result = hk.materialize_frozen_hk_0_2(shared, owner,
            signal_date=row['signal_date'], target_date=args.target,
            expected_previous=row['shared_expected_previous'])
        pool = hk.read_verified_hk_0_2_pool(shared, target_date=args.target,
            expected_signal_date=row['signal_date'])
        verify_published_pool(pool,row)
        output = {k: pool.run.verification[k] for k in ['run_id', 'artifact_sha256', 'manifest_sha256', 'receipt_sha256']}
        output['already_exists'] = result.get('already_exists', False)
    else:
        sys.path.insert(0, pub['api']['app_root'])
        from domains.preselection_materializer import build_shared_hk_0_2_pool
        from infrastructure.preselection_pool_store import PreselectionPoolStore
        pool = hk.read_verified_hk_0_2_pool(shared, target_date=args.target,
            expected_signal_date=row['signal_date'])
        verify_published_pool(pool,row)
        published=json.loads((H/f'PUBLISHED_{args.target}_SHARED.json').read_bytes())['result']
        assert all(pool.run.verification[key]==published[key] for key in ['run_id','artifact_sha256','manifest_sha256','receipt_sha256'])
        payload = build_shared_hk_0_2_pool(shared, trade_date=args.target,
            signal_date=row['signal_date'], reader=lambda *a, **kw: pool)
        payload = complete_consumer_identity(payload, pool, policy=policy, signal_date=row['signal_date'], target_date=args.target)
        store = PreselectionPoolStore(data)
        manifest_path = data/f'preselection_pools/{args.target}/manifest.json'
        manifest = json.loads(manifest_path.read_bytes()) if manifest_path.exists() else {}
        non_hk = {k: v for k, v in manifest.items() if k != POOL}
        if row['consumer_expected_previous'] is not None:
            result = store.refresh_verified_hk_resolution(payload,
                expected_previous=row['consumer_expected_previous'], shared_root=shared,
                shared_package_root=Path(pub['shared']['app_root']))
        else:
            # The existing create method holds the import lock, preserves all
            # other entries, and rejects conflicting/partial/racing artifacts.
            for relative in [f'preselection_pools/{args.target}/{POOL}.json',
                             f'preselection_pools/{args.target}/receipts/{POOL}.json',
                             f'preselection_pending_commits/{args.target}/{POOL}.json']:
                assert not (data/relative).exists(), 'HK_CREATE_PREIMAGE_CHANGED'
            assert POOL not in manifest
            assert pool.run.receipt['status'] == 'READY' and len(pool.rows) == 100
            token = pool.run.manifest['provenance']['history_resolution_proof']
            policy.verify_proof(token, end=row['signal_date'],
                consumer='HK_FROZEN_SCORE_PRICE121_TRADE_CURRENT_V1',
                codes=[r['code_norm'] for r in pool.rows])
            result = store.materialize(payload)
        after = json.loads(manifest_path.read_bytes())
        assert {k: v for k, v in after.items() if k != POOL} == non_hk
        output = dict(result, source_run_id=pool.run.verification['run_id'],
            source_sha256=pool.run.verification['artifact_sha256'], row_count=100,
            non_HK_manifest_entries_unchanged=True)
    receipt = dict(phase=args.phase, target_date=args.target, signal_date=row['signal_date'],
        result=output, A_producer_called=False, production_allowed=False,
        buy_gate_updated=False, orders_sent=False, raw_rows_or_scores_exported=False)
    (H/f'PUBLISHED_{args.target}_{args.phase.upper()}.json').write_text(json.dumps(receipt, sort_keys=True, indent=2)+'\n')
    print(json.dumps(receipt, sort_keys=True))

if __name__ == '__main__':
    main()
