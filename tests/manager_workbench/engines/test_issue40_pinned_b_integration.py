"""Executable exact-B integration, gated by fixed Git blobs (not a B mirror).

Mac: assemble A@<candidate> + original B@5010f866 (or B contract-only
correction b132f9bc) in a temporary checkout, then run this test file.
It NEVER accesses live owners, CLI, a network model, or a trading surface.
"""
from __future__ import annotations

from datetime import datetime
from hashlib import sha1
import importlib
from pathlib import Path
import time

import pytest
from v4.manager_workbench.engines.announcement import PROMPT_VERSION
from v4.manager_workbench.engines.common import RULE, digest, plain
from test_issue40_joint_regressions import RealBShapedExecutor, b_announcement

B_SERVICE_BLOB = "5ec946053d984b34d9399460a45c44366c4cff4f"
B_EXECUTOR_BLOB = "89d6e9d6a862aa5c7a06ab6ca70d88dc7a749354"
B_CONTRACT_BLOBS = {
    "a1efa6d79d56c1ef2ff0ce95c8ee2fbe5c737112",  # original B @5010f866
    "2974275d64416c4a7f528944a4b3be36e1743c58",  # Mac-reviewed contract correction b132f9bc
}


def _git_blob(path):
    content=Path(path).read_bytes()
    return sha1(b"blob "+str(len(content)).encode()+b"\0"+content).hexdigest()


@pytest.fixture
def exact_b():
    try:
        svc=importlib.import_module("v4.manager_workbench.service")
        exc=importlib.import_module("v4.manager_workbench.executors.codex")
        cfg=importlib.import_module("v4.manager_workbench.config")
        con=importlib.import_module("v4.manager_workbench.contracts")
    except ModuleNotFoundError:
        pytest.skip("PINNED_B_ORIGINAL_5010_SOURCE_NOT_ASSEMBLED")
    verified=(
        _git_blob(svc.__file__)==B_SERVICE_BLOB
        and _git_blob(exc.__file__)==B_EXECUTOR_BLOB
        and _git_blob(con.__file__) in B_CONTRACT_BLOBS
    )
    if not verified:
        pytest.skip("PINNED_B_SOURCE_IDENTITY_MISMATCH")
    return svc,exc,cfg,con


def test_original_b_service_executes_full_a_load_run_merge_store(tmp_path,exact_b):
    svc,exc,cfg,con=exact_b
    from v4.manager_workbench import engines
    config=cfg.WorkbenchConfig(state_root=tmp_path, rules_version=RULE,
        model="b-fixture-model",prompt_version=PROMPT_VERSION)
    service=svc.create_service(config,{},engines,object())
    try:
        job=service.submit("20261013",con.Phase.MANUAL,trigger="MANUAL",
            cutoff=datetime.fromisoformat("2026-10-13T09:00:00+08:00"))
        deadline=time.monotonic()+8
        while time.monotonic() < deadline:
            saved=service.jobs.get(job.job_id)
            if saved.state not in (con.JobState.QUEUED,con.JobState.RUNNING):
                break
            time.sleep(.02)
        else:
            pytest.fail("B_JOB_TIMED_OUT")
        assert saved.state==con.JobState.PARTIAL, saved.model_dump(mode="json")
        plan=service.store.read_plan(saved.run_id)
        assert len(plan.lanes)==5
        assert all(l.run_id==saved.run_id and l.state==con.LaneState.INPUT_MISSING for l in plan.lanes)
        assert plan.counts.selected==0 and plan.counts.unassessed==0
        assert not plan.orders_sent and not plan.production_allowed
    finally:
        service.jobs.stop()


def test_original_b_audited_executor_accepts_a_shared_source_hash(exact_b):
    svc,exc,cfg,con=exact_b
    from v4.manager_workbench.engines.announcement import run_announcements
    c,b=b_announcement()
    delegate=RealBShapedExecutor()
    delegate.config=delegate.delegate.config
    audit=exc.AuditedExecutor(delegate)
    output=run_announcements(plain(c),b,audit)
    assert output['rows'][0]['decision']=='SELECTED'
    audit.assert_independent_review(True)
    assert [r['role'] for r in audit.refs]==['READER','REVIEWER']
    assert audit.refs[0]['input_sha256']==audit.refs[1]['input_sha256']
    assert audit.refs[0]['source_sha256']==audit.refs[1]['source_sha256']
