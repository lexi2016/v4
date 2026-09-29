#!/usr/bin/env python3
"""Existing exact-date V4 review entry, with explicit caller-pinned assembly.

No HOME/source-root fallback, service, scheduler, latest pointer or alternate
provider. Optional Python injection parameters replace raw transport/final SDK
only for offline testing; they are not CLI flags or environment switches.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path

from domains.research_review_generation import GenerationRefused,run_generation
from domains.research_review_generation.assembly import assemble_runtime
from domains.research_review_generation._owned_io import BoundaryError


def _parser() -> argparse.ArgumentParser:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--date',required=True,help='exact YYYYMMDD or YYYY-MM-DD review session')
    p.add_argument('--config',type=Path,required=True,help='explicit non-secret V4 assembly JSON')
    p.add_argument('--config-sha256',required=True,help='caller-approved config SHA, never self-approved')
    p.add_argument('--source-manifest-sha256',required=True,help='caller-approved owned source manifest SHA')
    p.add_argument('--review-root',type=Path,help='optional cross-check; must equal configured state_root/reviews')
    p.add_argument('--replace',action='store_true',help='explicitly approved regeneration of exact artifact')
    return p


def main(argv: list[str] | None = None, *, transport=None,client_factory=None) -> int:
    args=_parser().parse_args(argv)
    try:
        runtime=assemble_runtime(config_path=args.config,config_sha256=args.config_sha256,
            implementation_manifest_sha256=args.source_manifest_sha256,
            transport=transport,client_factory=client_factory)
        result=run_generation(args.date,review_root=args.review_root or runtime.state_root/'reviews',
                              runtime=runtime,replace=args.replace)
    except (GenerationRefused,BoundaryError,OSError,ValueError,ImportError) as exc:
        # Avoid serializing arbitrary SDK exceptions or credential-containing paths.
        print(json.dumps({'status':'CANNOT_CONFIRM','reason_code':type(exc).__name__,
              'reason':'V4 exact-date generation refused; inspect local bound test/validation evidence',
              'production_allowed':False,'buy_gate_updated':False,'orders_sent':False},ensure_ascii=False))
        return 2
    print(json.dumps(result,ensure_ascii=False,sort_keys=True))
    return 0


if __name__=='__main__':raise SystemExit(main())
