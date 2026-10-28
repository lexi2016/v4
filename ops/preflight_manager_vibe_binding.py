"""Read-only validation of the operator-owned Vibe binding; never calls Vibe."""
from __future__ import annotations
import argparse, json
from pathlib import Path
from infrastructure.owned_io import SafeRoot
from v4.manager_research.vibe_binding_preflight import preflight_vibe_binding


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binding')
    parser.add_argument('--date',action='append',required=True)
    args=parser.parse_args(argv)
    config=None
    if args.binding:
        path=Path(args.binding).expanduser()
        if not path.is_absolute() or '..' in path.parts: raise ValueError('VIBE_BINDING_PATH_MUST_BE_EXACT_ABSOLUTE')
        config=json.loads(SafeRoot(path.parent).read_bytes(path.name,max_bytes=1024*1024))
    print(json.dumps(preflight_vibe_binding(config,args.date),ensure_ascii=False,sort_keys=True))
    return 0

if __name__=='__main__': raise SystemExit(main())
