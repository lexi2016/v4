import os
from pathlib import Path
from types import SimpleNamespace
import pytest
from v4.manager_workbench.executors.local_cli import process_environment,LocalCliRunner,SKILL_LIMITS
from v4.manager_workbench.executors.codex import IsolationNotVerified
from v4.manager_workbench.executors.schema_check import validate_output
from v4.manager_workbench.engines.announcement import READER_SCHEMA,REVIEWER_SCHEMA,_validate_reader,_validate_review,_task,PROMPT_VERSION
from v4.manager_workbench.contracts import digest


def test_launchagent_no_proxy_star_is_replaced_only_for_verified_system_proxy(monkeypatch):
    monkeypatch.setenv('NO_PROXY','*');monkeypatch.setenv('no_proxy','*')
    monkeypatch.setenv('HTTPS_PROXY','https://unapproved.invalid')
    monkeypatch.setenv('ALL_PROXY','socks5://unapproved.invalid')
    config='''<dictionary> {
 HTTPEnable : 1
 HTTPProxy : 127.0.0.1
 HTTPPort : 7897
 HTTPSEnable : 1
 HTTPSProxy : 127.0.0.1
 HTTPSPort : 7897
}'''
    monkeypatch.setattr('subprocess.run',lambda *args,**kwargs:SimpleNamespace(stdout=config.encode(),returncode=0))
    env=process_environment()
    assert env['HTTPS_PROXY']=='http://127.0.0.1:7897'
    assert env['NO_PROXY']==env['no_proxy']=='localhost,127.0.0.1,::1'
    assert 'ALL_PROXY' not in env
    assert os.environ['NO_PROXY']=='*'
    monkeypatch.setattr('subprocess.run',lambda *args,**kwargs:SimpleNamespace(stdout=config.replace('127.0.0.1','unapproved.invalid').encode(),returncode=0))
    env=process_environment()
    assert 'HTTPS_PROXY' not in env and 'ALL_PROXY' not in env


def test_binary_profile_change_denied_without_model_execution(tmp_path):
    binary=tmp_path/'codex';binary.write_text('unverified binary')
    with pytest.raises(IsolationNotVerified,match='CODEX_BINARY_REVIEW_IDENTITY_CHANGED'):LocalCliRunner(binary)


def test_proxy_form_actual_enum_failure_regression_and_independent_review():
    body='FORM OF PROXY. Shareholders may appoint a representative.'
    article=dict(source_sha256='a'*64,body_sha256='b'*64)
    output=dict(disposition='NOT_SELECTED',selection_basis='NOT_SELECTED',direction='NEUTRAL',
        evidence_sufficiency='VERIFIED_EXISTING_FACTS',reason='Administrative form; no operating catalyst.',risk_notes=[],
        facts=[dict(claim='Proxy form',quote='FORM OF PROXY',locator='page 1')],changes=[],impact=[],confirmation_conditions=[],counter_evidence=[],**article)
    validate_output(output,READER_SCHEMA);_validate_reader(body,article,output)
    for field,value in [('direction','NOT_ASSESSED'),('selection_basis','Assessed proxy form independently'),('evidence_sufficiency','INSUFFICIENT: a proxy form')]:
        invalid={**output,field:value}
        with pytest.raises(ValueError):validate_output(invalid,READER_SCHEMA)
    reader=dict(output=output,output_sha256=digest(output),execution_identity='reader:1',execution_id='reader')
    reviewed=dict(confirmed=True,reason='Source is a complete administrative form without a qualifying catalyst.',
        reader_output_sha256=digest(output),disposition='NOT_SELECTED',direction='NEUTRAL',evidence_sufficiency='VERIFIED_EXISTING_FACTS',**article)
    validate_output(reviewed,REVIEWER_SCHEMA)
    _validate_review(article,reader,dict(output=reviewed,execution_identity='reviewer:2',execution_id='reviewer'))
    assert PROMPT_VERSION=='MWB_ANNOUNCEMENT_READER_REVIEWER_V2_20261013'
    executor=SimpleNamespace(models={'READER':'gpt-6-luna'},reasoning_effort={'READER':'max'})
    current=_task(executor,'READER',article={**article,'article_id':'official:1','symbol':'HK.00001','owner':'HKEX','observed_at':'2026-10-12T18:00:00+08:00','available_at':'2026-10-12T18:00:00+08:00'},body=body)
    assert current['prompt_version']==PROMPT_VERSION


def test_exact_profile_matches_executed_canary_and_rejects_extra_overrides(tmp_path,monkeypatch):
    import json
    from v4.manager_workbench.executors.local_cli import invocation_profile,VERIFIED_BINARY_SHA256
    receipt=Path(__file__).resolve().parents[3]/"docs/handoff/manager-workbench-implementation-20261013/real-single-article-canary-receipt.json"
    saved=json.loads(receipt.read_text())
    for invocation in saved['actual_invocations']:
        argv=invocation['argv'];workspace=Path(argv[argv.index('--output-schema')+1]).parent
        assert argv==invocation_profile(Path(argv[0]),workspace)
    runner=LocalCliRunner.__new__(LocalCliRunner)
    runner.binary=Path(saved['actual_invocations'][0]['argv'][0])
    changed=invocation_profile(runner.binary,tmp_path)
    changed[2:2]=['-c','features.shell_tool=true']
    with pytest.raises(IsolationNotVerified,match='CODEX_FIXED_PROFILE_CHANGED'):
        runner.run(argv=changed,cwd=tmp_path,stdin=b'synthetic',timeout_seconds=1,role='READER')
