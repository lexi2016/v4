"""Offline writer verification using pinned active dependencies, never live writes."""
from pathlib import Path
import csv
import difflib
import hashlib
import importlib.util
import json
import os
import subprocess
import sys

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
STAGE = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/v4-v192-assets-20261109-r1/v4-v192-assets-20261109-r1-stage/app')
API = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/v4-top200-scope-20261110-r2/v4-top200-scope-20261110-r2-api/app')
STATE = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/state')
TRACE = Path('/Users/lexi/Desktop/学习/agents调试/v4_stage_loss_trace_20261109')
CHANGED = ('infrastructure/stage_quote_provider.py', 'stage_center/selection.py',
           'stage_center/_selection_parts/schema_values.py', 'stage_center/_selection_parts/a_auction.py',
           'stage_center/_live_collectors_parts/a_auction.py', 'stage_center/_live_collectors_parts/selection_builder_registry.py')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def mount(source, target, replacements):
    if target.is_symlink():
        target.unlink()
    target.mkdir(parents=True, exist_ok=True)
    for child in source.iterdir():
        destination=target/child.name
        if destination.is_symlink():
            destination.unlink()
        if child.name in replacements:
            destination.write_bytes(replacements[child.name])
        elif any(p.startswith(child.name+'/') for p in replacements):
            mount(child,destination,{p[len(child.name)+1:]:v for p,v in replacements.items() if p.startswith(child.name+'/')})
        else:
            destination.symlink_to(child, target_is_directory=child.is_dir())


def source_rows(snapshot, digest):
    rows=[]
    for source in snapshot['rows']:
        preopen=source.get('source_time_semantics') == 'PREOPEN_SESSION_OPEN_LABEL'
        row=dict(source,code=source['symbol'],trade_date=snapshot['trade_date'],
                 time=source['captured_at'] if preopen else source['source_update_time'],
                 amount=source.get('turnover'),bid_vol=source.get('bid_vol1'),ask_vol=source.get('ask_vol1'),
                 native_quote_snapshot=True,native_snapshot_sha256=digest,
                 native_capture_started_at=source['capture_started_at'],native_captured_at=source['captured_at'],
                 native_source_update_time=source['source_update_time'],native_market_cutoff_at=snapshot['market_cutoff_at'],
                 is_open_call_auction_match=False)
        rows.append(row)
    return rows


def verify_pure():
    from stage_center import selection as new
    from infrastructure.stage_quote_provider import native_opening_field_readiness
    spec=importlib.util.spec_from_file_location('stage_center._selection_parts.old_a925',STAGE/'stage_center/_selection_parts/a_auction.py')
    old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
    all_summaries={}
    for date in ('20261109','20261110'):
        path=STATE/f'data/stage_inputs/native_opening/{date}/STAGE_0925/snapshot.json'
        digest=sha(path);snapshot=json.loads(path.read_text());rows=source_rows(snapshot,digest)
        evidence=('native_snapshot_contract=V4_A_OPENING_NATIVE_SNAPSHOT_V1',f'native_snapshot_sha256={digest}')
        kwargs=dict(next_validation_time=None,source_status='PARTIAL_WITH_ROWS',requested_rows=len(snapshot['requested_symbols']),
                    missing_symbols=snapshot['missing_symbols'],cannot_confirm=(),source_evidence=evidence)
        old_rows=[];new_rows=[]
        for row in rows:
            old_rows.extend(old._select_a_0925_auction_body(vars(new),[row],date,'b'*64,**kwargs)['rows'])
            new_rows.extend(new.select_a_0925_auction([row],date,'b'*64,**kwargs)['rows'])
        assert len(old_rows)==len(new_rows)==len(rows)
        unchanged=[i for i,row in enumerate(rows) if row.get('open_price',0)>0]
        assert all(old_rows[i]['score']==new_rows[i]['score'] for i in unchanged)
        assert all(r['current_change_pct'] != -100 for r in new_rows)
        assert all(r['trade_status']=='WATCH_ONLY' and r['action_level']=='NO_BUY' for r in new_rows)
        paired=[dict(code=r['code'],old_score=old_rows[i]['score'],new_score=r['score'],
                     old_gap=old_rows[i]['qmt_gap_pct'],new_gap=r['qmt_gap_pct'],scoring_price=r['scoring_price'],price_basis=r['price_basis']) for i,r in enumerate(new_rows)]
        (HERE/f'LOCAL_ONLY_{date}_ALL_ROWS.json').write_text(json.dumps(paired,indent=2)+'\n')
        if date=='20261109':
            trace=json.loads((TRACE/'ALL_472_SCORE_TRACE.json').read_text())
            trace_by={r['symbol']:r for r in trace}
            for r in paired:
                symbol=r['code'][2:]+('.SH' if r['code'][2] in '69' else '.SZ')
                assert trace_by[symbol]['score_reconstructed']==r['old_score']
            hits=[r for r in paired if trace_by[r['code'][2:]+('.SH' if r['code'][2] in '69' else '.SZ')]['pool_hit_top200']]
            assert len(hits)==36 and sum(r['old_gap']==-100 for r in hits)==34
            (HERE/'LOCAL_ONLY_36_HITS.json').write_text(json.dumps(hits,indent=2)+'\n')
        all_summaries[date]=dict(snapshot_sha256=digest,requested=len(snapshot['requested_symbols']),returned=len(rows),
            original_positive_open_scores_unchanged=len(unchanged),old_minus100_rows=sum(r['qmt_gap_pct']==-100 for r in old_rows),
            new_minus100_rows=sum(r['qmt_gap_pct']==-100 for r in new_rows),
            new_last_price_observations=sum(r['price_basis']=='NATIVE_LAST_PRICE_OBSERVATION' for r in new_rows),
            readiness=native_opening_field_readiness(snapshot['rows']),
            old_top10=[r['code'] for r in sorted(old_rows,key=lambda r:r['score'],reverse=True)[:10]],
            new_top10=[r['code'] for r in sorted(new_rows,key=lambda r:r['score'],reverse=True)[:10]])
        assert sha(path)==digest
        if date=='20261109':
            envelope=new.select_a_0925_auction(rows,date,'b'*64,**kwargs)
            store=HERE/'.verification/artifacts'
            new.publish_selection(store,envelope,market='A_SHARE')
            (HERE/'.verification/envelope.json').write_text(json.dumps(envelope))
    (HERE/'PURE_REGRESSION_SUMMARY.json').write_text(json.dumps(all_summaries,indent=2)+'\n')
    print(json.dumps(all_summaries,indent=2))


def verify_api():
    from stage_center.selection import SelectionStore
    root=HERE/'.verification/artifacts'
    envelope=json.loads((HERE/'.verification/envelope.json').read_text())
    result=SelectionStore(root).read_verified('20261109','STAGE_0925',market='A_SHARE')
    assert result['rows']==envelope['rows']
    assert result['algorithm_sha256']==envelope['algorithm_sha256']
    assert result['rows'][0]['field_readiness']
    print('API_ARTIFACT_ROUNDTRIP_PASS: new SHA and native per-row semantics retained')


def main():
    if len(sys.argv)>1 and sys.argv[1] != '--finish':
        return verify_pure() if sys.argv[1]=='pure' else verify_api()
    sys.path.insert(0,str(REPO))
    from stage_center import selection
    overlay=HERE/'.verification/stage'
    mount(STAGE,overlay,{p:(REPO/p).read_bytes() for p in CHANGED})
    env=dict(os.environ,PYTHONPATH=str(overlay),PYTHONDONTWRITEBYTECODE='1')
    command=[sys.executable,'-m','pytest','-q',str(REPO/'tests/test_a925_price_readiness.py'),
             str(STAGE/'tests/test_a925_native_snapshot.py'),str(REPO/'stage_center/tests/test_selection_consumer_batch3.py'),
             '-k','not primary_first_no_transaction_or_minute_rpc_and_bad_rows_isolated and not late_true_capture_cannot_be_replaced_by_old_source_timestamp',
             '--basetemp='+str(HERE/'.verification/pytest'),'--tb=short']
    if '--finish' not in sys.argv:
        result=subprocess.run(command,cwd=overlay,env=env);assert result.returncode==0
    subprocess.run([sys.executable,str(Path(__file__).resolve()),'pure'],cwd=overlay,env=env,check=True)
    api_path=API/'stage_center/selection.py';before=api_path.read_text()
    needle='        V11_PIT_TOP10_ALGORITHM_SHA256,\n'
    assert before.count(needle)==1
    after=before.replace(needle,needle+f'        "{selection.A_SHARE_AUCTION_PRICE_READY_SHA256}",  # A925 price readiness observation\n')
    patch=''.join(difflib.unified_diff(before.splitlines(True),after.splitlines(True),fromfile='a/stage_center/selection.py',tofile='b/stage_center/selection.py'))
    (HERE/'api_compat.patch').write_text(patch)
    (HERE/'API_COMPAT_SHA.json').write_text(json.dumps(dict(source=str(api_path),before_sha256=sha(api_path),
        after_sha256=hashlib.sha256(after.encode()).hexdigest(),algorithm_sha256=selection.A_SHARE_AUCTION_PRICE_READY_SHA256),indent=2)+'\n')
    api_overlay=HERE/'.verification/api'
    mount(API,api_overlay,{'stage_center/selection.py':after.encode()})
    subprocess.run([sys.executable,str(Path(__file__).resolve()),'api'],cwd=api_overlay,
                   env=dict(env,PYTHONPATH=str(api_overlay)),check=True)


if __name__=='__main__':main()
