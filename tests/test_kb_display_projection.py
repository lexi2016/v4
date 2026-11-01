import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from ops.research_panel_daily_product import _kb_display_stock_worker
from ops.research_panel_qfq import sha


def test_scoped_display_physically_removes_only_policy_columns(tmp_path):
    root=Path(__file__).resolve().parents[1]
    policy=json.loads((root/'contracts/a_share_top200_display_projection_v1.json').read_text())
    excluded=policy['excluded_from_display_projection']
    backtest_removed=[x for x in excluded if x.startswith('user_v1_')]
    assert len(excluded)==25 and len(backtest_removed)==8
    refs={}
    for role,count,names in (('selector',393,excluded),('backtest',245,backtest_removed)):
        columns={'ts_code':['600809.SH'],'trade_date':[20261030],'kb_yidong':[True],
                 'kb_yidong_resumed':[None],'kb_hold_volume_ok_reason':['RULE_NOT_QUANTIFIED']}
        columns.update({name:[False] for name in names})
        columns.update({f'filler_{i}':[i] for i in range(count-len(columns))})
        path=tmp_path/(role+'_full.parquet');pq.write_table(pa.table(columns),path)
        refs[role]={'path':str(path),'sha256':sha(path),'bytes':path.stat().st_size}
    stock={'symbol':'600809.SH','rows':1,'first_date':20261030,'last_date':20261030,'assets':refs}
    result=_kb_display_stock_worker((stock,excluded,{'policy':'test'},str(tmp_path/'projected')))
    for role,expected in (('selector',368),('backtest',237)):
        r=result['display_roles'][role];table=pq.read_table(r['artifact']['path'])
        assert len(table.column_names)==expected
        assert not set(table.column_names)&set(excluded)
        assert table['kb_hold_volume_ok_reason'][0].as_py()=='RULE_NOT_QUANTIFIED'
        assert table['kb_yidong_resumed'][0].as_py() is None
        assert r['retained_values_equal'] and refs[role]['sha256']==sha(Path(refs[role]['path']))
