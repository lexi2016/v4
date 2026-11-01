"""Bind existing authority results, the chart and company producers for 300206."""
from pathlib import Path
import gzip
import json
import pyarrow as pa
import pyarrow.parquet as pq
from ops import research_panel_qfq as q
from ops import render_original_formula_projection as renderer
from ops.junda_feedback_candidate import immutable,write_json,same
from ops.bootstrap_stock_event_history import build_retained_single_stock,ref
from ops.research_panel_daily_product import materialize_bound_single_company

r=Path(__file__).resolve().parent;repo=Path(q.__file__).resolve().parents[1];parent=r.parent
interim=json.loads((r/'EDAN_PREFIX_INTERIM_R1.json').read_text())
gate_ref=ref(r/'SOURCE_GATE_EDAN_R1.json');gate=json.loads(q._source(gate_ref,owner='EDAN source gate').read_text())
assert gate['status']=='PASS_RELOCATED_SOURCE_GATE' and gate['canonical_input_sha256']==interim['identity']['input_sha256']
for name,item in gate['source_code_refs'].items():assert q.sha(repo/name)==item['sha256']
template_path=parent/'n_hold_score_integration_20261102_r1/301048_SZ_N_BINDING_9bf8022c1206fea7.json'
binding=json.loads(template_path.read_text());assert binding['source_generation']==interim['source_generation']
view_data=json.loads(gzip.decompress((r/'EDAN_VIEW_ROWS_R1.json.gz').read_bytes()))
fields,inventory,rows=view_data['fields'],view_data['field_inventory'],view_data['rows'];assert len(rows)==3767
admission_ref=ref(r/'EDAN_SOURCE_ADMISSION_R1.json');admission=json.loads(q._source(admission_ref,owner='EDAN admission').read_text())
assert admission['status']=='CURRENT_PRODUCER_ACCEPTED_FOR_REQUESTED_RESEARCH'
score=immutable(r/('a_share_kb_hold_score_v1_'+q.sha(repo/'contracts/a_share_kb_hold_score_v1.json')[:16]+'.json'),(repo/'contracts/a_share_kb_hold_score_v1.json').read_bytes())
supplemental=immutable(r/'a_share_kb_supplemental_signals_v1.json',(repo/'contracts/a_share_kb_supplemental_signals_v1.json').read_bytes())
action=immutable(r/('a_share_kb_action_v1_'+q.sha(repo/'contracts/a_share_kb_action_v1.json')[:16]+'.json'),(repo/'contracts/a_share_kb_action_v1.json').read_bytes())
yidong=immutable(r/('a_share_kb_yidong_v1_'+q.sha(repo/'contracts/a_share_kb_yidong_v1.json')[:16]+'.json'),(repo/'contracts/a_share_kb_yidong_v1.json').read_bytes())
policy=immutable(r/('a_share_single_display_projection_v1_'+q.sha(repo/'contracts/a_share_single_display_projection_v1.json')[:16]+'.json'),(repo/'contracts/a_share_single_display_projection_v1.json').read_bytes())
gap_contract=immutable(r/('a_share_kb_confirmed_gap_v1_'+q.sha(repo/'contracts/a_share_kb_confirmed_gap_v1.json')[:16]+'.json'),(repo/'contracts/a_share_kb_confirmed_gap_v1.json').read_bytes())
n_contract=immutable(r/('a_share_kb_n_structure_v1_'+q.sha(repo/'contracts/a_share_kb_n_structure_v1.json')[:16]+'.json'),(repo/'contracts/a_share_kb_n_structure_v1.json').read_bytes())
source_names=set(binding['candidate_identity']['source_sha256'])|set(gate['source_code_refs'])
sources={name:q.sha(repo/name) for name in sorted(source_names)}
f10_receipt=json.loads((r/'F10_SINGLE_COMPLETION_R1.json').read_text())['receipt']
completion=json.loads(q._source(f10_receipt,owner='EDAN F10 receipt').read_text())
index=json.loads(q._source(completion['checkpoint'],owner='EDAN F10 checkpoint').read_text())
f10_ref=index['items']['300206.SZ'];f10=json.loads(q._source(f10_ref,owner='EDAN F10').read_text())
assert f10['symbol']=='300206.SZ' and f10['status']=='OBSERVED' and f10['historical_PIT'] is False
concepts='、'.join(x['name'] for x in f10['concepts']);concept_count=len(f10['concepts'])
identity=dict(binding['candidate_identity'])
for k in ('action_prior_candidate_sha256','confirmed_gap_prior_candidate_sha256','display_prior_candidate_sha256',
          'n_structure_prior_candidate_sha256','n_structure_prior_candidate_generation','n_structure_receipt_sha256',
          'n_structure_values_sha256','n_structure_checkpoint_sha256','company_asset_sha256','history_asset_sha256',
          'source_candidate_sha256','signal_component_facts_sha256'):
    identity.pop(k,None)
identity.update(symbol='300206.SZ',source_sha256=sources,source_gate_sha256=gate_ref['sha256'],
    admission_sha256=admission_ref['sha256'],score_contract_sha256=score['sha256'],
    score_engine_sha256=q.sha(repo/'ops/kb_hold_score.py'),supplemental_contract_sha256=supplemental['sha256'],
    action_contract_sha256=action['sha256'],yidong_contract_sha256=yidong['sha256'],
    display_policy_sha256=policy['sha256'],display_f10_sha256=f10_ref['sha256'],
    confirmed_gap_contract_sha256=gap_contract['sha256'],n_structure_contract_sha256=n_contract['sha256'],
    n_structure_helper_sha256=q._n_sha256s()['n_structure_helper_sha256'],builder_ref=ref(Path(__file__)),
    action_authority_sha256=q.sha(repo/'ops/kb_action_authority.py'),
    yidong_authority_sha256=q.sha(repo/'ops/kb_yidong_authority.py'),field_inventory=inventory)
initial_generation=q.canonical_sha(identity)
view={'schema':'junda_kb_single_research_candidate.v1','symbol':'300206.SZ','name':'理邦仪器','asof':20261030,
      'source_date':'2026-10-30','observation_date':'2026-11-02','source_generation':interim['source_generation'],
      'source_input_sha256':interim['identity']['input_sha256'],'source_snapshot':interim['snapshot'],
      'field_contract_sha256':sources['contracts/a_share_kb_fields_v1.json'],'authority_sha256':sources['ops/kb_signal_authority.py'],
      'selector_candidate_sha256':interim['outputs']['selector']['sha256'],'source_gate':'PASS_RELOCATED_SOURCE_GATE',
      'source_gate_receipt':gate_ref,'source_relocation':gate['relocation_ref'],'historical_PIT':False,
      'candidate_pool_member':False,'legacy_buy_sell_formula':'USER_V1_UNCHANGED','kb_formula':'PINNED_KB_V1',
      'fields':fields,'rows':rows,'candidate_generation':initial_generation,'candidate_identity_sha256':initial_generation,
      'field_inventory':inventory,'hold_score_contract_sha256':score['sha256'],'hold_score_engine_sha256':identity['score_engine_sha256'],
      'supplemental_contract_sha256':supplemental['sha256'],**q.FLAGS}
raw=json.dumps(view,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()
assert len(raw)<32*1024*1024
kb=immutable(r/'EDAN_INTERIM_VIEW_R1.json.gz',gzip.compress(raw,mtime=0));kb.update(encoding='gzip',decoded_bytes=len(raw))
binding.update(symbol='300206.SZ',name='理邦仪器',candidate_pool_member=False,rows=len(rows),
    candidate_identity=identity,candidate_generation=initial_generation,source_gate_receipt=gate_ref,
    source_relocation=gate['relocation_ref'],admission=admission_ref,assets={'kb':kb},field_inventory=inventory,
    hold_score_contract=score,hold_score_engine_sha256=identity['score_engine_sha256'],
    supplemental_contract=supplemental,action_contract=action,yidong_contract=yidong)
for k in ('confirmed_gap','n_structure','display_projection','history_source_relocation'):binding.pop(k,None)
ib=write_json(r/'EDAN_INTERIM_BINDING_R1.json',binding)
ic=write_json(r/'EDAN_INTERIM_CANDIDATE_R1.json',{'candidate_generation':initial_generation,'binding':ib,'outputs':interim['outputs'],**q.FLAGS})
calendar=ref(parent/'junda_score_visibility_20261101_r1/CALENDAR_SZ_20261030.json')
history=build_retained_single_stock(ic,calendar,r)
desc=next((x['desc'] for x in f10['concepts'] if x.get('name')=='健康中国' and x.get('desc')),None)
received={'schema':'v4.single_company_received.v1','symbol':'300206.SZ','asof':'2026-10-30',
    'sources':{'tdx_f10':{'kind':'TDX_F10_CURRENT_SNAPSHOT','file':f10_ref}},
    'business_reported':{'value':('TDX F10“健康中国”概念介绍：'+desc+'（当前采集快照）') if desc else '主营资料待核'},
    'financials_reported':{'latest_report_period':f10['financials']['report_period'],'latest_period_kind':'TDX F10当前快照',
                           'latest_revenue':None,'latest_net_profit_parent':None,'latest_disclosed_at':None},
    'shareholders_reported':{'holder_count':f10['financials']['holder_count'],'holder_asof':None,
                            'note':'F10采集时股东户数，具体统计截止日待核。'},'report_catalog':[],'stored_report':None}
rr=write_json(r/'EDAN_RECEIVED_COMPANY_R1.json',received)
company=materialize_bound_single_company(candidate_ref=ic,received_ref=rr,output_root=r)
facts={'schema':'single_signal_component_facts.v1','symbol':'300206.SZ','data_asof':20261030,
       'source':{'sha256':identity['baseline_panel_sha256']['selector']},'facts':{},
       'note':'No unbound component explanations are fabricated.'}
fr=write_json(r/'EDAN_SIGNAL_FACTS_R1.json',facts)
assets={}
for kind,item in [('history',history),('company',company)]:
    raw=q._source(item,owner=kind).read_bytes()
    obj=immutable(r/('EDAN_'+kind.upper()+'_'+item['sha256'][:16]+'.json.gz'),gzip.compress(raw,mtime=0))
    obj.update(encoding='gzip',decoded_bytes=len(raw));assets[kind]=obj

side=pq.read_table(q._source(interim['gap_sidecar'],owner='EDAN source diagnostics'))
side_rows=side.to_pylist();n_values=pq.read_table(q._source(interim['n_values'],owner='EDAN N values')).to_pylist()
for row,d in zip(n_values,side_rows):
    structure=json.loads(d['diagnostics_json'])['kb_n_structure']
    assert row['ts_code']==d['ts_code'] and row['trade_date']==d['trade_date'] and json.loads(row['kb_n_structure_json'])==structure
    row['prefix_input_sha256']=structure['prefix_input_sha256']
n_table=pa.Table.from_pylist(n_values);sink=pa.BufferOutputStream();pq.write_table(n_table,sink,compression='zstd')
n_ref=immutable(r/'EDAN_N_VALUES_R2.parquet',sink.getvalue().to_pybytes())
checkpoint=json.loads(q._source(interim['n_checkpoint'],owner='EDAN N checkpoint').read_text())
assert n_values[-1]['prefix_input_sha256']==checkpoint['prefix_sha256'] and checkpoint['symbol']=='300206.SZ'
n_item={'source_candidate_generation':initial_generation,'source_selector_sha256':interim['outputs']['selector']['sha256'],
        'n_values_path':n_ref['path'],'n_values_sha256':n_ref['sha256'],
        'checkpoint_path':interim['n_checkpoint']['path'],'checkpoint_file_sha256':interim['n_checkpoint']['sha256'],
        'checkpoint_state_sha256':checkpoint['checkpoint_sha256'],'prefix_input_sha256':checkpoint['prefix_sha256'],
        'rows':len(rows)}
n_receipt=write_json(r/'EDAN_N_PREPARED_RECEIPT_R1.json',{'schema':'n_structure_v1_prepared_receipt_v1',
    'source_generation':binding['source_generation'],'source_input_sha256':binding['source_input_sha256'],
    'snapshot_file_sha256':identity['snapshot_sha256'],'contract_sha256':n_contract['sha256'],
    'helper_sha256':identity['n_structure_helper_sha256'],'calendar_sha256':None,'price_basis_sha256':None,
    'price_basis':'QFQ_ASOF','symbols':{'300206.SZ':n_item},**q.FLAGS})
source_full=pq.read_table(q._source(interim['outputs']['selector'],owner='EDAN gap owner values'))
gap_source={}
for role,names in [('rebuild',['ts_code','trade_date','kb_rebuild','kb_brick_trend','kb_brick_action_desc']),
                   ('components',['ts_code','trade_date',*sorted(q.SINGLE_GAP_FIELDS-{'kb_brick_trend','kb_brick_action_desc'})])]:
    part=source_full.select(names);sink=pa.BufferOutputStream();pq.write_table(part,sink,compression='zstd')
    gap_source[role]=immutable(r/f'EDAN_GAP_SOURCE_{role.upper()}_R1.parquet',sink.getvalue().to_pybytes())
gap_source_receipt=write_json(r/'EDAN_GAP_SOURCE_RECEIPT_R1.json',{'schema':'v4.single_gap_source_projection.v1',
    'symbol':'300206.SZ','source_owner':ref(repo/'ops/research_panel_qfq.py'),
    'input_candidate':ref(r/'EDAN_PREFIX_INTERIM_R1.json'),'source_full':interim['outputs']['selector'],
    'source_diagnostics':interim['gap_sidecar'],'role_projections':gap_source,'rows':len(rows),**q.FLAGS})
identity.update(source_candidate_sha256=ic['sha256'],history_asset_sha256=assets['history']['sha256'],
    company_asset_sha256=assets['company']['sha256'],signal_component_facts_sha256=fr['sha256'],
    confirmed_gap_source_sha256={'rebuild':gap_source['rebuild']['sha256'],'components':gap_source['components']['sha256'],
                                 'diagnostics':interim['gap_sidecar']['sha256']},
    n_structure_enabled=True,n_structure_values_sha256=n_ref['sha256'],n_structure_checkpoint_sha256=interim['n_checkpoint']['sha256'],
    n_structure_receipt_sha256=n_receipt['sha256'],n_structure_prior_candidate_generation=initial_generation)
generation=q.canonical_sha(identity);short=generation[:16];outputs={};display_roles={}
policy_doc=json.loads(q._source(policy,owner='display policy').read_text());excluded=policy_doc['excluded_from_display_projection']
for role,item in interim['outputs'].items():
    table=pq.read_table(q._source(item,owner='EDAN paired intermediate'))
    m=dict(table.schema.metadata or {});m[b'kb_single_candidate_v1']=json.dumps({'candidate_generation':generation,
        'source_generation':binding['source_generation'],'source_input_sha256':binding['source_input_sha256'],
        'confirmed_gap_contract_sha256':gap_contract['sha256'],'historical_PIT':False,**q.FLAGS},sort_keys=True).encode()
    table=table.replace_schema_metadata(m);sink=pa.BufferOutputStream();pq.write_table(table,sink,compression='zstd')
    output=immutable(r/f'EDAN_{role.upper()}_FULL_{short}.parquet',sink.getvalue().to_pybytes())
    reread=pq.read_table(q._source(output,owner='EDAN final readback'))
    assert all(same(table[name],reread[name]) for name in table.column_names)
    outputs[role]={**output,'rows':len(table),'old_columns_equal':True}
    removed=[name for name in table.column_names if name in excluded]
    projected=table.select([name for name in table.column_names if name not in excluded])
    projected=projected.append_column(pa.field('kb_concepts',pa.string(),nullable=True),pa.array([None]*(len(table)-1)+[concepts],type=pa.string()))
    projected=projected.append_column(pa.field('kb_concept_count',pa.int8(),nullable=True),pa.array([None]*(len(table)-1)+[concept_count],type=pa.int8()))
    context={'candidate_generation':generation,'symbol':'300206.SZ','role':role,'source_full_sha256':output['sha256'],
             'policy_sha256':policy['sha256'],'f10_sha256':f10_ref['sha256'],'captured_at':f10['captured_at'],
             'historical_PIT':False,**q.FLAGS}
    projected=projected.replace_schema_metadata({b'a_share_single_display_projection_v1':json.dumps(context,sort_keys=True).encode()})
    sink=pa.BufferOutputStream();pq.write_table(projected,sink,compression='zstd')
    artifact=immutable(r/f'EDAN_{role.upper()}_DISPLAY_{short}.parquet',sink.getvalue().to_pybytes())
    display_roles[role]={'artifact':artifact,'source_full':output,'removed_fields':removed,'columns':len(projected.column_names),'rows':len(projected)}

metadata=json.loads((side.schema.metadata or {})[b'v4.a_share.kb_gap_diagnostics.v1'])
metadata.update(candidate_generation=generation,source_generation=binding['source_generation'])
side=side.replace_schema_metadata({b'v4.a_share.kb_gap_diagnostics.v1':json.dumps(metadata,sort_keys=True).encode()})
sink=pa.BufferOutputStream();pq.write_table(side,sink,compression='zstd')
side_ref=immutable(r/f'EDAN_DIAGNOSTICS_{short}.parquet',sink.getvalue().to_pybytes())
source_contracts={name:ref(repo/name) for name in json.loads(q._source(gap_contract,owner='gap contract').read_text())['source_contracts']}
gap={'contract':gap_contract,'source_contracts':source_contracts,'diagnostics':side_ref,
     'source_diagnostics':interim['gap_sidecar'],'source_candidates':gap_source,
     'source_receipts':{'rebuild':gap_source_receipt,'components':gap_source_receipt,'diagnostics':gap_source_receipt},
     'prior_source_gate':gate['prior_source_gate'],'calendar_status':'CANNOT_CONFIRM','calendar_sha256':None}
n_binding={'contract':n_contract,'receipt':n_receipt,'values':n_ref,'checkpoint':interim['n_checkpoint']}
display={'policy':policy,'f10_source':f10_ref,'captured_at':f10['captured_at'],'kb_concepts':concepts,
         'kb_concept_count':concept_count,'historical_PIT':False,'roles':display_roles}
view.update(candidate_generation=generation,candidate_identity_sha256=generation,selector_candidate_sha256=outputs['selector']['sha256'],
    signal_component_facts=facts['facts'],signal_component_facts_sha256=fr['sha256'],action_contract_sha256=action['sha256'],
    yidong_contract_sha256=yidong['sha256'],concept_snapshot={'source_sha256':f10_ref['sha256'],'kb_concepts':concepts,
        'kb_concept_count':concept_count,'captured_at':f10['captured_at'],'historical_PIT':False},
    confirmed_gap_contract_sha256=gap_contract['sha256'],confirmed_gap_diagnostics_sha256=side_ref['sha256'],
    n_structure_contract_sha256=n_contract['sha256'])
raw=json.dumps(view,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode();assert len(raw)<32*1024*1024
kb=immutable(r/f'EDAN_VIEW_{short}.json.gz',gzip.compress(raw,mtime=0));kb.update(encoding='gzip',decoded_bytes=len(raw))
projection=json.loads(gzip.decompress((r/'EDAN_ORIGINAL_PROJECTION_R1.json.gz').read_bytes()))
projection.update(candidate_generation=generation);projection['lineage']['candidate_generation']=generation
projection['lineage']['selector_candidate']=outputs['selector'];projection['lineage']['source_gate']=gate_ref
projection['lineage']['source_relocation']=gate['relocation_ref']
raw=(json.dumps(projection,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()
proj=immutable(r/f'EDAN_PROJECTION_{short}.json.gz',gzip.compress(raw,mtime=0))
proj.update(encoding='gzip',decoded_bytes=len(raw),row_count=len(rows),formula_sha256=renderer.FORMULA_SHA)
html=renderer.chart_html(Path(renderer.OWNER_RENDERER['path']).read_bytes(),projection,projection['lineage'],compress_payload=True)
html=html.replace('候选派生投影','单股研究投影').replace('候选原式派生投影','单股原式研究投影')
chart=immutable(r/f'EDAN_CHART_{short}.html',html.encode())
assets.update(kb=kb,projection=proj,html=chart)
binding.update(candidate_identity=identity,candidate_generation=generation,assets=assets,confirmed_gap=gap,
               n_structure=n_binding,display_projection=display)
br=write_json(r/f'EDAN_BINDING_{short}.json',binding)
result={'schema':'single_kb_final_candidate_receipt.v1','status':'PREPARED_PENDING_UI_AND_INDEPENDENT_REVIEW',
        'candidate_generation':generation,'candidate_identity':identity,'symbol':'300206.SZ',
        'source_date':'2026-10-30','observation_date':'2026-11-02','source_generation':binding['source_generation'],
        'source_input_sha256':binding['source_input_sha256'],'numeric_manifest':binding['numeric_manifest'],
        'binding':br,'outputs':outputs,'assets':assets,'admission':admission_ref,'source_gate':gate_ref,
        'historical_PIT':False,'candidate_pool_member':False,'history_source':history,'company_source':company,
        'display_projection':display,'confirmed_gap':gap,'n_structure':n_binding,'rows':len(rows),**q.FLAGS}
result_ref=write_json(r/f'EDAN_CANDIDATE_{short}.json',result)
print(json.dumps({'generation':generation,'receipt':result_ref,'binding':br,'history':history,'company':company,
                  'rows':len(rows),'decoded_view_bytes':kb['decoded_bytes'],
                  'display_columns':{k:v['columns'] for k,v in display_roles.items()}},ensure_ascii=False))
