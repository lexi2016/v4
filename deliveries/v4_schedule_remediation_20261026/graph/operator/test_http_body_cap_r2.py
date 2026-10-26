"""Only graph HTTP transport size admission; no sockets or business producer."""
from pathlib import Path
import hashlib
import importlib.util
import io
import json
from types import SimpleNamespace

import pytest

CASE=Path(__file__).resolve().parent
SCOPE=json.loads((CASE/'R2_SCOPE.json').read_text())
SOURCE=Path(SCOPE['allowed_source_files'][0])
TARGET='http://127.0.0.1:8873/api/v3/preselection-pools?date=20261026&limit=200'


def helper():
    spec=importlib.util.spec_from_file_location('graph_r2_http_client',SOURCE)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def transport(monkeypatch,module,raw,declared):
    observed=SimpleNamespace(read_sizes=[],open_calls=0,timeouts=[])
    class Response(io.BytesIO):
        def __init__(self):
            super().__init__(raw)
            self.headers={} if declared is None else {'Content-Length':str(declared)}
        def geturl(self):return TARGET
        def read(self,size):
            observed.read_sizes.append(size)
            return super().read(size)
    class Opener:
        def open(self,request,timeout):
            assert request.full_url==TARGET
            assert request.get_method()=='GET'
            observed.open_calls+=1;observed.timeouts.append(timeout)
            return Response()
    monkeypatch.setattr(module.urllib.request,'build_opener',lambda *args:Opener())
    return observed


@pytest.mark.parametrize('content_length',[True,False])
def test_real_2652719_byte_dto_is_read_whole_with_status_preserved(monkeypatch,content_length):
    module=helper();raw=(CASE/'R2_DTO_20261026.json').read_bytes()
    assert len(raw)==2652719
    assert hashlib.sha256(raw).hexdigest()=='39c6d12d4bcec334d38398ddd024714f49ffae62f937cf5b012066cec0fdb507'
    seen=transport(monkeypatch,module,raw,len(raw) if content_length else None)
    result=module.make_http_get('http://127.0.0.1:8873')(TARGET.removeprefix('http://127.0.0.1:8873'))
    assert result==json.loads(raw)
    assert result['data_status']=='PARTIAL_WITH_ROWS'
    assert seen.open_calls==1 and seen.timeouts==[3.0]
    assert seen.read_sizes==[4*1024*1024+1]


def test_declared_body_over_four_mib_rejected_before_read(monkeypatch):
    module=helper();seen=transport(monkeypatch,module,b'{}',4*1024*1024+1)
    with pytest.raises(ValueError,match='^API_BODY_TOO_LARGE$'):
        module.make_http_get('http://127.0.0.1:8873')(TARGET.removeprefix('http://127.0.0.1:8873'))
    assert seen.open_calls==1 and seen.read_sizes==[]


def test_streamed_body_over_four_mib_rejected_with_bounded_read(monkeypatch):
    module=helper();raw=b'{"blob":"'+b'x'*(4*1024*1024)+b'"}'
    seen=transport(monkeypatch,module,raw,None)
    with pytest.raises(ValueError,match='^API_BODY_TOO_LARGE$'):
        module.make_http_get('http://127.0.0.1:8873')(TARGET.removeprefix('http://127.0.0.1:8873'))
    assert seen.open_calls==1 and seen.read_sizes==[4*1024*1024+1]


def test_exact_four_mib_mapping_is_admitted(monkeypatch):
    module=helper();prefix=b'{"blob":"';suffix=b'"}'
    raw=prefix+b'x'*(4*1024*1024-len(prefix)-len(suffix))+suffix
    seen=transport(monkeypatch,module,raw,len(raw))
    result=module.make_http_get('http://127.0.0.1:8873')(TARGET.removeprefix('http://127.0.0.1:8873'))
    assert len(result['blob'])==4*1024*1024-len(prefix)-len(suffix)
    assert seen.read_sizes==[4*1024*1024+1]


def test_larger_non_mapping_json_still_rejected(monkeypatch):
    module=helper();raw=b'["'+b'x'*(2652719-4)+b'"]'
    transport(monkeypatch,module,raw,len(raw))
    with pytest.raises(ValueError,match='^API_UNAVAILABLE$'):
        module.make_http_get('http://127.0.0.1:8873')(TARGET.removeprefix('http://127.0.0.1:8873'))
