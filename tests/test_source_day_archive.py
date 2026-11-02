import copy

import pytest

from infrastructure.research_workbench_host import FLAGS, ResearchWorkbenchHost


@pytest.fixture
def case():
    manifest={'path':'/source/manifest.json','sha256':'a'*64}
    product={'data_date':'20261030','source_generation':'b'*64,'source_identity':{'input_sha256':'c'*64},
             'manifest':manifest,'rows':[{'symbol':'000035.SZ','display_name':'中国天楹'},
                {'symbol':'000528.SZ','display_name':'柳    工'},{'symbol':'689009.SH','display_name':'九号公司'},
                {'symbol':'000001.SZ','display_name':'平安银行'},{'symbol':'000002.SZ','display_name':'万科'}]}
    def row(symbol,name,price,change,amount,**extra):
        return {'symbol':symbol,'name':name,'directory_name':name,'identity_status':'EXACT_CODE_NAME','source_date':'2026-10-30',
                'source_time':'UNKNOWN_DATE_ONLY','price_status':'VALID','close':price,'change_pct':change,'amount_cny':amount,**extra}
    archive={'schema':'V4_A_SHARE_TOP200_V1','data_date':'20261030','source_generation':'b'*64,'input_sha256':'c'*64,
        'numeric_manifest':manifest,'top200':[],'top200_count':0,'historical_PIT':False,**FLAGS,
        'coverage':[row('000035.SZ','中国天楹',4.39,-2.44,152743652.86),
            row('000528.SZ','柳 工',7.76,0,193071479.48),row('000001.SZ','平安银行',10,0,0),
            row('000002.SZ','万科',10,1,None)]}
    host=ResearchWorkbenchHost.__new__(ResearchWorkbenchHost)
    host._is_skill_date=lambda _:False
    host._view=lambda *_:product
    host._index=lambda:{'top200':{'20261030':{'path':'/source/top200.json','sha256':'d'*64}}}
    host.source=type('Source',(),{'_a_product_reference':lambda self,ref:archive})()
    return host,product,archive


def test_archive_projection_keeps_source_identity_gaps_and_zero_values(case):
    host,_,archive=case
    archive['coverage'][1]['identity_status']='NAME_CONFLICT'
    result=host.top200('2026-10-30');assert 'coverage' not in result
    view=result['source_day_archive'];rows={r['symbol']:r for r in view['rows']}
    assert view['source_date']=='2026-10-30' and view['source_time']=='UNKNOWN_DATE_ONLY'
    assert view['historical_PIT'] is False and len(rows)==5
    assert (rows['000035.SZ']['price'],rows['000035.SZ']['change_percent_source'],rows['000035.SZ']['amount_source'])==(4.39,-2.44,152743652.86)
    assert rows['000528.SZ']['reason']=='ARCHIVE_IDENTITY_CONFLICT' and rows['000528.SZ']['archive_name']=='柳 工'
    assert rows['689009.SH']['reason']=='ARCHIVE_COVERAGE_MISSING' and rows['689009.SH']['price'] is None
    assert rows['000001.SZ']['status']=='READY' and rows['000001.SZ']['change_percent_source']==0 and rows['000001.SZ']['amount_source']==0
    assert rows['000002.SZ']['status']=='PARTIAL' and rows['000002.SZ']['amount_source'] is None


@pytest.mark.parametrize('field,altered',[('data_date','20261102'),('source_generation','e'*64),
    ('input_sha256','f'*64),('numeric_manifest',{'path':'/other','sha256':'a'*64})])
def test_archive_rejects_product_identity_mismatch(case,field,altered):
    host,_,archive=case;archive[field]=altered
    with pytest.raises(ValueError,match='WORKBENCH_TOP200_SOURCE_CONFLICT'):host.top200('2026-10-30')


def test_archive_rejects_candidate_name_wrong_date_duplicate_and_untrusted_flags(case):
    host,product,archive=case
    product['rows'][0]['display_name']='不同名称';rows=host.top200('2026-10-30')['source_day_archive']['rows']
    assert rows[0]['reason']=='CANDIDATE_NAME_CONFLICT' and rows[0]['price'] is None
    product['rows'][0]['display_name']='中国天楹';archive['coverage'][0]['source_date']='2026-11-02'
    assert host.top200('2026-10-30')['source_day_archive']['rows'][0]['reason']=='ARCHIVE_DATE_CONFLICT'
    archive['coverage'][0]['source_date']='2026-10-30';archive['coverage'].append(copy.deepcopy(archive['coverage'][0]))
    assert host.top200('2026-10-30')['source_day_archive']['rows'][0]['reason']=='ARCHIVE_DUPLICATE_IDENTITY'
    archive['RESEARCH_ONLY']=False
    assert all(r['reason']=='ARCHIVE_SOURCE_FLAGS_UNCONFIRMED' for r in host.top200('2026-10-30')['source_day_archive']['rows'])


def test_archive_invalid_metric_values_remain_missing_without_changing_other_fields(case):
    host,_,archive=case
    archive['coverage'][0].update(close=float('nan'),change_pct=10**400,amount_cny=True)
    row=host.top200('2026-10-30')['source_day_archive']['rows'][0]
    assert row['status']=='PARTIAL'
    assert row['price'] is None and row['change_percent_source'] is None and row['amount_source'] is None
