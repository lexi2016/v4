"""Invoke the existing US producer once in an isolated owned data root, then read it through Manager.

This is an activation canary, not a new producer.  It calls
``ops.us_market_digest.materialize_us_market_phase`` and verifies that the
existing Manager exact-session reader consumes the same payload/receipt/
manifest identity. A fresh, empty, identity-bound data root is required.
Only a new natural POST_CLOSE capture can pass; recovery and reuse cannot.
"""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
from datetime import datetime, timezone

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
    evidence={'producer_invoked':False,'source_unchanged':True}
    producer={}; bridge={}; extra_gaps=[]
    run_id=str(sandbox_identity['run_id'])
    capture_id='manager-us-canary:'+run_id
    started=datetime.now(timezone.utc).replace(microsecond=0)
    freshness={'run_id':run_id,'capture_id':capture_id,'attempt_started_at':started.isoformat(),
               'data_root_empty_before':False,'fresh_capture_verified':False}
    try:
        from ops.us_market_digest import (materialize_us_market_phase,
            us_capture_window, us_market_day_certification, _is_late_capture_identity)
        if args.capture_phase!='POST_CLOSE' or args.allow_late_post_close:
            extra_gaps.append('US_CANARY_NATURAL_POST_CLOSE_REQUIRED')
        freshness['data_root_empty_before']=not any(root.iterdir())
        if not freshness['data_root_empty_before']:
            extra_gaps.append('US_CANARY_DATA_ROOT_NOT_EMPTY')
        day=us_market_day_certification(args.us_session_date)
        if day.get('status')!='VERIFIED':
            extra_gaps.append('US_CANARY_CALENDAR_UNVERIFIED')
        window_start,window_end=us_capture_window(args.us_session_date,'POST_CLOSE')
        if not window_start<=started<window_end:
            extra_gaps.append('US_CANARY_OUTSIDE_NATURAL_WINDOW')
        if not extra_gaps:
            # Do not forward a clock, backfill timestamp or injected provider.
            evidence['producer_invoked']=True
            producer=materialize_us_market_phase(data_root=root,trade_date=args.us_session_date,
                capture_phase='POST_CLOSE',allow_late_post_close=False,
                us_session_date=args.us_session_date,run_id=run_id,capture_id=capture_id)
            finished=datetime.now(timezone.utc)
            freshness['attempt_finished_at']=finished.isoformat()
            if not isinstance(producer,dict):
                raise TypeError('US_CANARY_PRODUCER_RESULT_INVALID')
            payload=producer.get('payload')
            if not isinstance(payload,dict):
                raise TypeError('US_CANARY_PAYLOAD_INVALID')
            snapshot=payload.get('market_snapshot')
            if not isinstance(snapshot,dict):
                raise TypeError('US_CANARY_SNAPSHOT_INVALID')
            if (producer.get('reused') is not False or producer.get('replaced') is not False
                    or producer.get('retained_previous') not in (None,False)):
                extra_gaps.append('US_CANARY_CAPTURE_NOT_NEW')
            captures=payload.get('us_session_captures')
            row=captures[0] if isinstance(captures,list) and len(captures)==1 else None
            if not isinstance(row,dict):
                extra_gaps.append('US_CANARY_SINGLE_CAPTURE_REQUIRED')
            else:
                if (row.get('run_id')!=run_id or row.get('capture_id')!=capture_id
                        or row.get('us_session_date')!=args.us_session_date
                        or row.get('capture_phase')!='POST_CLOSE'
                        or row.get('capture_origin')!='ORIGINAL_TIME_CAPTURE'
                        or row.get('original_time_capture') is not True):
                    extra_gaps.append('US_CANARY_CAPTURE_IDENTITY_MISMATCH')
                for item in (payload,snapshot,row):
                    if _is_late_capture_identity(item):
                        extra_gaps.append('US_CANARY_LATE_OR_RECOVERED_CAPTURE')
                try:
                    captured=datetime.fromisoformat(str(row.get('captured_at') or '').replace('Z','+00:00'))
                    snapshot_time=datetime.fromisoformat(str(snapshot.get('captured_at') or '').replace('Z','+00:00'))
                    if (captured.tzinfo is None or snapshot_time.tzinfo is None
                            or not started<=captured<=finished
                            or not window_start<=captured<window_end
                            or snapshot_time!=captured):
                        extra_gaps.append('US_CANARY_CAPTURE_TIME_MISMATCH')
                except (TypeError,ValueError):
                    extra_gaps.append('US_CANARY_CAPTURE_TIME_MISMATCH')
            if (snapshot.get('capture_phase')!='POST_CLOSE'
                    or snapshot.get('capture_session_date')!=args.us_session_date
                    or snapshot.get('provider_session_dates')!=[args.us_session_date]):
                extra_gaps.append('US_CANARY_SNAPSHOT_SESSION_MISMATCH')
            from v4.manager_research.us_market_bridge import ResearchPeripheralUsMarketReader, project_us_market
            reader=ResearchPeripheralUsMarketReader(root)
            bridge=project_us_market(reader,args.target_hk_date,{'research_cutoff':args.manager_cutoff})
            read_payload,lineage=reader.read_exact_session(args.us_session_date)
            if read_payload!=payload:
                extra_gaps.append('US_CANARY_READER_PAYLOAD_MISMATCH')
            evidence.update({
              'producer_status':snapshot.get('status'),
              'payload_sha256':producer.get('payload_sha256'),
              'reader_lineage':lineage,'bridge_status':bridge.get('status'),
              'expected_us_session':bridge.get('expected_us_session'),
              'producer_us_session':args.us_session_date,
              'bridge_coverage':bridge.get('coverage'),'bridge_gaps':bridge.get('gaps'),
              'producer_reused':producer.get('reused'),
            })
            freshness['fresh_capture_verified']=not extra_gaps
    except Exception as exc:
        # An isolated failed attempt must not become an absent/silent receipt.
        # Never serialize provider exception text, URLs, credentials or tracebacks.
        extra_gaps.append('US_CANARY_ATTEMPT_FAILED')
        freshness['exception_type']=type(exc).__name__
        freshness['fresh_capture_verified']=False
    evidence['source_unchanged']=tree_manifest(APP_ROOT)==source_before
    evidence['fresh_capture_evidence']=freshness
    from v4.manager_research.activation_canary import evaluate_us_activation
    decision=evaluate_us_activation(evidence)
    decision['gaps']=sorted(set(decision['gaps'])|set(extra_gaps))
    decision['status']='STOP' if decision['gaps'] else 'PASS'
    freshness['fresh_capture_verified']=decision['status']=='PASS'
    output={'schema_version':'v4.manager_research.us_activation_canary.v2','decision':decision,
            'producer':{k:v for k,v in producer.items() if k!='payload'} if isinstance(producer,dict) else {},
            'bridge':bridge,'sandbox_identity':sandbox_identity,
            'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}
    from infrastructure.owned_io import SafeRoot
    SafeRoot(receipt.parent).write_bytes(receipt.name,
        (json.dumps(output,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode('utf-8'),require_absent=True)
    print(json.dumps(output,ensure_ascii=False,sort_keys=True))
    return 0 if decision['status']=='PASS' else 2

if __name__=='__main__':raise SystemExit(main())
