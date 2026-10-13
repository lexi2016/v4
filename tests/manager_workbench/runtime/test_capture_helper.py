"""Isolated helper cannot grant leases or silently invoke a model/network."""
import importlib.util
import json
from pathlib import Path
import pytest
from test_capture_wiring import setup


def helper():
    path=Path(__file__).resolve().parents[3]/'docs/handoff/manager-workbench-implementation-20261013/capture_wiring_helper.py'
    spec=importlib.util.spec_from_file_location('capture_wiring_helper_test',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def test_prepare_zero_transport_calls_writes_and_no_grant(tmp_path,capsys):
    s,t,m,cache,clock=setup(tmp_path)
    config=tmp_path/'isolated-config.json';config.write_text(json.dumps(s.config.model_dump(mode='json')))
    before={str(p):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    try:
        args=['--config',str(config),'--isolated-root',str(tmp_path),'--target','20261013',
            '--cutoff',clock().isoformat()]
        assert helper().main(args)==0
        proof=json.loads(capsys.readouterr().out)
        assert proof['state']=='PREPARED' and not proof['network_run'] and not proof['model_run']
        assert not proof['lease_auto_granted'] and not t.calls and not m.calls
        assert before=={str(p):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
        with pytest.raises(ValueError,match='EXPLICIT_NETWORK'):
            helper().main(args+['--execute-collect'])
        outside=tmp_path/'unrelated';outside.mkdir()
        with pytest.raises(ValueError,match='ALL_WRITES'):
            helper().main(['--config',str(config),'--isolated-root',str(outside),
                '--target','20261013','--cutoff',clock().isoformat()])
    finally:s.stop()
