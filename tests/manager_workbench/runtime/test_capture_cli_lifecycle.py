"""CLI waits capture completion before closing its incremental research queue."""
from datetime import datetime
import threading
import pytest
from test_capture_wiring import setup,Clock,research_job
from v4.manager_workbench import cli
from v4.manager_workbench.contracts import HK,JobState


def inject(monkeypatch,service):
    monkeypatch.setattr(cli,'load_config',lambda _:service.config)
    monkeypatch.setattr(cli,'_binding',lambda _:dict(adapters=service.adapters,engines=service.engines,executor=service.executor))
    monkeypatch.setattr(cli,'create_service',lambda *a,**kw:service)


def test_cli_run_closes_capture_first_and_persists_incremental_result(tmp_path,monkeypatch,capsys):
    service,t,m,cache,clock=setup(tmp_path,clock=Clock(datetime.now(HK).isoformat()))
    service.capture_jobs.clock=lambda:datetime.now(HK)
    service.capture_jobs.cache.clock=service.capture_jobs.clock
    inject(monkeypatch,service)
    assert cli.main(['--config','injected','--binding','injected:factory','run','20261013'])==0
    assert service.capture_jobs.jobs.pool._shutdown and service.jobs.pool._shutdown
    assert research_job(service).state==JobState.SUCCEEDED
    assert m.roles==['READER','REVIEWER']
    assert '"job_id"' in capsys.readouterr().out


def test_cli_exception_still_closes_both_queues(tmp_path,monkeypatch,capsys):
    service,t,m,cache,clock=setup(tmp_path)
    inject(monkeypatch,service)
    def fail(*args,**kwargs):raise RuntimeError('synthetic private exception')
    monkeypatch.setattr(cli,'tick',fail)
    assert cli.main(['--config','injected','--binding','injected:factory','tick'])==3
    assert service.capture_jobs.jobs.pool._shutdown and service.jobs.pool._shutdown
    assert 'WORKBENCH_CLI_FAILED' in capsys.readouterr().err and not t.calls
