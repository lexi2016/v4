"""A new classification is effective only with a separate exact-tuple review."""
import copy,json
import pytest
from test_us_gap_diagnostics import case,loaded
from test_integration import write,context
from v4.manager_workbench.inputs import source_bindings as b
from v4.manager_workbench.inputs.validation import owner_digest

KEYS=('us_symbol','hk_symbol','relationship_type','direction')
VERSION='US_RESEARCH_PRIORITY_REVIEW_V1_20261013'

def packet(tmp_path):
 cfg,old,old_review=case(tmp_path)
 oldrel='v4/manager_research/us_mapping_relation_evidence_20261011.json'
 oldrev='v4/manager_research/us_mapping_relation_evidence_review_20261011.json'
 oldsha=write(cfg.relation_root,oldrel,old);revsha=write(cfg.relation_root,oldrev,old_review)
 cfg.relation_evidence_relative='v4/manager_workbench/research_data/new-evidence.json'
 cfg.relation_review_relative='v4/manager_workbench/research_data/new-review.json'
 e=copy.deepcopy(old);card=e['relations'][0];stamp='2026-10-12T09:00:00+08:00';priority='WATCH';reason='历史合作可作条件观察，无当期收入或价格因果证据。'
 a=dict(classification_version=VERSION,classification_kind='NEW_RESEARCH_CLASSIFICATION_NOT_RECOVERED_OLD_FIELD',
  analyst_identity='writer-fixture',classified_at=stamp,research_priority=priority,reason=reason,counter_evidence=['历史材料不能证明当前合同'],
  original_relation_sha256=owner_digest(old['relations'][0]),original_evidence_raw_sha256=oldsha,original_review_raw_sha256=revsha,
  original_tuple={k:card.get(k) for k in KEYS},not_a_quote_based_rank=True,strict_selection_supported=False)
 card.update(available_at=stamp,original_available_at=old['relations'][0]['available_at'],research_priority=priority,research_priority_reason=reason,priority_assessment=a)
 e.update(schema_version='v4.manager_workbench.us_mapping_relation_evidence.v3',classification_version=VERSION,classified_at=stamp,
  inherited_evidence=dict(relative=oldrel,raw_sha256=oldsha,artifact_sha256=old['artifact_sha256'],review_relative=oldrev,review_raw_sha256=revsha))
 review=copy.deepcopy(old_review);review.update(reviewed_at='2026-10-12T10:00:00+08:00',reviewed_priority_assessments=[{**a['original_tuple'],
  'assessment_sha256':owner_digest(a),'research_priority':priority,'reason':reason,'counter_evidence':a['counter_evidence']}])
 save(cfg,e,review);return cfg,e,review

def save(cfg,e,v):
 e['artifact_sha256']=owner_digest({k:x for k,x in e.items() if k!='artifact_sha256'});sha=write(cfg.relation_root,cfg.relation_evidence_relative,e)
 v.update(evidence_file_sha256=sha,declared_artifact_sha256=e['artifact_sha256'],recomputed_artifact_sha256=e['artifact_sha256']);write(cfg.relation_root,cfg.relation_review_relative,v)

def test_new_priority_provenance_and_conditions_are_preserved(tmp_path):
 cfg,e,v=packet(tmp_path);batch,result=loaded(cfg);r=next(r for r in result['rows'] if r['us_symbol']=='NVDA')
 assert r['decision']=='CONDITIONAL_WATCH' and r['conditions']==['RELATION_NOT_A_STRICT_SELECTION_RULE']
 assert r['research_priority_reason']==e['relations'][0]['research_priority_reason']
 assert r['priority_assessment']==e['relations'][0]['priority_assessment'] and r['research_basis']=='Original verified relationship'
 assert len(batch.records)==33 and len([r for r in result['rows'] if r['reason']=='US_ETF_THEME_PROXY_ONLY'])==1
 pin=batch.context.scope_refs['owner_bindings']['us_mapping'];assert len(pin['checked_files'])==4
 # Mutating an original after job submission also invalidates the immutable input binding.
 (cfg.relation_root/e['inherited_evidence']['relative']).write_text('{}')
 from v4.manager_workbench.inputs.native import NativeAdapters
 with pytest.raises(ValueError,match='OWNER_BOUND_BYTES_CHANGED'):NativeAdapters(cfg).us_mapping(batch.context)

@pytest.mark.parametrize('bad',['digest','priority','reason','counter','missing','duplicate','newtuple','samewriter','late','early','original','sources','unknownversion','legacy_schema'])
def test_priority_review_rejects_changed_identity_fact_or_time(tmp_path,bad):
 cfg,e,v=packet(tmp_path);card=e['relations'][0];a=card['priority_assessment'];r=v['reviewed_priority_assessments'][0]
 if bad=='digest':r['assessment_sha256']='0'*64
 elif bad=='priority':r['research_priority']='PRIORITY'
 elif bad=='reason':r['reason']='Unreviewed claim'
 elif bad=='counter':r['counter_evidence']=[]
 elif bad=='missing':v['reviewed_priority_assessments']=[]
 elif bad=='duplicate':v['reviewed_priority_assessments']*=2
 elif bad=='newtuple':card['hk_symbol']='HK.00002'
 elif bad=='samewriter':v['reviewer_identity']=a['analyst_identity']
 elif bad=='late':v['reviewed_at']='2026-10-11T10:00:00+08:00'
 elif bad=='early':a['classified_at']='2026-10-10T09:00:00+08:00';r['assessment_sha256']=owner_digest(a)
 elif bad=='original':a['original_relation_sha256']='0'*64;r['assessment_sha256']=owner_digest(a)
 elif bad=='sources':card['reason']='Altered underlying fact'
 elif bad=='unknownversion':e['classification_version']='FUTURE_UNKNOWN'
 elif bad=='legacy_schema':e['schema_version']='v4.manager_research.us_mapping_relation_evidence.v2'
 save(cfg,e,v);ctx=context();ctx.source_sessions['us']='20261012'
 with pytest.raises(ValueError):b.us_mapping(cfg,ctx)

@pytest.mark.parametrize('change,member,expected',[(0,True,'NOT_SELECTED'),(-1,True,'NOT_SELECTED'),(1,False,'UNASSESSED'),(1,True,'CONDITIONAL_WATCH')])
def test_new_priority_never_overrides_positive_change_or_membership(tmp_path,change,member,expected):
 cfg,e,v=packet(tmp_path);batch,_=loaded(cfg);raw=batch.model_dump(mode='json');item=next(r for r in raw['records'] if r['us_symbol']=='NVDA');item['quote']['change_pct']=change;item['relations'][0]['membership']['eligible']=member
 from v4.manager_workbench.engines.us_mapping import run_us_mapping
 r=next(r for r in run_us_mapping(raw['context'],raw)['rows'] if r['us_symbol']=='NVDA');assert r['decision']==expected
 assert all(r['decision']!='SELECTED' for r in run_us_mapping(raw['context'],raw)['rows'])
