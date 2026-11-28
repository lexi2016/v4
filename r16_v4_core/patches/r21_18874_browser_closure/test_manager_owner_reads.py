from datetime import datetime
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
from time import monotonic

from fastapi.testclient import TestClient

work = Path(__file__).resolve().parent
path = work / "candidate/content_projection/manager_owner_reads.py"
spec = importlib.util.spec_from_file_location("isolated_manager_owner_reads", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
prefix = module.PREFIX
started = monotonic()
client = TestClient(module.native_app())
results = {}


def read(case, route):
    start = monotonic()
    response = client.get(prefix + route)
    value = response.json()
    data = value.get("data") or {}
    snapshot = data.get("snapshot") or {}
    results[case] = {
        "status": response.status_code,
        "elapsed_ms": round((monotonic() - start) * 1000),
        "http_bytes": len(response.content),
        "state": value.get("state"),
        "gaps": value.get("gaps", [])[:10],
        "rows": len(data.get("stocks") or []),
        "total": (data.get("pagination") or {}).get("total"),
        "target_date": (snapshot.get("context") or {}).get("target_date") or snapshot.get("target_date"),
        "run_id": snapshot.get("run_id"),
        "product_sha256": snapshot.get("product_sha256"),
        "generated_at": snapshot.get("generated_at"),
        "first_row": ({field: data["stocks"][0].get(field) for field in ("symbol", "name", "row_id")}
                      if data.get("stocks") else None),
    }
    print(case, results[case]["status"], results[case]["elapsed_ms"], results[case]["state"], results[case]["rows"], flush=True)
    return response.status_code, data


def k(lane: str, date="20261127", suffix=""):
    return f"/days/{date}/recommendations/{lane}?limit=50{suffix}"


try:
    status, us = read("selected_d27_us", k("US_MAPPING", suffix="&view=compact"))
    assert status == 200 and us["snapshot"]["target_date"] == "20261127"
    assert us["snapshot"]["run_id"] == "9fe394240e73400aabbc86823c89feab"
    assert len(us["stocks"]) > 0
    status, oversold = read("warm_d27_oversold", k("OVERSOLD"))
    assert status == 200 and oversold["snapshot"]["run_id"] == us["snapshot"]["run_id"]
    status, history = read("d27_history_catalog", "/history?date=20261127")
    assert status == 200 and len(history["versions"]) > 3
    stock = us["stocks"][0]
    status, details = read("d27_stock_diagnostics", k("US_MAPPING", suffix=f"&view=diagnostics&symbol={stock['symbol']}&run_id={us['snapshot']['run_id']}"))
    assert status == 200 and details["snapshot"]["run_id"] == us["snapshot"]["run_id"]
    status, d30 = read("selected_d30_us", k("US_MAPPING", date="20261130", suffix="&view=compact"))
    assert status == 200 and d30["snapshot"]["target_date"] == "20261130"
    status, missing = read("d28_closed_day_exact", k("US_MAPPING", date="20261128"))
    assert status == 200 and missing["snapshot"] is None and missing["stocks"] == []
    assert {route.path for route in client.app.router.routes} == module.NATIVE_READS | {prefix + "/history"}
    status = "PASS"
except Exception as exc:
    status = "FAIL:" + repr(exc)[:300]
finally:
    receipt = {"status": status, "elapsed_ms": round((monotonic()-started)*1000),
               "module_sha256": sha256(path.read_bytes()).hexdigest(), "observed_at": datetime.now().astimezone().isoformat(),
               "results": results, "scope": "read-only direct ASGI, no browser claim"}
    (work / "MANAGER_READS_RECEIPT.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    print(status, flush=True)
    if status != "PASS":
        raise SystemExit(1)
