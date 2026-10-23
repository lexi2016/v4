"""Bounded author integration check against existing saved records; no listener."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import resource
import subprocess
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import httpx

from .gateway import create_app
from .saved_reader import Bindings, SavedFiles, SavedReader

# Public fixture, not a generated or deployed secret.
FIXTURE_TOKEN = "test-only-placeholder-never-deploy-0000"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def listeners():
    result = subprocess.run(["lsof", "-nP", "-iTCP:8873", "-sTCP:LISTEN", "-Fp"], capture_output=True, text=True)
    return sorted(int(line[1:]) for line in result.stdout.splitlines() if line.startswith("p"))


async def verify(bindings, day, announcement_day):
    before_listener = listeners()
    started = time.monotonic()
    touched = {}
    original_read = SavedFiles.read

    def audited_read(self, relative, maximum=64 * 1024 * 1024):
        obj, raw = original_read(self, relative, maximum)
        key = (self.root, relative)
        first = touched.setdefault(key, sha(raw))
        assert first == sha(raw), "SOURCE_CHANGED_DURING_AUTHOR_CHECK"
        return obj, raw

    SavedFiles.read = audited_read
    checks = []
    try:
        app = create_app(SavedReader(bindings), lambda: FIXTURE_TOKEN)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://local-test") as client:
            headers = {"Authorization": "Bearer " + FIXTURE_TOKEN}
            for market, pool_id in [("A", "a_share_research_recommendation_pool"), ("HK", "hkconnect_d1_top100")]:
                artifact = bindings.pool_root / f"preselection_pools/{day}/{pool_id}.json"
                raw = artifact.read_bytes()
                expected = json.loads(raw)
                rows, offset = [], 0
                while True:
                    params = {"trade_date": day, "market": market, "pool_id": pool_id, "limit": 50, "offset": offset}
                    response = await client.get("/v1/pools?" + urlencode(params), headers=headers)
                    assert response.status_code == 200, (response.status_code, response.text)
                    data = response.json()
                    assert data["trade_date"] == expected["trade_date"] and data["market"] == expected["market"]
                    assert data["coverage"]["total"] == len(expected["rows"])
                    assert data["source"][0]["artifact_sha256"] == sha(raw)
                    assert data["source"][0]["source_sha256"] == expected["source_sha256"]
                    assert data["version"]["source_schema"] == expected["schema_version"]
                    rows.extend(data["rows"])
                    offset = data["coverage"]["next_offset"]
                    if offset is None:
                        break
                assert len(rows) == len(expected["rows"])
                for actual, source in zip(rows, expected["rows"], strict=True):
                    assert actual["symbol"] == source["symbol"]
                    assert actual["name"] == (source.get("name") or source.get("stock_name"))
                checks.append({"check": "real_saved_pool", "market": market, "trade_date": day,
                               "pool_id": pool_id, "rows_compared": len(rows),
                               "source_artifact_sha256": sha(raw), "source_version": data["version"],
                               "result_status": data["status"], "result": "PASS"})
            pointer = json.loads((bindings.workbench_root / f"pointers/{day}/INTRADAY.json").read_bytes())
            snapshot_raw = (bindings.workbench_root / f"snapshots/{pointer['run_id']}.json").read_bytes()
            snapshot = json.loads(snapshot_raw)
            original = snapshot["stocks"][0]
            query = urlencode({"trade_date": day, "market": "HK", "phase": "INTRADAY"})
            response = await client.get(f"/v1/stocks/{original['symbol']}/research?{query}", headers=headers)
            assert response.status_code == 200, (response.status_code, response.text)
            data = response.json()
            assert data["trade_date"] == snapshot["context"]["target_date"]
            assert data["version"]["rules"] == snapshot["context"]["rules_version"]
            assert data["source"][0]["product_sha256"] == pointer["product_sha256"]
            assert data["source"][0]["artifact_sha256"] == sha(snapshot_raw)
            for key in ("symbol", "name", "decision", "reasons", "risks", "conditions", "invalidation_conditions"):
                assert data["rows"][0][key] == original[key], key
            checks.append({"check": "real_saved_stock_research", "trade_date": day,
                           "rows_compared": 1, "plan_run_id": pointer["run_id"],
                           "source_product_sha256": pointer["product_sha256"],
                           "result_status": data["status"], "result": "PASS"})
            index = json.loads((bindings.workbench_root / "cursors/announcement_flash_delivery_index.json").read_bytes())
            entry = [v for v in index["items"] if v["target_date"] == announcement_day][-1]
            base = bindings.workbench_root / f"announcement_flash/jobs/{entry['job_id']}/deliveries"
            binding = json.loads((base / "latest.json").read_bytes())
            expected = json.loads((base / (binding["sha256"] + ".json")).read_bytes())
            response = await client.get("/v1/announcements?" + urlencode({"trade_date": announcement_day, "market": "HK", "limit": 50}), headers=headers)
            assert response.status_code == 200, (response.status_code, response.text)
            data = response.json()
            assert data["trade_date"] == expected["target_trade_date"]
            assert data["coverage"]["total"] == len(expected["stocks"]) == len(data["rows"])
            assert data["source"][0]["artifact_sha256"] == binding["sha256"]
            assert data["status"] == "unknown" and data["as_of"] is None
            for actual, source in zip(data["rows"], expected["stocks"], strict=True):
                for key in ("symbol", "name", "reasons"):
                    assert actual[key] == source[key]
                assert len(actual["articles"]) == len(source["articles"])
                for article, source_article in zip(actual["articles"], source["articles"], strict=True):
                    for key in ("article_id", "title", "source_date", "source_sha256", "body_sha256"):
                        assert article[key] == source_article[key]
            checks.append({"check": "real_saved_announcement", "trade_date": announcement_day,
                           "rows_compared": len(data["rows"]), "source_artifact_sha256": binding["sha256"],
                           "result_status": data["status"], "result": "PASS"})
            missing = await client.get("/v1/pools?" + urlencode({"trade_date": "19000101", "market": "A", "pool_id": "a_share_research_recommendation_pool"}), headers=headers)
            assert missing.status_code == 404 and missing.json()["status"] == "unavailable"
            checks.append({"check": "exact_missing_date_no_fallback", "result": "PASS"})
        for (root, relative), expected_hash in touched.items():
            raw = (root / relative).read_bytes()
            assert sha(raw) == expected_hash, "SOURCE_BYTES_CHANGED"
        assert listeners() == before_listener and before_listener, "V4_LISTENER_CHANGED"
        return {"recorded_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
                "scope": "AUTHOR_IN_PROCESS_ASGI_AND_SAVED_RECORD_CHECKS",
                "independent_review": "NOT_RUN_USER_PROHIBITS_NEW_OR_DELEGATED_TASKS",
                "public_https": "NOT_RUN", "consumer_tool_call": "NOT_RUN",
                "checks": checks, "result": "PASS", "v4_listener_pids_unchanged": before_listener,
                "source_files_compared_unchanged": len(touched),
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "max_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                "source_hashes": [{"family": "pools" if root == bindings.pool_root else "manager",
                                   "relative": relative, "sha256": value}
                                  for (root, relative), value in touched.items()]}
    finally:
        SavedFiles.read = original_read


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pool-root", type=Path, required=True)
    parser.add_argument("--workbench-root", type=Path, required=True)
    parser.add_argument("--trade-date", required=True)
    parser.add_argument("--announcement-date", required=True)
    args = parser.parse_args()
    report = asyncio.run(verify(Bindings(args.pool_root, args.workbench_root), args.trade_date, args.announcement_date))
    directory = Path(__file__).with_name("local_only")
    directory.mkdir(exist_ok=True)
    output = directory / "real_saved_verification.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"result": report["result"], "checks": report["checks"],
                      "unchanged_files": report["source_files_compared_unchanged"],
                      "elapsed_seconds": report["elapsed_seconds"], "report": str(output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
