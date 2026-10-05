from __future__ import annotations

"""R3 R17 -> R18 switch wrapper; --preflight never contacts the service."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from typing import Any
import urllib.parse


R17_ID = "manager-us-mapping-r17-20261006-page-r1"
R18_ID = "hk-day24-stage0930-r18-20261006-api-r1"
RELEASES = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/releases")
R17_ROOT = RELEASES / R17_ID
R18_ROOT = RELEASES / R18_ID
R17_SHA = "1e40c351b50c40b8ef997ffc71298f8f9160f82d54d8a3b98d1150f9fa07559c"
R18_SHA = "ceafc0ae313b4016142e90bd84fea64885cbf54de886916ab5ec301f85244151"
EXPECTED_OLD_PID = 60616
DAY24_RUN_ID = "1d3ab9f9bd3a44c3811bf1fed2b74108"
DAY24_SELECTION_ID = "run-1f781dcc3ea56ab3c3e97c70"
STAGE = "STAGE_0930_0935"
EVIDENCE = Path(__file__).resolve().parent
SPECS = EVIDENCE / "r18_launch_specs_r3.json"
SPECS_SHA = "49d6fd6d8f013bed462028c03c0ae209dd139b22a0e2f3246b1d8b85c6c36837"
SWITCH_HELPER = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/"
    "manager-announcement-r14-20261005-page-results-r1/evidence/r14_process_switch.py"
)
SWITCH_HELPER_SHA = "33abca8a143289fcc1391f141fe202ffe7622218371189ad1dec36accf03bff7"
SWITCH_RECEIPT = EVIDENCE / "r18_direct_process_switch_receipt_r3.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_specs(module: Any) -> tuple[Any, Any]:
    if _sha(SPECS) != SPECS_SHA:
        raise ValueError("frozen R18 launch spec SHA changed")
    if _sha(R17_ROOT / "release-manifest.json") != R17_SHA:
        raise ValueError("R17 rollback manifest SHA changed")
    if _sha(R18_ROOT / "release-manifest.json") != R18_SHA:
        raise ValueError("R18 candidate manifest SHA changed")
    payload = json.loads(SPECS.read_text(encoding="utf-8"))
    specs = []
    for key, release_id, manifest_sha, root in (
        ("old", R17_ID, R17_SHA, R17_ROOT),
        ("new", R18_ID, R18_SHA, R18_ROOT),
    ):
        item = payload[key]
        if (item.get("release_id") != release_id or item.get("manifest_sha") != manifest_sha
                or item.get("app_root") != str(root / "app") or item.get("cwd") != str(root / "app")):
            raise ValueError(f"frozen {key} launch identity mismatch")
        specs.append(module.LaunchSpec(
            release_id=release_id,
            manifest_sha=manifest_sha,
            app_root=str(root / "app"),
            cwd=item["cwd"],
            argv=tuple(item["argv"]),
            stdout=item["stdout"],
            stderr=item["stderr"],
        ))
    return specs[0], specs[1]


def _load_switch():
    if _sha(SWITCH_HELPER) != SWITCH_HELPER_SHA:
        raise ValueError("reviewed R14 switch helper SHA changed")
    spec = importlib.util.spec_from_file_location("_reviewed_r14_switch_for_r18", SWITCH_HELPER)
    if spec is None or spec.loader is None:
        raise ImportError("reviewed R14 switch helper cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.R13_ID, module.R14_ID = R17_ID, R18_ID
    module.R13_ROOT, module.R14_ROOT = R17_ROOT, R18_ROOT
    module.R13_SHA, module.R14_SHA = R17_SHA, R18_SHA
    module.RECEIPT = SWITCH_RECEIPT
    return module


def _api_acceptance(ops: Any) -> dict[str, Any]:
    query = urllib.parse.urlencode({"date": "20260924", "stage": STAGE, "limit": "50"})
    stage = ops.get_json("/api/v3/workbench/stage?" + query) or {}
    markets = stage.get("markets") or {}
    a, hk = markets.get("A") or {}, markets.get("HK") or {}
    hk_rows = hk.get("rows") or []
    if (stage.get("RESEARCH_ONLY") is not True or set(markets) != {"A", "HK"}
            or any(stage.get(k) is not False for k in ("production_allowed", "buy_gate_updated", "orders_sent"))
            or a.get("run_id") != "run-867d2ad77f83abfe25d612bb"
            or (a.get("requested_rows"), a.get("source_rows"), len(a.get("rows") or [])) != (193, 189, 10)
            or hk.get("backfill_run_id") != DAY24_RUN_ID or hk.get("run_id") != DAY24_SELECTION_ID
            or (hk.get("requested_rows"), hk.get("source_rows"), hk.get("observation_count"), len(hk_rows)) != (100, 100, 10, 10)
            or hk.get("display_mode") != "OBSERVATION_UNVERIFIED" or hk.get("runner_receipt_verified") is not True
            or hk.get("RESEARCH_ONLY") is not True
            or any(k in hk and hk.get(k) is not False for k in ("production_allowed", "buy_gate_updated", "orders_sent"))
            or any(r.get("action_level") != "NO_BUY" or r.get("formal_eligible") is not False for r in hk_rows)
            or stage.get("market_readback_bindings", {}).get("single_bundle_artifact_id") is not None
            or (stage.get("execution_evidence") or {}).get("execution_verified") is not False
            or (stage.get("execution_evidence") or {}).get("natural_verified") is not False):
        raise RuntimeError("R18 same-page Stage API acceptance failed")

    workspace = ops.get_json(
        "/api/v4/manager/research/workspace?" + urllib.parse.urlencode({"date": "20260930", "view": "auto"})
    ) or {}
    mapping = workspace.get("us_mapping_research") or {}
    reviewed = mapping.get("reviewed_research") or {}
    cards = reviewed.get("cards") or []
    counts = {
        "priority": sum(c.get("research_priority") == "PRIORITY" for c in cards if isinstance(c, dict)),
        "watch": sum(c.get("research_priority") == "WATCH" for c in cards if isinstance(c, dict)),
    }
    if (workspace.get("RESEARCH_ONLY") is not True
            or any(workspace.get(k) is not False for k in ("production_allowed", "buy_gate_updated", "orders_sent"))
            or mapping.get("target_trade_date") != "20260930"
            or reviewed.get("status") != "REVIEWED_RETROSPECTIVE_RESEARCH"
            or len(cards) != 5 or counts != {"priority": 3, "watch": 2}
            or (mapping.get("daily_run") or {}).get("status") != "NOT_RUN"):
        raise RuntimeError("R18 preserved US mapping API acceptance failed")
    return {
        "same_page_stage": {"markets": ["A", "HK"], "a_rows": 10, "hk_observations": len(hk_rows),
                            "hk_backfill_run_id": DAY24_RUN_ID, "display_mode": hk.get("display_mode")},
        "us_mapping": {"target_trade_date": "20260930", "cards": len(cards), **counts,
                       "daily_run_status": (mapping.get("daily_run") or {}).get("status")},
        "safety_flags_false": True,
        "execution_verified": False,
        "natural_verified": False,
    }


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args not in (["--preflight"], ["--execute"]):
        print("usage: r18_process_switch_r3.py --preflight|--execute", file=sys.stderr)
        return 2
    try:
        module = _load_switch()
        old, new = _load_specs(module)
        if args == ["--preflight"]:
            print(json.dumps({"status": "PRECHECK_PASSED_PENDING_ROOT_SWITCH_AUTH",
                              "rollback_release": R17_ID, "candidate_release": R18_ID,
                              "launch_spec_sha256": SPECS_SHA}, sort_keys=True))
            return 0

        os.environ.update({"NO_PROXY": "*", "no_proxy": "*", "HTTP_PROXY": "", "HTTPS_PROXY": "",
                           "http_proxy": "", "https_proxy": ""})
        class PinnedOps(module.ProcessOps):
            def __init__(self):
                self.allowed_pids = {EXPECTED_OLD_PID}

            def listeners(self):
                rows = super().listeners()
                if len(rows) > 1 or (rows and rows[0]["pid"] not in self.allowed_pids):
                    raise module.SwitchError(f"unexpected listener outside R17/R18 switch: {rows}")
                return rows

            def launch(self, spec):
                process = super().launch(spec)
                self.allowed_pids.add(process.pid)
                return process

        module.ProcessOps = PinnedOps
        module.verify_apis = _api_acceptance
        module._build_specs = lambda: (old, new, {"launch_specs_sha256": SPECS_SHA,
                                                  "rollback_release": R17_ID,
                                                  "candidate_release": R18_ID})
        return module.main(["--execute"])
    except Exception as error:
        print(json.dumps({"status": "PRECHECK_FAILED", "error": f"{type(error).__name__}: {error}"}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
