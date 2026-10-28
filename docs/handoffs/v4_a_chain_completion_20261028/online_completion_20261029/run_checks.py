"""Use installed owning dependencies with only the named candidate modules."""
from pathlib import Path
import importlib.util,sys

OWNED=Path(__file__).resolve().parent
API_APP=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/daily-r19-profile-20261029-r1-api/app')
STAGE_APP=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/v4-retirement-20261028-stage/app')
mode=sys.argv[1]
assert mode in ('api','native')
sys.path.insert(0,str(API_APP if mode=='api' else STAGE_APP))
if mode=='api':
    import apps.api.v4_api
    name='apps.api.v4_api.review_router'
    path=OWNED/'sources/api/apps/api/v4_api/review_router.py'
else:
    import infrastructure
    name='infrastructure.stage_quote_provider'
    path=OWNED/'sources/stage/infrastructure/stage_quote_provider.py'
spec=importlib.util.spec_from_file_location(name,path)
module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
setattr(sys.modules[name.rpartition('.')[0]],name.rpartition('.')[2],module)
import pytest
(OWNED/'tmp').mkdir(exist_ok=True)
if mode=='api':args=[str(OWNED/'tests/test_a_close_root.py')]
else:
    # The approved prewarm AST is identical. Only two owning-dependency smoke
    # cases run here; the earlier independent11/11 PASS remains reused.
    args=[str(OWNED.parents[3]/'tests/test_a925_tdx_prewarm.py'),'-k','dead_first_eight or future_primary']
raise SystemExit(pytest.main([*args,'-q','-p','no:cacheprovider','--basetemp',str(OWNED/'tmp'/mode),*sys.argv[2:]]))
