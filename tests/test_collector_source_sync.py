"""Accepted collector source closure: CLI wiring and finite HTTP body boundary."""
import io
import json
from types import SimpleNamespace

import pytest

from infrastructure.runtime_graph import current, event_collector, http_client
from ops import collect_runtime_graph as cli


def test_events_cli_imports_existing_current_abi_and_preserves_date_cli(tmp_path, monkeypatch):
    for name in ('FLAGS', 'SCHEMA', 'atomic_json', 'read_json', 'safe', 'sha', 'state_root'):
        assert getattr(event_collector, name) is getattr(current, name)
    calls = []
    config = {'synthetic': True}
    get = lambda path: pytest.fail('CLI wiring must not call a provider')
    monkeypatch.setattr(current, 'load_config', lambda path: config)
    monkeypatch.setattr(http_client, 'make_http_get', lambda base: get)
    monkeypatch.setattr(cli, 'make_http_get', lambda base: get)
    def events(cfg, fetch, **kwargs):
        calls.append(('events', cfg, fetch, kwargs))
        return {'status': 'PUBLISHED'}
    monkeypatch.setattr(event_collector, 'collect_events', events)
    assert cli.main(['--events', '--initialize', '--date', '20261029', '--config',
                     str(tmp_path / 'config.json'), '--data-root', str(tmp_path)]) == 0
    assert calls == [('events', config, get, {'initialize': True, 'business_date': '20261029'})]
    def legacy(**kwargs):
        calls.append(('legacy', kwargs['business_date']))
        return {'status': 'PASS', 'snapshot_published': True, 'events_recorded': True}
    monkeypatch.setattr(cli, 'collect_once', legacy)
    assert cli.main(['--date', '20261028', '--data-root', str(tmp_path)]) == 0
    assert calls[-1] == ('legacy', '20261028')


@pytest.mark.parametrize('size,declared,accepted', [
    (2_652_719, True, True),
    (4 * 1024 * 1024 + 1, True, False),
    (4 * 1024 * 1024 + 1, False, False),
])
def test_http_accepts_known_dto_size_and_rejects_over_4mib(monkeypatch, size, declared, accepted):
    raw = json.dumps({'padding': 'x' * (size - len(b'{"padding": ""}'))}).encode()
    assert len(raw) == size
    target = 'http://127.0.0.1:8873/api/v4/runtime-graph/authorities?date=20261029'
    class Response(io.BytesIO):
        headers = {'Content-Length': str(size)} if declared else {}
        def geturl(self):
            return target
    monkeypatch.setattr(http_client.urllib.request, 'build_opener',
                        lambda *args: SimpleNamespace(open=lambda *a, **kw: Response(raw)))
    get = http_client.make_http_get('http://127.0.0.1:8873')
    if accepted:
        assert len(get('/api/v4/runtime-graph/authorities?date=20261029')['padding']) > 2 * 1024 * 1024
    else:
        with pytest.raises(ValueError, match='API_BODY_TOO_LARGE'):
            get('/api/v4/runtime-graph/authorities?date=20261029')
