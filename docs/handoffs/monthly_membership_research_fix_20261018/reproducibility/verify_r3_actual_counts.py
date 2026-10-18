#!/usr/bin/env python3
"""Read-only in-memory replay of the saved R2 run through the R3 lane API projection."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient


HANDOFF = Path(__file__).resolve().parents[1]
BUILD = json.loads((HANDOFF / "ROOT_API_RELEASE_BUILD.json").read_text())
APP_ROOT = Path(BUILD["candidate_app_root"]).resolve()
EXPECTED_MANIFEST_SHA256 = "b5023596734381d0773f258bfa458a7daa1dce8eef89803a06c849cadd474eae"
EXPECTED_BASE_DISPLAY_SHA256 = "585a1fde856c17650e2fd0b4e3cf05c46ca1389f569b1cfa62464e912d244089"
OVERLAY_ROOT = HANDOFF / "local_only/runtime_overlay_r3/app"
DISPLAY_PATH = OVERLAY_ROOT / "v4/manager_workbench/display_read.py"
UI_PATHS = {
    "workbench": OVERLAY_ROOT / "apps/web/src/manager-workbench/Workbench.vue",
    "types": OVERLAY_ROOT / "apps/web/src/manager-workbench/types.ts",
    "test": OVERLAY_ROOT / "apps/web/src/manager-workbench/__tests__/us_factor.spec.ts",
}
EXPECTED_R3_SHA256 = {
    "display_read.py": "87c2edf936146fdf4fd2f1e3d4742577272ed47734d883b896bb97d125a50a20",
    "Workbench.vue": "44643f793b080c0358e6d8c92b5ca9a8282d461a653fcbe438a07cd43733d088",
    "types.ts": "6de8a2d4763642d69c117224ede7a01a199ffe00992a5995f75cb9692985e56d",
    "us_factor.spec.ts": "efddf00312aa6b8372d4e2388416b1a151b3966b17b5035b1a76443028e2ad77",
}
RUN_ID = "2e2a1dbb1312422c8b1e21a58d2d44d0"
SNAPSHOT_PATH = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v4.local/state/manager_workbench/"
    f"manager_workbench/snapshots/{RUN_ID}.json"
)
SNAPSHOT_SHA256 = "388b4db4f4d46d7f926258ea872226243b9f121cd071e7ad6fb56aafb51cccbf"
BASELINE_LANE_RESPONSE = HANDOFF / "local_only/actual_r2/lane-response.json"
BASELINE_LANE_RESPONSE_SHA256 = "466bee06806340c4ad7fc7dd066201c5b9774a753379ff20c070c3642400bc59"
OUTPUT_PATH = HANDOFF / "local_only/r3_actual_count_canary.json"


def sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    manifest = Path(BUILD["candidate_root"]) / "release-manifest.json"
    if sha_file(manifest) != EXPECTED_MANIFEST_SHA256:
        raise ValueError("R3_API_CANDIDATE_MANIFEST_SHA_MISMATCH")
    base_display = APP_ROOT / "v4/manager_workbench/display_read.py"
    if sha_file(base_display) != EXPECTED_BASE_DISPLAY_SHA256:
        raise ValueError("R3_API_BASE_DISPLAY_SHA_MISMATCH")
    if sha_file(DISPLAY_PATH) != EXPECTED_R3_SHA256["display_read.py"]:
        raise ValueError("R3_DISPLAY_OVERLAY_SHA_MISMATCH")
    for name, path in UI_PATHS.items():
        if sha_file(path) != EXPECTED_R3_SHA256[Path(path).name]:
            raise ValueError(f"R3_UI_OVERLAY_SHA_MISMATCH:{name}")
    if sha_file(BASELINE_LANE_RESPONSE) != BASELINE_LANE_RESPONSE_SHA256:
        raise ValueError("R3_SAVED_BASELINE_LANE_RESPONSE_SHA_MISMATCH")
    raw = SNAPSHOT_PATH.read_bytes()
    if hashlib.sha256(raw).hexdigest() != SNAPSHOT_SHA256:
        raise ValueError("R3_SAVED_SNAPSHOT_SHA_MISMATCH")

    sys.path.insert(0, str(APP_ROOT))
    from v4.manager_workbench.contracts import PlanSnapshot

    spec = importlib.util.spec_from_file_location(
        "v4.manager_workbench.display_read", DISPLAY_PATH
    )
    if spec is None or spec.loader is None:
        raise ValueError("R3_DISPLAY_OVERLAY_IMPORT_UNAVAILABLE")
    display_read = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = display_read
    spec.loader.exec_module(display_read)
    if Path(display_read.__file__).resolve() != DISPLAY_PATH.resolve():
        raise ValueError("R3_DISPLAY_OVERLAY_ORIGIN_MISMATCH")

    from v4.manager_workbench.api import create_router

    snapshot = PlanSnapshot.model_validate(json.loads(raw))
    if snapshot.run_id != RUN_ID or snapshot.context.target_date != "20261020":
        raise ValueError("R3_SAVED_SNAPSHOT_IDENTITY_MISMATCH")
    original = json.loads(BASELINE_LANE_RESPONSE.read_text())["data"]
    if original["recommendation_projection"]["row_count"] != 60:
        raise ValueError("R3_SAVED_SOURCE_ROW_BASELINE_MISMATCH")

    store = type("ReadOnlySnapshotStore", (), {
        "get_plan": lambda self, *args, **kwargs: snapshot,
        "list_plans": lambda self, *args: [snapshot],
    })()
    service = type("ReadOnlyWorkbenchService", (), {
        "store": store,
        "config": type("ReadOnlyConfig", (), {"shared_root": None})(),
    })()
    app = FastAPI()
    app.include_router(create_router(service))
    response = TestClient(app).get(
        f"/api/v4/manager-workbench/days/20261020/recommendations/US_MAPPING",
        params={"run_id": RUN_ID},
    )
    if response.status_code != 200:
        raise ValueError(f"R3_IN_MEMORY_READBACK_HTTP_{response.status_code}")
    envelope = response.json()
    data = envelope["data"]
    projection = data["recommendation_projection"]
    counts = data["counts"]
    source_counts = projection["source_decision_counts"]
    expected_source_counts = {
        "selected": 0, "watch": 0, "unassessed": 27, "not_selected": 33,
        "observation_only": 0,
    }
    if counts["selected"] != 0 or counts["watch"] != 153:
        raise ValueError(f"R3_RECOMMENDATION_HEADLINE_MISMATCH:{counts}")
    if data["recommendation_counts"]["US_MAPPING"] != counts:
        raise ValueError("R3_RECOMMENDATION_COUNTS_DIVERGE_FROM_LANE_COUNTS")
    if projection["candidate_stock_count"] != 701 or sum(counts.values()) != 701:
        raise ValueError("R3_CANDIDATE_STOCK_COVERAGE_MISMATCH")
    if projection["recommendation_count_unit"] != "DEDUPLICATED_HK_CANDIDATE_STOCKS":
        raise ValueError("R3_RECOMMENDATION_COUNT_UNIT_MISMATCH")
    if projection["row_count"] != 60 or source_counts != expected_source_counts:
        raise ValueError(f"R3_SOURCE_ROW_COUNTS_NOT_PRESERVED:{source_counts}")
    if projection["catalog_relation_row_count"] != 1003:
        raise ValueError("R3_CATALOG_ROWS_ENTERED_OR_LEFT_CATALOG_SUMMARY")
    if data["pagination"]["total"] != 153 or len(data["stocks"]) != 50:
        raise ValueError("R3_DEFAULT_RECOMMENDATION_LIST_MISMATCH")
    if sha_file(SNAPSHOT_PATH) != SNAPSHOT_SHA256:
        raise ValueError("R3_SAVED_SNAPSHOT_CHANGED_DURING_READBACK")

    output = {
        "status": "PASS_READ_ONLY_SAVED_SNAPSHOT_IN_MEMORY_API_PROJECTION",
        "run_id": RUN_ID,
        "snapshot_path": str(SNAPSHOT_PATH),
        "snapshot_sha256": SNAPSHOT_SHA256,
        "api_candidate_app_root": str(APP_ROOT),
        "api_candidate_manifest_sha256": EXPECTED_MANIFEST_SHA256,
        "display_module_path": str(DISPLAY_PATH),
        "display_module_sha256": sha_file(DISPLAY_PATH),
        "ui_overlay_sha256": {name: sha_file(path) for name, path in UI_PATHS.items()},
        "baseline_lane_response_sha256": BASELINE_LANE_RESPONSE_SHA256,
        "http_status": response.status_code,
        "lane_state": envelope["state"],
        "recommendation_counts": data["recommendation_counts"]["US_MAPPING"],
        "candidate_counts": counts,
        "candidate_stock_count": projection["candidate_stock_count"],
        "candidate_count_unit": projection["recommendation_count_unit"],
        "source_row_count": projection["row_count"],
        "source_decision_counts": source_counts,
        "source_count_unit": projection["source_decision_count_unit"],
        "catalog_relation_row_count": projection["catalog_relation_row_count"],
        "recommendation_pagination": data["pagination"],
        "saved_pre_r3_lane_counts": original["counts"],
        "read_only": True,
        "service_or_job_called": False,
        "api_posted": False,
        "owner_data_written": False,
    }
    OUTPUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
