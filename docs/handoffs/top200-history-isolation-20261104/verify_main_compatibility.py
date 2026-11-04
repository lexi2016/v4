"""Read deployed dependencies; test only the candidate Top200 continuation."""
import argparse
import hashlib
import importlib.util
from pathlib import Path
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--main-root', type=Path, required=True)
parser.add_argument('--basetemp', type=Path, required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parents[3]
main = args.main_root.resolve(strict=True)
assert hashlib.sha256((main / 'ops/research_panel_top200.py').read_bytes()).hexdigest() == '23cef60699d84a1755f24a802edc1a615c5e159df060873013065c882b41771f'
sys.path.insert(0, str(main))
import ops
from ops import research_panel_daily_product, sync_stock_history_completion, a_share_daily_sync
assert callable(sync_stock_history_completion._inherited_owner_duplicate)
assert callable(a_share_daily_sync._daily_source_policy_additions)
for module in (research_panel_daily_product, sync_stock_history_completion, a_share_daily_sync):
    assert Path(module.__file__).is_relative_to(main), module.__file__
    print('LIVE_DEPENDENCY', module.__file__)
spec = importlib.util.spec_from_file_location('ops.research_panel_top200', root / 'ops/research_panel_top200.py')
candidate = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = candidate
spec.loader.exec_module(candidate)
ops.research_panel_top200 = candidate
import pytest
args.basetemp.parent.mkdir(parents=True, exist_ok=True)
raise SystemExit(pytest.main(['-q', str(root / 'tests/test_daily_top200_completion.py'), '--basetemp=' + str(args.basetemp.resolve())]))
