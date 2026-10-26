"""Use the existing official helper, with only the receipt directory rebound."""
from pathlib import Path
import importlib.util,json,sys
B=Path(__file__).resolve().parent
p=B.parent/'a_share_local_panel_completion_20261024/register_stage_r17.py'
s=importlib.util.spec_from_file_location('futu76_existing_registry',p)
m=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.HERE=B
if __name__=='__main__':
 result=m.append(B/'EXECUTION_CONTRACT.json',sys.argv[1],sys.argv[2],artifacts=[Path(p) for p in sys.argv[3:]])
 print(json.dumps(result,sort_keys=True))
