"""Reviewer-only comparison of original/candidate readers on one Parquet fixture."""
from __future__ import annotations

import ast
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pandas
import pyarrow
import pytest

BASE = Path('/workspace/scratch/ff44f882fe5c')
BASELINE = BASE / 'verification/reviewer_history/baseline_regression'
REVIEW = BASE / 'verification/reviewer_history/o_subreview'


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n', encoding='utf-8')


def ast_function(path, name):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    return ast.dump(next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name), include_attributes=False)


def snapshot():
    support = subprocess.run(['rg', '--files', 'support_source', '-g', '*.py', '-g', '*.json'],
        cwd=BASE, check=True, text=True, capture_output=True).stdout.splitlines()
    names = support + [
        'candidate/v4/manager_research/workspace_plan.py',
        'candidate/v4/manager_research/research_attention.py',
        'candidate/v4/manager_research/workspace_projection.py',
        'candidate/v4/manager_research/workspace.py',
        'candidate/v4/manager_research/workspace_daily_channels.py',
        'candidate/tests/test_manager_three_lane_rebound_diagnostics_r1.py',
        'verification/reviewer_history/baseline_regression/v4/manager_research/workspace_plan.py',
        'verification/reviewer_history/baseline_regression/v4/manager_research/workspace_projection.py',
        'verification/reviewer_history/baseline_regression/v4/manager_research/research_attention.py',
    ]
    return dict(utc=datetime.now(timezone.utc).isoformat(), support_py_json_count=len(support),
        hashes={name:hashlib.sha256((BASE/name).read_bytes()).hexdigest() for name in sorted(names)})


def main():
    run_dir = REVIEW / ('original_screen_comparison_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    run_dir.mkdir(parents=True)
    fixture_dir = run_dir / 'parquet_fixture'
    fixture_dir.mkdir()
    before = snapshot()
    write_json(run_dir/'hashes_before.json', before)

    from v4.manager_research import workspace_plan as candidate_plan
    from v4.manager_research import workspace_projection as candidate_projection
    from v4.manager_research import research_attention as candidate_attention

    original_plan = load_module('v4.manager_research._review_original_plan',
        BASELINE/'v4/manager_research/workspace_plan.py')
    original_projection = load_module('v4.manager_research._review_original_projection',
        BASELINE/'v4/manager_research/workspace_projection.py')
    original_attention = load_module('v4.manager_research._review_original_attention',
        BASELINE/'v4/manager_research/research_attention.py')
    fixture_module = load_module('_review_original_screen_fixture',
        BASE/'candidate/tests/test_manager_three_lane_rebound_diagnostics_r1.py')

    def attention(module, screen, context):
        return module.build_research_attention('20261012', context=context, market_screen=screen,
            stocks=[], material_cards=[], themes=[], announcement_observation=None, us_market=None)

    with pytest.MonkeyPatch.context() as monkeypatch:
        fixture = fixture_module.tabular_input.__wrapped__(fixture_dir, monkeypatch)
        for name in ('_read_hk02_panel_witness', '_screen_security_master_witness', '_read_hk02_daily_supplement_witness'):
            monkeypatch.setattr(original_plan, name, getattr(candidate_plan, name))
        original_screen = original_plan.read_rebound_screen(fixture['root'], fixture['context'])
        diagnostics = {'rows':['stale'], 'gaps':['stale'], 'source_screen_decision_identity':'stale'}
        candidate_screen = candidate_plan.read_rebound_screen(fixture['root'], fixture['context'], diagnostics=diagnostics)
        kwargs = dict(catalyst=dict(target_trade_date='20261012', status='NOT_MATERIALIZED', cards=[], gaps=[]),
            plan_context=fixture['context'])
        original_outputs = dict(screen=original_screen,
            plan=original_projection.build_workspace('20261012', market_screen=original_screen, **kwargs),
            research_attention=attention(original_attention, original_screen, fixture['context']))
        candidate_outputs = dict(screen=candidate_screen,
            plan=candidate_projection.build_workspace('20261012', market_screen=candidate_screen, **kwargs),
            research_attention=attention(candidate_attention, candidate_screen, fixture['context']))
        assertions = dict(
            original_success=original_screen['status']=='READY_WITH_GAPS' and original_screen['coverage']['input_candidate_count']==2,
            candidate_success=candidate_screen['status']=='READY_WITH_GAPS' and candidate_screen['coverage']['input_candidate_count']==2,
            complete_screen_equal=original_screen==candidate_screen,
            complete_plan_equal=original_outputs['plan']==candidate_outputs['plan'],
            plan_input_identity_equal=original_outputs['plan']['input_identity']==candidate_outputs['plan']['input_identity'],
            complete_research_attention_equal=original_outputs['research_attention']==candidate_outputs['research_attention'],
            complete_research_ledger_equal=original_outputs['research_attention']['research_selection']==candidate_outputs['research_attention']['research_selection'],
            same_panel_master_reader_calls=len(fixture['calls'])==4,
            unattested_volume_remains_pending=len(original_screen['pending'])==len(candidate_screen['pending'])==2 and original_screen['coverage']['strict_count']==candidate_screen['coverage']['strict_count']==0,
        )
        write_json(run_dir/'original_outputs.json', original_outputs)
        write_json(run_dir/'candidate_outputs.json', candidate_outputs)
        write_json(run_dir/'diagnostics.json', diagnostics)
        fixture_record = dict(day=fixture['day'], context=fixture['context'], calls=fixture['calls'],
            missing=fixture['missing'], duplicate=fixture['duplicate'],
            parquet_sha256=fixture['panel']['panel_sha256'])

    after = snapshot()
    write_json(run_dir/'hashes_after.json', after)
    changed = [name for name in sorted(set(before['hashes'])|set(after['hashes']))
        if before['hashes'].get(name)!=after['hashes'].get(name)]
    assertions['source_files_unchanged'] = not changed
    ast_equal = {}
    for module, function in (('workspace_projection','build_workspace'), ('research_attention','build_research_attention'),
            ('research_attention','build_research_selection_ledger')):
        ast_equal[function] = ast_function(BASELINE/f'v4/manager_research/{module}.py', function) == ast_function(BASE/f'candidate/v4/manager_research/{module}.py', function)
    report = dict(result='PASS' if all(assertions.values()) else 'FAIL', assertions=assertions,
        artifact_directory=str(run_dir), command=[sys.executable,'-B',str(Path(__file__).resolve())],
        before_utc=before['utc'], after_utc=after['utc'], support_py_json_count=before['support_py_json_count'],
        total_hashed_files=len(before['hashes']), changed_files=changed,
        environment=dict(python=sys.version,pandas=pandas.__version__,pyarrow=pyarrow.__version__),
        projection_function_ast_equal=ast_equal, fixture=fixture_record,
        modules=dict(original_plan=original_plan.__file__,candidate_plan=candidate_plan.__file__,
            original_projection=original_projection.__file__,candidate_projection=candidate_projection.__file__,
            original_attention=original_attention.__file__,candidate_attention=candidate_attention.__file__),
        limitations=['One synthetic two-symbol real-Parquet fixture; not a live owner provenance attestation.',
            'Original top-level modules loaded from the exported baseline; relative imports use the current shared package/dependency namespace.',
            'Panel/master/supplement reader boundaries are patched identically; real reader calculation bodies, calendar and Parquet are executed.',
            'No Mac execution, live market selection, or natural scheduling assertion.'])
    write_json(run_dir/'comparison_result.json', report)
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report['result']=='PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
