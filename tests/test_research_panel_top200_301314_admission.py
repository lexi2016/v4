import copy
import pytest
from ops import repair_301314_admission as repair
from ops.research_panel_top200 import merge_exact_301314_row


def inputs():
    old=dict(symbol=repair.SYMBOL,data_date='20261110',groups='',pending_groups='original',evaluation={'groups':{g:{'status':'UNKNOWN'}for g in repair.owner.GROUPS}})
    row=copy.deepcopy(old);row['pending_groups']='';row['groups']='nav_smallk'
    row['evaluation']['groups']={g:{'status':'TRUE'if g=='nav_smallk'else'FALSE'}for g in repair.owner.GROUPS}
    refs={repair.SYMBOL:{'path':'old','sha256':'old'},**{str(i):{'path':str(i),'sha256':str(i)}for i in range(5807)}}
    product=dict(data_date='20261110',processed_count=5808,row_refs=refs,rows=[],unique_count=0,unknown_count=5808,
        three_value_counts={g:{'UNKNOWN':5808}for g in repair.owner.GROUPS},group_counts={g:0 for g in repair.owner.GROUPS})
    return product,old,row


def test_only_target_membership_delta_and_other5807_refs_preserved():
    product,old,row=inputs();before=copy.deepcopy(product);ref={'path':'new','sha256':'new'}
    merged=merge_exact_301314_row(product,old,row,ref)
    assert merged['unique_count']==1 and merged['rows'][0]['symbol']==repair.SYMBOL
    assert merged['group_counts']['nav_smallk']==1 and merged['unknown_count']==5807
    assert {k:v for k,v in merged['row_refs'].items()if k!=repair.SYMBOL}=={k:v for k,v in product['row_refs'].items()if k!=repair.SYMBOL}
    assert product==before


def test_unselected_target_preserves_membership_and_legitimate_formula_unknown():
    product,old,row=inputs();row['groups']='';row['pending_groups']='original';row['evaluation']['groups']['original']['status']='UNKNOWN';row['evaluation']['groups']['nav_smallk']['status']='FALSE'
    merged=merge_exact_301314_row(product,old,row,{'path':'new','sha256':'new'})
    assert merged['rows']==[]and merged['unique_count']==0 and merged['unknown_count']==5808
    assert merged['three_value_counts']['original']['UNKNOWN']==5808


def test_other_symbol_or_incomplete_universe_rejected():
    product,old,row=inputs();row['symbol']='002731.SZ'
    with pytest.raises(ValueError,match='AGGREGATE_SCOPE_CONFLICT'):merge_exact_301314_row(product,old,row,{})
