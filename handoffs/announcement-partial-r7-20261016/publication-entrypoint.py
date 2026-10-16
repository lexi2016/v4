"""One-shot local publisher for the exact reviewed saved-partial job.

This entrypoint uses the candidate release's canonical ManagerService factory
and the current API LaunchAgent's non-credential configuration. It does not
connect to or start the API server, run ASGI lifespan, start scheduled lanes,
load model credentials, submit queue work, or invoke a model. The only intended
state writes are the prevalidated saved PARTIAL result artifact and its index
cursor, made by AnnouncementUpdate.materialize_failed_partial().

The parent must run this only after reviewing the bound R7b receipt and
candidate manifest. It is inert on import and requires both explicit flags.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import plistlib
import re
import sys
from pathlib import Path
from typing import Any

BUNDLE = Path(
    "/Users/lexi/Desktop/学习/agents调试/助手/qwen_flash_next_20261013/"
    "pipeline_canary/evidence/announcement-workbench-20261016/batch-recovery-1457"
)
PLIST_PATH = Path("/Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist")
CONFIG_PATH = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v4.local/config/"
    "us-hk-recovery-v2r1-20261016-r2.json"
)
ACTIVE_R6_APP = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/"
    "announcement-recovery-api-20261016-r6/app"
)
CANDIDATE_ROOT = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/"
    "announcement-partial-api-20261016-r7b"
)
CANDIDATE_APP = CANDIDATE_ROOT / "app"
CANDIDATE_MANIFEST = CANDIDATE_ROOT / "release-manifest.json"
CANDIDATE_MANIFEST_SHA256 = "92f67456a72966e88be3a3980e1c3988c1fedbcf14fb36acabd8729eb402f30d"
JOB_ID = "85add37723bf4c5ea1445dcb61202899"
FAILURE_CODE = "INTERNAL_QUEUE_PAYLOAD_IDEMPOTENCY_CONFLICT"
TARGET_DATE = "20261016"
RESULT_REF = f"announcement_flash/jobs/{JOB_ID}/result.json"
EXPECTED_CONFIG_STATE_ROOT = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v4.local/state/manager_workbench"
)
EXPECTED_STORE_ROOT = EXPECTED_CONFIG_STATE_ROOT / "manager_workbench"
EXPECTED_CAPTURE_ROOT = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v4.local/state/manager_workbench_capture"
)
SENSITIVE_NAME = re.compile(
    r"(?:^|_)(?:API_KEY|ACCESS_TOKEN|REFRESH_TOKEN|TOKEN|SECRET|PASSWORD|"
    r"CREDENTIAL|AUTHORIZATION|BEARER)(?:_|$)",
    re.IGNORECASE,
)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _launchagent_noncredential_environment() -> dict[str, str]:
    """Rebuild only the LaunchAgent's non-credential environment, never inherit it."""
    with PLIST_PATH.open("rb") as stream:
        plist = plistlib.load(stream)
    if plist.get("Label") != "com.lexi.v35.api-only":
        raise RuntimeError("API_LAUNCHAGENT_IDENTITY_MISMATCH")

    values: dict[str, str] = {}
    configured = plist.get("EnvironmentVariables", {})
    if isinstance(configured, dict):
        values.update({str(k): str(v) for k, v in configured.items()})
    arguments = plist.get("ProgramArguments", [])
    if not isinstance(arguments, list) or not arguments or arguments[0] != "/usr/bin/env":
        raise RuntimeError("API_LAUNCHAGENT_ENV_LAYOUT_MISMATCH")
    for item in arguments[1:]:
        if not isinstance(item, str) or "=" not in item:
            break
        key, value = item.split("=", 1)
        values[key] = value

    # Credential-shaped entries are deliberately omitted even if a future
    # LaunchAgent adds one. No ambient shell/terminal environment is inherited.
    values = {key: value for key, value in values.items() if not SENSITIVE_NAME.search(key)}
    if values.get("V35_APP_ROOT") != str(ACTIVE_R6_APP):
        raise RuntimeError("API_LAUNCHAGENT_ACTIVE_RELEASE_MISMATCH")
    if values.get("V4_MANAGER_WORKBENCH_CONFIG_PATH") != str(CONFIG_PATH):
        raise RuntimeError("API_LAUNCHAGENT_WORKBENCH_CONFIG_MISMATCH")
    required = (
        "V35_DATA_ROOT",
        "V35_SHARED_DATA_ROOT",
        "V35_STAGE_CENTER_SELECTION_ROOT",
        "V4_MANAGER_RESEARCH_STATE_ROOT",
    )
    if any(not values.get(key) for key in required):
        raise RuntimeError("API_LAUNCHAGENT_REQUIRED_ROOT_MISSING")
    for key, expected in {
        "RESEARCH_ONLY": "1",
        "production_allowed": "false",
        "PRODUCTION_ALLOWED": "false",
        "buy_gate_updated": "false",
        "BUY_GATE_UPDATED": "false",
        "orders_sent": "false",
        "ORDERS_SENT": "false",
    }.items():
        if values.get(key) != expected:
            raise RuntimeError("API_LAUNCHAGENT_RESEARCH_SAFETY_FLAG_MISMATCH")

    # Pin imports and all subprocess lookup to a minimal, local-only environment.
    values.update(
        {
            "HOME": "/Users/lexi",
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "HTTP_PROXY": "",
            "HTTPS_PROXY": "",
            "http_proxy": "",
            "https_proxy": "",
            "NO_PROXY": "*",
            "no_proxy": "*",
            "V35_APP_ROOT": str(CANDIDATE_APP),
            "V35_RELEASE_ID": CANDIDATE_ROOT.name,
            "V35_RELEASE_MANIFEST_PATH": str(CANDIDATE_MANIFEST),
            "V35_RELEASE_MANIFEST_SHA256": CANDIDATE_MANIFEST_SHA256,
            "V35_API_ROLE": "gateway",
            "PYTHONPATH": os.pathsep.join(
                (str(CANDIDATE_APP / "upstreams"), str(CANDIDATE_APP))
            ),
        }
    )
    if any(SENSITIVE_NAME.search(key) for key in values):
        raise RuntimeError("CREDENTIAL_ENVIRONMENT_NOT_EMPTY")
    return values


def _verify_candidate() -> None:
    if not CANDIDATE_APP.is_dir() or CANDIDATE_APP.is_symlink():
        raise RuntimeError("R7B_CANDIDATE_APP_UNAVAILABLE")
    manifest_raw = CANDIDATE_MANIFEST.read_bytes()
    if _sha(manifest_raw) != CANDIDATE_MANIFEST_SHA256:
        raise RuntimeError("R7B_CANDIDATE_MANIFEST_SHA_MISMATCH")
    manifest = json.loads(manifest_raw)
    candidate = manifest.get("candidate", {})
    if (
        candidate.get("app_root") != str(CANDIDATE_APP)
        or candidate.get("release_id") != CANDIDATE_ROOT.name
        or manifest.get("activation_status") != "NOT_ACTIVATED"
    ):
        raise RuntimeError("R7B_CANDIDATE_IDENTITY_MISMATCH")
    if not (CANDIDATE_APP / "apps/api/v35_api/app.py").is_file():
        raise RuntimeError("R7B_API_FACTORY_UNAVAILABLE")
    if not (CANDIDATE_APP / "v4/manager_workbench/service.py").is_file():
        raise RuntimeError("R7B_MANAGER_SERVICE_FACTORY_UNAVAILABLE")


def _assert_no_active_attempts(state_root: Path) -> None:
    attempts_root = state_root / "manager_workbench" / "attempts"
    if not attempts_root.exists():
        return
    if attempts_root.is_symlink():
        raise RuntimeError("ATTEMPT_ROOT_SYMLINK_DENIED")
    active: list[str] = []
    for path in attempts_root.glob("*.json"):
        if path.is_symlink():
            raise RuntimeError("ATTEMPT_ENTRY_SYMLINK_DENIED")
        try:
            value = json.loads(path.read_bytes())
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            raise RuntimeError("ATTEMPT_ENTRY_UNREADABLE") from None
        if isinstance(value, dict) and value.get("state") in {"QUEUED", "RUNNING"}:
            active.append(path.stem)
    if active:
        raise RuntimeError("ACTIVE_ATTEMPTS_PRESENT")


def _assert_service_binding(service: Any, *, store_root: Path, capture_root: Path) -> None:
    """Check only attributes present in the candidate ManagerService contract."""
    if (
        getattr(getattr(service, "store", None), "root", None) != store_root
        or getattr(getattr(service, "config", None), "capture_root", None) != capture_root
        or getattr(getattr(service, "config", None), "capture_enabled", True)
        or getattr(service, "oversold_daily", None) is not None
        or getattr(service, "capture_jobs", None) is not None
        or not callable(getattr(service, "stop", None))
    ):
        raise RuntimeError("MANAGER_WORKBENCH_SERVICE_BINDING_MISMATCH")


def _import_candidate() -> None:
    for entry in (str(CANDIDATE_APP / "upstreams"), str(CANDIDATE_APP)):
        if entry not in sys.path:
            sys.path.insert(0, entry)


def materialize_saved_partial() -> dict[str, Any]:
    _verify_candidate()
    env = _launchagent_noncredential_environment()
    os.environ.clear()
    os.environ.update(env)
    _import_candidate()

    from v4.manager_workbench.config import load_config
    from v4.manager_workbench.service import create_service
    from v4.manager_workbench.announcement_update import AnnouncementUpdate
    from v4.manager_workbench.contracts import JobState

    config = load_config(CONFIG_PATH)
    if (
        config.state_root != EXPECTED_CONFIG_STATE_ROOT
        or config.capture_root != EXPECTED_CAPTURE_ROOT
        or config.capture_enabled
    ):
        raise RuntimeError("MANAGER_WORKBENCH_CONFIG_ROOT_OR_CAPTURE_MISMATCH")
    # The local one-shot must not construct the scheduled-lane owner. All data
    # roots and research rules remain from the exact LaunchAgent config.
    config = config.model_copy(update={"scheduled_lanes": None})
    _assert_no_active_attempts(config.state_root)

    # This is the same create_service factory called by the release's
    # binding.assemble_api(); dependencies unused by saved-result publication are
    # None, making model/producer execution unavailable in this process.
    service = create_service(config, adapters=None, engines=None, executor=None)
    try:
        _assert_service_binding(
            service, store_root=EXPECTED_STORE_ROOT, capture_root=EXPECTED_CAPTURE_ROOT
        )
        job = service.jobs.get(JOB_ID)
        if (
            job.state != JobState.FAILED
            or job.failure_code != FAILURE_CODE
            or job.context.target_date != TARGET_DATE
            or (job.step != "FLASH_SELECTION" and "FLASH_SELECTION" not in job.failed_steps)
        ):
            raise RuntimeError("SAVED_PARTIAL_JOB_IDENTITY_MISMATCH")
        try:
            service.store.io.read_bytes(RESULT_REF, max_bytes=64 * 1024 * 1024)
        except FileNotFoundError:
            pass
        else:
            raise RuntimeError("SAVED_PARTIAL_RESULT_ALREADY_EXISTS")

        # Fail closed if a future code edit accidentally routes this invocation
        # into normal queue submission.
        def reject_queue_dispatch(*_args, **_kwargs):
            raise RuntimeError("QUEUE_DISPATCH_FORBIDDEN_IN_MATERIALIZER")

        service.jobs.submit = reject_queue_dispatch
        result = AnnouncementUpdate(service).materialize_failed_partial(JOB_ID)
        final_job = service.jobs.get(JOB_ID)
        materialization = result.get("materialization") if isinstance(result, dict) else None
        if (
            final_job.state != JobState.FAILED
            or final_job.failure_code != FAILURE_CODE
            or not isinstance(materialization, dict)
            or materialization.get("mode") != "SAVED_VALIDATED_QUEUE_ONLY"
            or materialization.get("failure_code") != FAILURE_CODE
            or materialization.get("queue_dispatches") != 0
            or materialization.get("model_calls") != 0
            or result.get("state") != "PARTIAL"
        ):
            raise RuntimeError("SAVED_PARTIAL_RESULT_POSTCONDITION_FAILED")
        result_raw = service.store.io.read_bytes(RESULT_REF, max_bytes=64 * 1024 * 1024)
        cursor = service.store.cursor("announcement_flash_result_index") or {"items": []}
        indexed = any(
            isinstance(item, dict)
            and item.get("job_id") == JOB_ID
            and item.get("target_date") == TARGET_DATE
            and item.get("result_sha256") == _sha(result_raw)
            for item in cursor.get("items", [])
        )
        if not indexed:
            raise RuntimeError("SAVED_PARTIAL_RESULT_INDEX_NOT_CONFIRMED")
        return {
            "status": "PARTIAL_PUBLISHED",
            "job_id": JOB_ID,
            "target_date": TARGET_DATE,
            "job_state": final_job.state.value,
            "job_failure_code": final_job.failure_code,
            "result_sha256": _sha(result_raw),
            "result_state": result.get("state"),
            "queue_dispatches": materialization.get("queue_dispatches"),
            "model_calls": materialization.get("model_calls"),
            "result_indexed": True,
        }
    finally:
        service.stop()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--publish-saved-partial",
        action="store_true",
        required=True,
        help="write the validated PARTIAL result and its result-index cursor",
    )
    parser.add_argument(
        "--confirm-job-id",
        required=True,
        choices=[JOB_ID],
        help="must name the one frozen failed job",
    )
    args = parser.parse_args()
    if args.confirm_job_id != JOB_ID:
        raise RuntimeError("SAVED_PARTIAL_JOB_IDENTITY_MISMATCH")
    print(json.dumps(materialize_saved_partial(), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
