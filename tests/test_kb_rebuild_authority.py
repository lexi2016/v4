import ast
from pathlib import Path

import pandas as pd

from ops.kb_rebuild_authority import project_rebuild
from ops.kb_signal_authority import DailyData, calculate_ma


def test_fixed_rebuild_matches_pinned_source_and_keeps_warmup_unknown():
    path=Path('/Users/lexi/.claude/skills/zettaranc-perspective/modules/indicators/price_patterns/complex_patterns.py')
    tree=ast.parse(path.read_text());fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='detect_zaihou_chongjian')
    env={'DailyData':DailyData,'calculate_ma':calculate_ma};exec(compile(ast.Module(body=[fn],type_ignores=[]),str(path),'exec'),env)
    dates=pd.bdate_range('2025-01-01',periods=160).strftime('%Y%m%d').astype(int)
    close=[10+i*.001 for i in range(160)];volume=[100.]*160;pct=[0.]*160
    volume[151]=300.;pct[151]=6.;volume[159]=30.
    frame=pd.DataFrame({'trade_date':dates,'close':close,'volume':volume,'pct_chg':pct})
    observed=project_rebuild(frame);assert observed[122] is None
    bars=[DailyData('600000.SH',str(d),c,c,c,c,v,0,p,1) for d,c,v,p in zip(dates,close,volume,pct)]
    for i in range(123,len(bars)):
        assert observed[i] == env['detect_zaihou_chongjian'](bars[:i+1])['is_rebuild']
    assert observed[-1] is True
