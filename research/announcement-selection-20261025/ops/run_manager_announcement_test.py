#!/usr/bin/env python3
"""Serve only the explicit isolated test app and its prebuilt same-source UI."""
from pathlib import Path
import argparse
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path: sys.path.insert(0,str(REPO_ROOT))


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--context',required=True)
    parser.add_argument('--context-sha256',required=True)
    parser.add_argument('--test-root',required=True)
    parser.add_argument('--web-dist',required=True)
    parser.add_argument('--port',type=int,default=8897)
    args=parser.parse_args(argv)
    if args.port in {8873,8910} or not 1024 <= args.port <= 65535:
        parser.error('isolated port required')
    from v4.manager_workbench.announcement_test import TestContext,create_app,_path
    from fastapi.staticfiles import StaticFiles
    import uvicorn
    root=_path(args.test_root)
    context=TestContext.load(Path(args.context),args.context_sha256,allowed_test_root=root)
    dist=_path(args.web_dist,within=root)
    app=create_app(context)
    app.mount('/',StaticFiles(directory=dist,html=True),name='isolated-test-ui')
    uvicorn.run(app,host='127.0.0.1',port=args.port,access_log=False)
    return 0


if __name__=='__main__':raise SystemExit(main())
