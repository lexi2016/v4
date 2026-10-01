"""No external I/O: fabricated HTTP responses only, real local original stores."""
import socket
import pytest
@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def deny(*a,**kw):
        raise AssertionError('UNEXPECTED_NETWORK_CALL')
    monkeypatch.setattr(socket,'create_connection',deny)
    monkeypatch.setattr(socket.socket,'connect',deny)
    monkeypatch.setattr(socket.socket,'connect_ex',deny)


def pytest_sessionfinish(session, exitstatus):
    import sys, os, json, hashlib
    from pathlib import Path
    target=os.environ.get("FINAL_IMPORT_RECEIPT")
    root=os.environ.get("FINAL_APP_ROOT")
    if not target or not root:return
    root=Path(root).resolve(); entries={}
    for name,module in list(sys.modules.items()):
        value=getattr(module,"__file__",None)
        if not isinstance(value,str):continue
        path=Path(value).resolve()
        if path.is_file() and path.is_relative_to(root):
            entries[name]={"path":str(path.relative_to(root)),"sha256":hashlib.sha256(path.read_bytes()).hexdigest()}
    with open(target,"x",encoding="utf-8") as f:
        json.dump({"root":str(root),"exit_code":exitstatus,"python":sys.version,"imports":entries},f,indent=2)
