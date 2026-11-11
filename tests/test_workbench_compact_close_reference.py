"""Regression for the actual WorkbenchHost._view compact input contract."""
import copy
import json
from pathlib import Path

import pytest

from infrastructure.research_workbench_quote_reference import SourceCloseReferences
from test_daily_completion_closure import DAY, FLAGS, GEN, INPUT, product_fixture, write


def compact_fixture(tmp_path):
    product,paths=product_fixture(tmp_path,overlay=True)
    first=json.loads(Path(paths['row']['path']).read_text())
    for row in product['rows'][1:]:
        detail=copy.deepcopy(first);detail['symbol']=row['symbol']
        product['row_refs'][row['symbol']]=write(paths['root']/(row['symbol']+'.json'),detail)
    full={**product,'schema_version':'v4.a_share.daily_product.v1','source_config':{'sha256':'d'*64},
          'processed_count':3,'source_universe_count':3,'status':'PARTIAL_WITH_ROWS','sample_only':False,**FLAGS}
    full.pop('manifest',None)
    # The BJ symbol represents an independent same-source model display, not
    # membership in the original two-symbol four-group candidate list.
    full['rows']=full['rows'][:2]
    artifact=write(paths['root']/'numeric_product.json',full)
    manifest=dict(schema_version='v4.a_share.daily_product_manifest.v1',data_date=DAY,
        source_generation=GEN,input_sha256=INPUT,snapshot=full['source_identity']['snapshot'],
        artifact=artifact,sample_only=False,processed_count=3,**FLAGS)
    manifest_ref=write(paths['root']/'numeric_manifest.json',manifest)
    source={**full,'manifest':manifest_ref,'artifact':artifact}
    fields=('data_date','source_generation','source_identity','source_config','manifest','artifact',
            'processed_count','source_universe_count','status','rows')
    compact={key:source[key]for key in fields}
    assert 'row_refs'not in compact
    return compact,paths,full,manifest


def test_actual_compact_numeric_view_resolves_declared_artifact_not_current(tmp_path):
    compact,_,_,_=compact_fixture(tmp_path)
    result=SourceCloseReferences().read(compact)
    assert result['status']=='BOUND_SOURCE_CLOSE' and result['scope_count']==result['available_count']==2
    assert result['rows']['600000.SH']['price']==20.
    assert result['source_date']=='2026-11-11' and result['source_asof']is None


def test_compact_numeric_view_retains_same_source_model_scope(tmp_path):
    compact,_,_,_=compact_fixture(tmp_path);compact['rows']=[{'symbol':'920001.BJ'}]
    result=SourceCloseReferences().read(compact)
    assert result['scope_count']==1 and result['rows']['920001.BJ']['price']==30.


@pytest.mark.parametrize('kind',['manifest_sha','artifact_sha','identity','scope','flags','sample'])
def test_compact_numeric_view_does_not_relax_signed_source_contract(tmp_path,kind):
    compact,paths,full,manifest=compact_fixture(tmp_path)
    if kind=='manifest_sha':Path(compact['manifest']['path']).write_text('{}')
    elif kind=='artifact_sha':Path(compact['artifact']['path']).write_text('{}')
    elif kind=='scope':compact['rows'].append({'symbol':'600999.SH'})
    else:
        if kind=='identity':full['source_identity']={**full['source_identity'],'input_sha256':'f'*64}
        elif kind=='flags':full['production_allowed']=True
        else:full['sample_only']=True
        compact['artifact']=write(Path(compact['artifact']['path']),full)
        manifest['artifact']=compact['artifact'];compact['manifest']=write(Path(compact['manifest']['path']),manifest)
    with pytest.raises(ValueError):SourceCloseReferences().read(compact)
