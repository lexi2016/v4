"""TEST ONLY: temporary SDK response fixtures, not another producer or installed SDK.

No runtime module imports this helper. The actual panel, sync, codecs, updater,
registry and ledger run unchanged; only external SDK responses are synthetic.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import textwrap


def transport_environment(root: Path, repo: Path) -> dict[str, str]:
    files = {
        "pytdx/__init__.py": "import fixture_guard\n",
        "pytdx/config/__init__.py": "",
        "pytdx/config/hosts.py": 'hq_hosts = [("OFFLINE_FIXTURE", "fixture.invalid", 7710)]\n',
        "pytdx/errors.py": 'class TdxFunctionCallError(Exception):\n    pass\n',
        "pytdx/hq.py": '''
            import json, os, time
            from pathlib import Path
            def record(event, **data):
                with Path(os.environ["V4_FIXTURE_CALLS"]).open("a") as f:
                    f.write(json.dumps({"fixture": True, "event": event, **data}) + "\\n")
            class TdxHq_API:
                def __init__(self, **kwargs):
                    record("session", kwargs=kwargs)
                def connect(self, host, port, time_out=None):
                    assert host == "fixture.invalid" and port == 7710
                    record("connect", host=host, port=port)
                    return True
                def get_security_bars(self, kline, market, code, start, count):
                    record("bars", code=code, market=market, count=count)
                    time.sleep(float(os.environ.get("V4_FIXTURE_DELAY", "0")))
                    rows = json.loads(os.environ["V4_FIXTURE_BARS"])
                    return rows
                def disconnect(self):
                    record("disconnect")
        ''',
        "futu.py": '''
            import fixture_guard
            import json, os
            from pathlib import Path
            def record(event, **data):
                with Path(os.environ["V4_FIXTURE_CALLS"]).open("a") as f:
                    f.write(json.dumps({"fixture": True, "event": event, **data}) + "\\n")
            class OpenQuoteContext:
                def __init__(self, host, port):
                    record("futu_fixture_context", host=host, port=port)
                def get_plate_stock(self, plate):
                    record("plate", plate=plate)
                    return 0, [{"code": "HK.%05d" % n, "name": "OFFLINE_FIXTURE"} for n in range(1, 601)]
                def get_market_snapshot(self, codes):
                    record("snapshot", codes=len(codes))
                    return 0, [{"code": code, "update_time": "2026-09-11 16:10:00",
                                "open_price": 10, "high_price": 11, "low_price": 9,
                                "last_price": 10.5, "volume": 100, "turnover": 1000} for code in codes]
                def close(self):
                    record("futu_close")
        ''',
        "fixture_guard.py": '''
            import atexit, json, os, sys
            from pathlib import Path
            def audit(event, args):
                if event in {"socket.connect", "socket.connect_ex", "socket.getaddrinfo", "socket.gethostbyname", "socket.sendto"}:
                    raise PermissionError("OFFLINE_FIXTURE_NETWORK_FORBIDDEN")
                if event == "subprocess.Popen" and any(x in str(args[0]) for x in ("launchctl", "systemctl")):
                    raise PermissionError("SERVICE_CONTROL_FORBIDDEN")
            sys.addaudithook(audit)
            def record_modules():
                observed = sorted(n for n in sys.modules if n in {
                    "macos_windows_a_sync_authority", "shared_data.hk_0_2", "pytdx.hq", "futu"})
                with Path(os.environ["V4_FIXTURE_MODULES"]).open("a") as f:
                    f.write(json.dumps({"pid": os.getpid(), "modules": observed, "argv": sys.argv,
                                        "network_guard": True, "fixture": True}) + "\\n")
            atexit.register(record_modules)
        ''',
    }
    root.mkdir(parents=True)
    for relative, source in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(source).lstrip())
    import sys
    wrapper = root / "guarded-python"
    wrapper.write_text("#!" + sys.executable + "\n" +
        "import sys, runpy\n" + "sys.path.insert(0, " + repr(str(root)) + ")\n" +
        "import fixture_guard\n" +
        "target = sys.argv.pop(1)\n" +
        "if target == '-c': exec(sys.argv.pop(1))\n" +
        "else: sys.argv[0] = target; runpy.run_path(target, run_name='__main__')\n")
    wrapper.chmod(0o700)
    environment = os.environ.copy()
    environment.update({"PYTHONPATH": os.pathsep.join([str(root), str(repo), str(repo / "upstreams/v3_shared_data")]),
                        "PYTHONDONTWRITEBYTECODE": "1", "RESEARCH_ONLY": "1",
                        "V4_FIXTURE_PYTHON": str(wrapper),
                        "V4_FIXTURE_CALLS": str(root / "calls.jsonl"), "V4_FIXTURE_MODULES": str(root / "modules.jsonl"),
                        "production_allowed": "false", "buy_gate_updated": "false", "orders_sent": "false"})
    return environment


def bar(date: int, close: float) -> dict:
    return dict(year=date//10000, month=date//100%100, day=date%100, open=close-.2,
                high=close+.2, low=close-.4, close=close, amount=1000.0, vol=100.0)


def read_lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def file_fact(path: Path, root: Path) -> dict:
    raw = path.read_bytes()
    return {"path": str(path.relative_to(root)), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def record_evidence(name: str, evidence: dict) -> None:
    # The test runner, not runtime code, supplies a separate verification root.
    destination = os.environ.get("V4_CANDIDATE_EVIDENCE_DIR")
    if destination:
        root = Path(destination)
        if not root.is_absolute():
            raise ValueError("evidence root must be explicit and absolute")
        root.mkdir(parents=True, exist_ok=True)
        (root / (name + ".json")).write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n")
