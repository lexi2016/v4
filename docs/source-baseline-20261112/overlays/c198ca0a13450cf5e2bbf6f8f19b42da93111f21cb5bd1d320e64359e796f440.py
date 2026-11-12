"""Adjacent #22/#24 invariants; no rerun of the deployed 333MB native read."""
from copy import deepcopy
from pathlib import Path
import json
import os
import ast
from types import SimpleNamespace
import pytest
from v4.manager_research.workspace import _readback_plan, PLAN_SCHEMA
from v4.manager_research.workspace_projection import FLAGS,digest


def test_issue24_persistent_storage_and_reader_are_byte_identical():
    root=Path(os.environ['V4_TEST_ROOT']); source=Path(os.environ['V4_INPUT_ROOT'])/'source'
    for path in ('v4/manager_research/store.py','v4/manager_research/workspace.py',
                 'v4/manager_research/workspace_read_control.py','v4/manager_research/research_evidence.py'):
        assert (root/path).read_bytes()==(source/path).read_bytes(),path
    # Inspect the actual constant without replacing native SafeRoot.
    tree=ast.parse((root/'v4/manager_research/store.py').read_text())
    assignment=next(n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='WORKSPACE_PLAN_MAX_BYTES' for t in n.targets))
    assert eval(compile(ast.Expression(assignment.value),'<constant>','eval'),{'__builtins__':{}})==320*1024*1024


def product(current):
    workspace=deepcopy(current)
    workspace['research_attention']={'status':'READY','input_identity':'old-diagnostic'}
    workspace['selection_diagnostics']={'status':'READY'}
    row=dict(schema_version=PLAN_SCHEMA,target_trade_date='20261002',run_id='1'*32,
             execution_kind='MANUAL_REFRESH',generated_at='2026-10-03T04:18:29+00:00',
             workspace=workspace,input_identity=current['input_identity'],**FLAGS)
    row['sha256']=digest(row)
    return row


def current_workspace():
    return dict(target_trade_date='20261002',semantic_version='synthetic-v1',input_identity='x'*64,
        plan_context={'research_cutoff':'2026-10-03T12:18:06+08:00'},
        stocks=[],focus_symbols=[],research_attention={'status':'READY_WITH_GAPS'},
        selection_diagnostics={'formal_selection':{'status':'NOT_APPLICABLE'}},**FLAGS)


def test_current_saved_plan_overlays_new_diagnostics_without_mutating_sealed_bytes(tmp_path):
    current=current_workspace();saved=product(current);original=deepcopy(saved)
    store=SimpleNamespace(root=tmp_path,_read=lambda path: deepcopy(saved) if 'workspace_plans' in path.parts else None)
    result=_readback_plan(store,'20261002',current)
    assert result['plan_product']['status']=='CURRENT' and result['plan_product']['consumed'] is True
    assert result['selection_diagnostics']==current['selection_diagnostics']
    assert result['research_attention']==current['research_attention']
    assert result['plan_product']['run_id']==saved['run_id']
    assert saved==original


def test_bad_readback_remains_failed_and_preserves_fresh_diagnostics(tmp_path):
    def read(_): raise ValueError('synthetic corrupt stored product')
    current=current_workspace()
    out=_readback_plan(SimpleNamespace(root=tmp_path,_read=read),'20261002',current)
    assert out['plan_product']['status']=='READBACK_FAILED'
    assert out['selection_diagnostics']['formal_selection']['status']=='NOT_APPLICABLE'


def test_frozen_us_card_hashes_match_exact_archive_ingestion_gap_ids():
    f=json.loads((Path(os.environ['V4_INPUT_ROOT'])/'evidence/FROZEN_SELECTED_FIELDS.json').read_text())
    ids=set()
    def walk(v):
        if isinstance(v,dict):
            for a in v.values():walk(a)
        elif isinstance(v,list):
            for a in v:walk(a)
        elif isinstance(v,str) and v.startswith('ARCHIVE_ARTICLE_ACQUISITION_TIME_MISSING:'):
            ids.add(v.split(':',1)[1])
    walk(f)
    audits=f['selection_diagnostics']['us_relation_audit']
    assert len(audits)==84
    matches=[]
    for row in audits:
        matched=[]
        for ref in row['source_refs']:
            for aid in ids:
                mid=digest([ref['payload_path'],ref['payload_sha256'],aid])
                if digest(['MATERIAL','20261002',row['symbol'],mid])==row['card_id']:
                    matched.append(aid)
        assert len(matched)==1,row['card_id']
        matches.extend(matched)
    assert matches[0]=='935c5711e5ec57d3645381231afa8ebc577c94c52b5d7bcb72d78559789a03c5'
