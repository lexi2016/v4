"""Diagnostics retain original source evidence; never create an eligible tuple."""
import copy,json
import pytest
from test_integration import config,context,us,monthly,write
from v4.manager_workbench.inputs import source_bindings as bindings
from v4.manager_workbench.inputs.native import NativeAdapters
from v4.manager_workbench.engines.us_mapping import run_us_mapping
from v4.manager_workbench.contracts import Lane
from v4.manager_workbench.inputs.validation import owner_digest

def case(tmp_path):
 cfg=config(tmp_path);us(cfg);monthly(cfg)
 e=json.loads((cfg.relation_root/cfg.relation_evidence_relative).read_bytes())
 e['relations'][0].update(published_at='2025-01-01T00:00:00Z',reason='Original verified relationship',limitations=['Original historical-context limit'])
 a=dict(us_symbol='MU',candidate_hk_code='00001',candidate_hk_symbol='HK.00001',status='ASSESSED_WITH_GAPS',conclusion='CANNOT_CONFIRM',available_at='2026-10-11T09:00:00+08:00',reason='Original HTTP body cannot confirm',limitations=['Not a current verified issuer relationship'],sources=[])
 e['symbol_assessments']=[a];e['artifact_sha256']=owner_digest({k:v for k,v in e.items() if k!='artifact_sha256'});esha=write(cfg.relation_root,cfg.relation_evidence_relative,e)
 review=json.loads((cfg.relation_root/cfg.relation_review_relative).read_bytes());review.update(evidence_file_sha256=esha,declared_artifact_sha256=e['artifact_sha256'],recomputed_artifact_sha256=e['artifact_sha256'],reviewed_symbol_assessments=[dict(us_symbol='MU',candidate_hk_code='00001',status='ASSESSED_WITH_GAPS',conclusion='CANNOT_CONFIRM',assessment_sha256=owner_digest(a))]);write(cfg.relation_root,cfg.relation_review_relative,review)
 rel='research/peripherals/20261012/external_finance.json';payload=dict(market_snapshot=dict(capture_session_date='20261012',captured_at='2026-10-13T05:00:00+08:00',quotes=[dict(symbol=s,change_pct=1) for s in bindings.US_SYMBOLS],rows=[dict(mapping_type='etf_proxy',label='Original ETF theme',proxy_symbols=['ARKX'],status='READY')]))
 qsha=write(cfg.us_root,rel,payload);write(cfg.us_root,'research/peripherals/manifest.json',{rel:qsha});write(cfg.us_root,'receipts/research/peripherals/20261012/external_finance.json',{'payload_sha256':qsha})
 return cfg,e,review

def loaded(cfg):
 adapter=NativeAdapters(cfg);c=adapter.prepare_context(context());b=adapter.load(Lane.US_MAPPING,c);return b,run_us_mapping(b.context.model_dump(mode='json'),b.model_dump(mode='json'))

def test_original_assessment_etf_and_missing_priority_never_promoted(tmp_path):
 cfg,e,v=case(tmp_path);b,result=loaded(cfg);rows={r['us_symbol']:r for r in result['rows']}
 assert len(b.records)==33
 mu=rows['MU'];assert mu['decision']=='UNASSESSED' and mu['symbol'] is None and mu['reason']=='US_REVIEWED_ASSESSMENT_WITH_GAPS'
 assert mu['reviewed_assessments'][0]['original']==e['symbol_assessments'][0]
 assert len(mu['reviewed_assessments'][0]['source_refs'])==2 and 'relations' not in mu['reviewed_assessments'][0]
 ark=rows['ARKX'];assert ark['decision']=='UNASSESSED' and ark['symbol'] is None and ark['reason']=='US_ETF_THEME_PROXY_ONLY'
 assert ark['proxy_metadata'][0]['mapping_type']=='etf_proxy' and ark['proxy_metadata'][0]['label']=='Original ETF theme'
 nvda=rows['NVDA'];assert nvda['decision']=='UNASSESSED' and nvda['reason']=='US_RELATION_PRIORITY_NOT_REVIEWED' and 'AUDITED_RESEARCH_PRIORITY_UNAVAILABLE' in nvda['diagnostic_gaps']
 assert nvda['research_basis']=='Original verified relationship' and nvda['relation_limitations']==['Original historical-context limit']

@pytest.mark.parametrize('bad',['digest','symbol','status','conclusion','candidate','late','rawsha','reviewowner'])
def test_assessment_identity_or_time_failclosed(tmp_path,bad):
 cfg,e,review=case(tmp_path);a=review['reviewed_symbol_assessments'][0]
 if bad=='digest':a['assessment_sha256']='0'*64
 elif bad=='symbol':a['us_symbol']='WDC'
 elif bad=='status':a['status']='REVIEWED'
 elif bad=='conclusion':a['conclusion']='VERIFIED'
 elif bad=='candidate':a['candidate_hk_code']='00002'
 elif bad=='late':review['reviewed_at']='2026-10-11T08:00:00+08:00'
 elif bad=='rawsha':review['evidence_file_sha256']='0'*64
 elif bad=='reviewowner':review['reviewer_identity']=''
 write(cfg.relation_root,cfg.relation_review_relative,review)
 c=context();c.source_sessions['us']='20261012'
 with pytest.raises(ValueError):bindings.us_mapping(cfg,c)

def test_direct_diagnostic_tamper_and_ready_never_make_relation(tmp_path):
 cfg,e,v=case(tmp_path);b,_=loaded(cfg);raw=b.model_dump(mode='json');mu=next(r for r in raw['records'] if r['us_symbol']=='MU');mu['reviewed_assessments'][0]['original']['reason']='Forged newer fact'
 ark=next(r for r in raw['records'] if r['us_symbol']=='ARKX');ark['proxy_metadata'][0]['source_sha256']='0'*64
 rows={r['us_symbol']:r for r in run_us_mapping(raw['context'],raw)['rows']}
 for s in ['MU','ARKX']:assert rows[s]['decision']=='UNASSESSED' and rows[s]['symbol'] is None and rows[s]['reason']=='US_REVIEWED_RELATION_ABSENT'

def test_connect_false_is_retained_as_additional_priority_blocker(tmp_path):
 cfg,e,v=case(tmp_path);b,_=loaded(cfg);raw=b.model_dump(mode='json');nvda=next(r for r in raw['records'] if r['us_symbol']=='NVDA');nvda['relations'][0]['membership']['eligible']=False
 row=next(r for r in run_us_mapping(raw['context'],raw)['rows'] if r['us_symbol']=='NVDA')
 assert row['decision']=='UNASSESSED' and set(row['diagnostic_gaps'])=={'AUDITED_RESEARCH_PRIORITY_UNAVAILABLE','TARGET_NOT_IN_CURRENT_CONNECT_MEMBERSHIP'}

def test_original_basket_proxy_type_is_retained_without_inferred_relation(tmp_path):
 cfg,e,v=case(tmp_path)
 rel='research/peripherals/20261012/external_finance.json';payload=json.loads((cfg.us_root/rel).read_bytes())
 payload['market_snapshot']['rows'].extend([
  dict(mapping_type='etf_basket_proxy',label='消费',proxy_symbols=['XLY','XLP'],status='READY'),
  dict(mapping_type='unverified_theme',label='Unknown theme',proxy_symbols=['TAN'],status='READY')])
 qsha=write(cfg.us_root,rel,payload);write(cfg.us_root,'research/peripherals/manifest.json',{rel:qsha});write(cfg.us_root,'receipts/research/peripherals/20261012/external_finance.json',{'payload_sha256':qsha})
 b,result=loaded(cfg);rows={r['us_symbol']:r for r in result['rows']}
 for symbol in ['XLP','XLY']:
  r=rows[symbol];assert r['decision']=='UNASSESSED' and r['symbol'] is None and r['reason']=='US_ETF_THEME_PROXY_ONLY'
  assert r['proxy_metadata'][0]['mapping_type']=='etf_basket_proxy' and r['proxy_metadata'][0]['source_sha256']==qsha
 assert rows['TAN']['reason']=='US_REVIEWED_RELATION_ABSENT' and not rows['TAN']['proxy_metadata']
