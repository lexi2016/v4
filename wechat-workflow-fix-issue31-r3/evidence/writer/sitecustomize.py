"""Per-process network deny guard for all R3 writer evidence commands."""
from __future__ import annotations

import json
import os
import socket
from pathlib import Path
import urllib.request

LOG = Path(os.environ.get("ISSUE31_NETWORK_GUARD_LOG", "/tmp/issue31-network-guard.jsonl"))

def _blocked(*args, **kwargs):
    record = {"blocked": True, "function": getattr(_blocked, "label", "network"), "args": [str(x) for x in args[:3]]}
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    raise RuntimeError("network access blocked by Issue 31 offline evidence guard")

for _name in ("connect", "connect_ex", "sendto"):
    _fn = _blocked
    _fn.label = "socket.socket." + _name
    setattr(socket.socket, _name, _fn)
for _name in ("getaddrinfo", "gethostbyname", "gethostbyname_ex", "create_connection"):
    _fn = _blocked
    _fn.label = "socket." + _name
    setattr(socket, _name, _fn)
_blocked.label = "urllib.request.urlopen"
urllib.request.urlopen = _blocked
