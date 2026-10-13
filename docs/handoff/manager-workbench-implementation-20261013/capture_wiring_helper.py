"""Isolated capture-only preparation/canary; no grant, activation or model calls.

Run with PYTHONPATH=. from the worktree. All three writable roots must be inside
an explicitly supplied isolated directory. Existing source roots remain read-only.
"""
from __future__ import annotations
import argparse
from datetime import datetime
import json
from pathlib import Path
from v4.manager_workbench.config import load_config
from v4.manager_workbench.contracts import HK,RunContext
from v4.manager_workbench.inputs.capture_store import CaptureStore
from v4.manager_workbench.inputs.capture import capture_window,resolve_publication_window
from v4.manager_workbench.inputs.capture_binding import publish,read_binding


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',required=True);p.add_argument('--isolated-root',required=True)
    p.add_argument('--target',required=True);p.add_argument('--cutoff',required=True)
    p.add_argument('--phase',choices=['INTRADAY','PREOPEN','NEXT_DAY','RETROSPECTIVE'],default='RETROSPECTIVE')
    p.add_argument('--execute-collect',action='store_true');p.add_argument('--allow-network',action='store_true')
    p.add_argument('--max-bodies',type=int);args=p.parse_args(argv)
    cfg=load_config(args.config);root=Path(args.isolated_root).resolve()
    if not root.is_absolute():raise ValueError('ISOLATED_ROOT_REQUIRED')
    for value in (cfg.state_root,cfg.capture_root,cfg.capture_lease_root):
        if value is None or not value.resolve().is_relative_to(root):raise ValueError('ALL_WRITES_MUST_BE_ISOLATED')
    if args.max_bodies is not None and not 0<=args.max_bodies<=1000:raise ValueError('MAX_BODIES_INVALID')
    ctx=RunContext(target_date=args.target,phase=args.phase,cutoff=args.cutoff,trigger='MANUAL',rules_version=cfg.rules_version)
    window=resolve_publication_window(ctx)
    proof=dict(state='PREPARED',window=window,network_run=False,model_run=False,formal_owner_active=False,
        lease_auto_granted=False,production_allowed=False,buy_gate_updated=False,orders_sent=False)
    if args.execute_collect:
        if not args.allow_network:raise ValueError('EXPLICIT_NETWORK_CANARY_REQUIRED')
        import requests
        cache=CaptureStore(cfg.capture_root,lease_root=cfg.capture_lease_root,token=cfg.capture_lease_token)
        options={'transport':requests.Session()}
        if args.max_bodies is not None:options['max_bodies']=args.max_bodies
        product=capture_window(ctx,options,cache)
        completed=ctx.model_copy(deep=True);completed.cutoff=datetime.now(HK).isoformat()
        with cache.guard():pin=publish(cfg,product,completed,'isolated-capture-canary')
        manifest,saved=read_binding(cfg,pin,completed)
        proof.update(state='SAVED_READBACK',network_run=True,completed_cutoff=completed.cutoff,
            product_ref=product['saved_ref'],binding_pin=pin,observed_count=saved['observed_count'],
            body_complete_count=sum(r['body_complete'] for r in saved['rows']),gaps=saved['gaps'])
    print(json.dumps(proof,ensure_ascii=False))
    return 0


if __name__=='__main__':raise SystemExit(main())
