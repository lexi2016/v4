import importlib.abc, importlib.util, os, sys, uuid
from pathlib import Path
import pytest
w=Path("/Users/lexi/.codex/worktrees/stage-failure-snapshots-20261023/v4_app")
b=Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/hk-close-ready-status-20261021-r1/app")
os.environ["AUCTION_SHARED_PACKAGE_ROOT"]="/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/hk-tdx-conflict-repair-shared-20261015-r4/app/upstreams/v3_shared_data"
class Overlay(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname=="ops.run_hkconnect_0915_0920_capture":return importlib.util.spec_from_file_location(fullname,w/"ops/run_hkconnect_0915_0920_capture.py")
sys.meta_path.insert(0,Overlay());sys.path.insert(0,str(b))
temp=Path(__file__).parent/"pytest-tmp";temp.mkdir(exist_ok=True)
args=sys.argv[1:] or [str(w/"tests/test_hk_auction_snapshot_on_failure.py"),"-q"]
raise SystemExit(pytest.main(args+["--basetemp",str(temp/uuid.uuid4().hex),"-p","no:cacheprovider"]))
