"""Only current Main parent/accepted cohort/jobs compatibility; no old suite rerun."""
from datetime import datetime
import hashlib
import importlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from types import SimpleNamespace

import pytest

CANDIDATE=Path(os.environ['US_MAIN_CANDIDATE']).resolve()
sys.path.insert(0,str(CANDIDATE))
CASE=Path('/Users/lexi/Desktop/学习/agents调试/V4_BUSINESS_GAPS_20261027')


@pytest.fixture(autouse=True)
def no_external(monkeypatch):
    monkeypatch.delenv('V4_RUNTIME_GRAPH_INBOX',raising=False)
    def denied(*a,**k):pytest.fail('integration fixture may not use provider/subprocess/network')
    monkeypatch.setattr(socket.socket,'connect',denied);monkeypatch.setattr(subprocess,'Popen',denied)


def test_complete_current_parent_imports_accepted_12_and_preserves_original_jobs_hook():
    rows=json.loads((CASE/'baseline/US_MAPPING_THREE_WAY_R1.json').read_bytes())
    for row in rows:
        module=importlib.import_module(row['path'][:-3].replace('/','.'))
        path=Path(module.__file__).resolve();assert path==CANDIDATE/row['path']
        assert hashlib.sha256(path.read_bytes()).hexdigest()==row['after_sha256']
    for name in ('v4.manager_workbench.jobs','v4.manager_workbench.supervisor','v4.manager_workbench.store'):
        module=importlib.import_module(name);path=Path(module.__file__).resolve();assert path.is_relative_to(CANDIDATE)
        original=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/ui-pdf-publication-20261027-r2-main/app')/path.relative_to(CANDIDATE)
        assert path.read_bytes()==original.read_bytes()
    from v4.manager_workbench.engines.us_mapping_policy import POLICY
    assert (POLICY['primary_return_min'],POLICY['max_selected'],POLICY['max_theme'],POLICY['sector_paths'])==('1',10,3,'CONTEXT_ONLY')
    from v4.manager_workbench.contracts import RunContext,Phase
    from v4.manager_workbench.service import _selection_identity
    ctx=RunContext(target_date='20261027',phase=Phase.NEXT_DAY,cutoff='2026-10-27T04:17:00+08:00',trigger='SCHEDULED',rules_version='frozen',scope_refs={'requested_lanes':['US_MAPPING']})
    identity=_selection_identity(ctx)
    assert identity['us_selection_policy_sha256'] and identity['us_selection_engine_identity']


def test_current_main_jobs_event_wiring_survives_new_job_contract_and_is_exact_once(monkeypatch):
    from v4.manager_workbench import jobs
    from v4.manager_workbench.contracts import JobRecord,JobState,RunContext,Phase
    events=[];saved=[]
    monkeypatch.setattr(jobs,'_graph_notify',lambda *a,**k:events.append((a,k)))
    coordinator=object.__new__(jobs.JobCoordinator);coordinator.store=SimpleNamespace(root=Path('/isolated/store'),save_job=lambda job:saved.append(job.state.value))
    ctx=RunContext(target_date='20261027',phase=Phase.NEXT_DAY,cutoff='2026-10-27T04:17:00+08:00',trigger='SCHEDULED',rules_version='frozen')
    job=JobRecord(job_id='samejob',run_id='samejob',context=ctx,state=JobState.QUEUED,step='QUEUED')
    coordinator.update(job,state=JobState.RUNNING);coordinator.update(job,step='PROGRESS')
    coordinator.update(job,state=JobState.PARTIAL,finished=True)
    assert [event[0][3] for event in events]==['EXECUTOR_ENTERED','COMMITTED']
    assert all(event[0][:2]==('MANAGER_WORKBENCH','manager_workbench') for event in events)
    assert all(event[1]['source_path']==Path('/isolated/store/attempts/samejob.json') for event in events)
    assert saved==['RUNNING','RUNNING','PARTIAL'] and job.finished_at
