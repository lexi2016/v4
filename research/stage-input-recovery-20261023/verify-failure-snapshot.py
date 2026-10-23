import importlib.abc, importlib.util, sys, uuid
from pathlib import Path
import pytest
w=Path("/Users/lexi/.codex/worktrees/stage-failure-snapshots-20261023/v4_app")
b=Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/stage-input-recovery-20261023-stage-r1/app")
paths=["stage_center/runner.py","stage_center/_runner_parts/configuration.py","stage_center/_runner_parts/runner_receipts.py","stage_center/_runner_parts/slot_execution.py","stage_center/hk_stage8/snapshot.py","stage_center/hk_stage8/precapture.py","ops/_run_stage_center_nodes_parts/node_entry.py"]
mapping={p[:-3].replace("/","."):w/p for p in paths}
class Overlay(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname in mapping:return importlib.util.spec_from_file_location(fullname,mapping[fullname])
sys.meta_path.insert(0,Overlay())
sys.path.insert(0,str(b))
(Path(__file__).parent / "pytest-tmp").mkdir(exist_ok=True)
args = sys.argv[1:] or [str(w/"tests/test_hk_snapshot_on_stage_failure.py"), "-q"]
args += ["--basetemp", str(Path(__file__).parent / "pytest-tmp" / uuid.uuid4().hex), "-p", "no:cacheprovider"]
raise SystemExit(pytest.main(args))
