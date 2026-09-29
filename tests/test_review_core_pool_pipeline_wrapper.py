from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest


CANDIDATE_ROOT = Path("/Users/lexi/Documents/Codex/2026-08-13/v35-stage-selection-20260821-fix")
APP_ROOT = CANDIDATE_ROOT / "release-candidate" / "app"
WRAPPER_PATH = APP_ROOT / "ops" / "run_review_core_pool_pipeline.py"
CANARY_ROOT = CANDIDATE_ROOT / "test-tmp" / "fupan-pipeline" / "wrapper-tests"
FORMAL_REVIEW_CORE_ROOT = Path(
    "/Users/lexi/Library/Application Support/com.lexi.review-core.local/app"
)
CALENDAR_PATH = APP_ROOT / "contracts" / "market_calendar_2026.json"
SAFETY_FLAGS = ("production_allowed", "buy_gate_updated", "orders_sent")


def _load_wrapper() -> ModuleType:
    spec = importlib.util.spec_from_file_location("review_core_pool_pipeline_wrapper", WRAPPER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


wrapper = _load_wrapper()


def _request_kwargs(root: Path = CANARY_ROOT) -> dict[str, object]:
    return {
        "review_core_package_root": FORMAL_REVIEW_CORE_ROOT,
        "runtime_root": root / "runtime",
        "shared_root": root / "shared-package",
        "hk_root": root / "hk-store",
        "close_root": root / "close-source",
        "fupan_store_root": root / "fupan-store",
        "stage7_store_root": root / "stage7-store",
        "bundle_root": root / "bundle-source",
        "shared_store_root": root / "shared-store",
        "trade_date": "20260821",
        "previous_trade_date": "20260820",
        "target_date": "20260824",
        "calendar_path": CALENDAR_PATH,
    }


def _request(root: Path = CANARY_ROOT):
    return wrapper.validate_request(**_request_kwargs(root))


def _workload(status: str, name: str) -> dict[str, object]:
    result: dict[str, object] = {"status": status}
    if status == "READY":
        result.update(
            {
                "run_id": f"run-{name}",
                "artifact_sha256": "a" * 64,
                "manifest_sha256": "b" * 64,
                "receipt_sha256": "c" * 64,
            }
        )
    return result


def _official_result(
    *,
    workloads: dict[str, dict[str, object]] | None = None,
    status: str = "READY",
    safety: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "schema": "review_core.pool_pipeline.receipt.v1",
        "run_id": "20260821-review_core_pools_2115-test",
        "receipt_path": str(CANARY_ROOT / "runtime" / "pool_pipeline" / "receipt.json"),
        "status": status,
        "workloads": workloads
        or {
            "hk_close_review": _workload("READY", "hk"),
            "fupan_pool": _workload("READY", "fupan"),
            "stage7_pool": _workload("READY", "stage7"),
        },
        **(safety or {name: False for name in SAFETY_FLAGS}),
    }


def test_request_freezes_dates_roots_command_and_shared_data_environment() -> None:
    request = _request()

    assert (request.trade_date, request.previous_trade_date, request.target_date) == (
        "20260821",
        "20260820",
        "20260824",
    )
    command = wrapper.build_command(request)
    assert command[:4] == [sys.executable, "-X", "utf8", "-m"]
    assert command[4] == "review_core.pool_pipeline"
    for option, value in (
        ("--trade-date", "20260821"),
        ("--previous-trade-date", "20260820"),
        ("--target-date", "20260824"),
        ("--runtime-root", str(request.runtime_root)),
        ("--shared-root", str(request.shared_root)),
        ("--hk-root", str(request.hk_root)),
        ("--close-root", str(request.close_root)),
        ("--fupan-store-root", str(request.fupan_store_root)),
        ("--stage7-store-root", str(request.stage7_store_root)),
        ("--bundle-root", str(request.bundle_root)),
        ("--shared-store-root", str(request.shared_store_root)),
        ("--calendar-path", str(request.calendar_path)),
    ):
        assert command[command.index(option) + 1] == value

    env = wrapper.build_environment(request, base_env={"PATH": "/usr/bin"})
    assert env["V3_SHARED_DATA_PACKAGE_ROOT"] == str(request.shared_root)
    assert env["V3_SHARED_DATA_STORE_ROOT"] == str(request.shared_store_root)
    assert env["PYTHONDONTWRITEBYTECODE"] == "1"
    assert str(request.review_core_package_root) in env["PYTHONPATH"].split(":")


@pytest.mark.parametrize(
    "field,value",
    [
        ("review_core_package_root", "/Users/lexi/Desktop/review-core"),
        ("shared_root", "/Users/lexi/Documents/Codex/Windows/review-core"),
        ("runtime_root", r"C:\\Users\\lexi\\review-core"),
        ("fupan_store_root", "/Users/lexi/Documents/Codex/not-a-canary"),
    ],
)
def test_request_rejects_desktop_windows_backslash_and_non_canary_roots(
    field: str, value: str
) -> None:
    kwargs = _request_kwargs()
    kwargs[field] = value
    with pytest.raises(wrapper.PathBoundaryError):
        wrapper.validate_request(**kwargs)


def test_request_rejects_date_drift_and_calendar_outside_candidate_or_canary() -> None:
    kwargs = _request_kwargs()
    kwargs["target_date"] = "20260825"
    with pytest.raises(wrapper.FrozenDateError):
        wrapper.validate_request(**kwargs)

    kwargs = _request_kwargs()
    kwargs["calendar_path"] = "/Users/lexi/Desktop/market_calendar_2026.json"
    with pytest.raises(wrapper.PathBoundaryError):
        wrapper.validate_request(**kwargs)


def test_result_preserves_partial_and_missing_workloads_and_provenance() -> None:
    request = _request()
    result = wrapper.validate_official_result(
        _official_result(
            status="PARTIAL",
            workloads={
                "hk_close_review": _workload("PARTIAL", "hk"),
                "fupan_pool": _workload("READY", "fupan"),
            },
        ),
        request,
        exit_code=0,
    )

    assert result["status"] == "CANNOT_CONFIRM"
    assert set(result["workloads"]) == set(wrapper.WORKLOADS)
    assert result["workloads"]["hk_close_review"]["status"] == "PARTIAL"
    assert result["workloads"]["fupan_pool"]["artifact_sha256"] == "a" * 64
    assert result["workloads"]["stage7_pool"]["status"] == "CANNOT_CONFIRM"
    assert result["workloads"]["stage7_pool"]["error"]["type"] == "MissingWorkload"
    assert all(result[name] is False for name in SAFETY_FLAGS)


def test_nonzero_child_exit_is_cannot_confirm_and_never_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    request = _request()
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return subprocess.CompletedProcess(command, 7, "", "official package failed")

    result = wrapper.run_pipeline(request, runner=fake_run)

    assert result["status"] == "CANNOT_CONFIRM"
    assert result["exit_code"] == 7
    assert result["error"]["type"] == "OfficialPipelineExit"
    assert captured["shell"] is False
    assert captured["check"] is False
    assert all(result[name] is False for name in SAFETY_FLAGS)


def test_semantic_non_ready_result_has_nonzero_wrapper_exit_even_when_child_exits_zero() -> None:
    request = _request()
    official = _official_result(
        status="PARTIAL",
        workloads={
            "hk_close_review": _workload("READY", "hk"),
            "fupan_pool": _workload("PARTIAL", "fupan"),
            "stage7_pool": _workload("CANNOT_CONFIRM", "stage7"),
        },
    )

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, json.dumps(official), "")

    result = wrapper.run_pipeline(request, runner=fake_run)

    assert result["status"] == "CANNOT_CONFIRM"
    assert result["official_exit_code"] == 0
    assert result["exit_code"] != 0


def test_all_ready_result_is_the_only_zero_wrapper_exit() -> None:
    request = _request()
    official = _official_result()

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, json.dumps(official), "")

    result = wrapper.run_pipeline(request, runner=fake_run)

    assert result["status"] == "READY"
    assert result["official_exit_code"] == 0
    assert result["exit_code"] == 0


def test_timeout_is_typed_and_nonzero(monkeypatch: pytest.MonkeyPatch) -> None:
    request = _request()
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured.update(kwargs)
        raise subprocess.TimeoutExpired(command, kwargs["timeout"], output="partial", stderr="timed out")

    result = wrapper.run_pipeline(request, runner=fake_run)

    assert captured["timeout"] == wrapper.PIPELINE_TIMEOUT_SECONDS
    assert result["status"] == "CANNOT_CONFIRM"
    assert result["exit_code"] == wrapper.TIMEOUT_EXIT_CODE
    assert result["error"]["type"] == "OfficialPipelineTimeout"
    assert all(result[name] is False for name in SAFETY_FLAGS)


def test_unsafe_result_has_nonzero_wrapper_exit() -> None:
    request = _request()
    official = _official_result(safety={"production_allowed": True, "buy_gate_updated": False, "orders_sent": False})

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, json.dumps(official), "")

    result = wrapper.run_pipeline(request, runner=fake_run)

    assert result["status"] == "CANNOT_CONFIRM"
    assert result["exit_code"] == wrapper.WRAPPER_FAILURE_EXIT_CODE
    assert any(error["type"] == "UnsafeSafetyFlag" for error in result["errors"])


def test_unsafe_official_flags_fail_closed_to_cannot_confirm() -> None:
    request = _request()
    result = wrapper.validate_official_result(
        _official_result(safety={"production_allowed": True, "buy_gate_updated": False, "orders_sent": False}),
        request,
        exit_code=0,
    )

    assert result["status"] == "CANNOT_CONFIRM"
    assert any(error["type"] == "UnsafeSafetyFlag" for error in result["errors"])
    assert all(result[name] is False for name in SAFETY_FLAGS)


def _write_public_fupan_fixture(shared_root: Path, shared_store_root: Path) -> None:
    source = Path(
        "/Users/lexi/Documents/Codex/2026-08-13/"
        "v35-stage-selection-finance-localize-20260817/work/service-app/"
        "upstreams/v3_shared_data/shared_data"
    )
    package = shared_root / "shared_data"
    package.mkdir(parents=True, exist_ok=True)
    for name in ("public_fupan.py", "hashing.py", "paths.py", "store.py", "allowlist.py", "collectors.py", "constants.py"):
        shutil.copy2(source / name, package / name)
    (package / "__init__.py").write_text("", encoding="utf-8")

    bundle_path = Path(
        "/Users/lexi/Library/Application Support/com.lexi.review-core.local/state/"
        "data/review_bundle/20260821/runs/rbv1-20260821-aac5a9e564ea1f55/review_bundle.json"
    )
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    anchor_rows = bundle["compatibility"]["anchor_role_v3_rows"]
    blocks: list[str] = []
    for index, row in enumerate(anchor_rows, 1):
        code = f"{index:06d}"
        blocks.append(
            "<div class='list-group-item ztitem'><b>"
            + str(row["theme"])
            + "</b><table><tr><td><span class='kline' code='"
            + code
            + "'>"
            + str(row["stock"])
            + "</span></td></tr></table></div>"
        )
    plate = json.dumps({"result": "success", "html": "".join(blocks)}, ensure_ascii=False).encode()
    run_id = "20260821-public-fupan-wrapper-canary"
    run_relative = f"public_fupan/runs/20260821/{run_id}"
    run_dir = shared_store_root / run_relative
    run_dir.mkdir(parents=True, exist_ok=True)
    plate_path = run_dir / "plate.json"
    plate_path.write_bytes(plate)
    plate_sha = hashlib.sha256(plate).hexdigest()
    manifest = {
        "schema_version": "v3_shared_data.public_fupan_bundle.v1",
        "trade_date": "20260821",
        "run_id": run_id,
        "files": {
            "plate.json": {
                "relative": f"{run_relative}/plate.json",
                "sha256": plate_sha,
                "size": len(plate),
            }
        },
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    manifest_bytes = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    (run_dir / "manifest.json").write_bytes(manifest_bytes)
    receipt = {
        "schema_version": "v3_shared_data.public_fupan_bundle.v1",
        "status": "READY",
        "trade_date": "20260821",
        "run_id": run_id,
        "manifest_sha256": manifest_sha,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    (run_dir / "receipt.json").write_text(json.dumps(receipt, ensure_ascii=False), encoding="utf-8")
    (shared_store_root / "public_fupan").mkdir(parents=True, exist_ok=True)
    (shared_store_root / "public_fupan" / "latest.json").write_text(
        json.dumps(
            {
                "schema_version": "v3_shared_data.public_fupan_latest.v1",
                "entries": {
                    "20260821": {
                        "run_id": run_id,
                        "run_relative": run_relative,
                        "status": "READY",
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _write_bundle_fixture(bundle_root: Path) -> None:
    formal_run = Path(
        "/Users/lexi/Library/Application Support/com.lexi.review-core.local/state/data/"
        "review_bundle/20260821/runs/rbv1-20260821-aac5a9e564ea1f55"
    )
    run = bundle_root / "review_bundle" / "20260821" / "runs" / formal_run.name
    run.mkdir(parents=True, exist_ok=True)
    for name in ("review_bundle.json", "manifest.json", "receipt.json"):
        shutil.copy2(formal_run / name, run / name)
    hashes = {
        name.removesuffix(".json") + "_sha256": hashlib.sha256((run / name).read_bytes()).hexdigest()
        for name in ("review_bundle.json", "manifest.json", "receipt.json")
    }
    current = {
        "schema_version": "review_core.review_bundle.current.v1",
        "trade_date": "20260821",
        "run_id": formal_run.name,
        "run_path": f"review_bundle/20260821/runs/{formal_run.name}",
        "bundle_path": f"review_bundle/20260821/runs/{formal_run.name}/review_bundle.json",
        "manifest_path": f"review_bundle/20260821/runs/{formal_run.name}/manifest.json",
        "receipt_path": f"review_bundle/20260821/runs/{formal_run.name}/receipt.json",
        "bundle_sha256": hashes["review_bundle_sha256"],
        "manifest_sha256": hashes["manifest_sha256"],
        "receipt_sha256": hashes["receipt_sha256"],
        "safety_flags": {name: False for name in SAFETY_FLAGS},
    }
    pointer = bundle_root / "review_bundle" / "20260821" / "current.json"
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text(json.dumps(current, ensure_ascii=False), encoding="utf-8")


def test_test_tmp_canary_reads_public_fupan_ready_and_keeps_stage7_missing() -> None:
    root = CANARY_ROOT / "official-canary-aac5"
    request = _request(root)
    _write_public_fupan_fixture(request.shared_root, request.shared_store_root)
    _write_bundle_fixture(request.bundle_root)

    result = wrapper.run_pipeline(request)

    assert result["exit_code"] == wrapper.WRAPPER_FAILURE_EXIT_CODE
    assert result["official_exit_code"] == 0
    assert result["trade_date"] == "20260821"
    assert result["previous_trade_date"] == "20260820"
    assert result["target_date"] == "20260824"
    assert result["status"] == "CANNOT_CONFIRM"
    assert result["workloads"]["fupan_pool"]["status"] == "PARTIAL"
    assert result["workloads"]["stage7_pool"]["status"] == "CANNOT_CONFIRM"
    assert all(result[name] is False for name in SAFETY_FLAGS)
    receipt = Path(result["receipt_path"])
    assert receipt.is_file()
    receipt_payload = json.loads(receipt.read_text(encoding="utf-8"))
    fupan_current_path = root / "fupan-store" / "current" / "20260824" / "D1_FUPAN_REVIEW_POOL_V1" / "current.json"
    assert fupan_current_path.is_file()
    fupan_current = json.loads(fupan_current_path.read_text(encoding="utf-8"))
    assert fupan_current["status"] == "PARTIAL"
    fupan_artifact = root / "fupan-store" / fupan_current["artifact_relative"]
    fupan_payload = json.loads(fupan_artifact.read_text(encoding="utf-8"))
    assert fupan_payload["public_fupan_run_id"] == "20260821-public-fupan-wrapper-canary"
    assert fupan_payload["public_fupan_manifest_sha256"]
    assert receipt_payload["status"] == "CANNOT_CONFIRM"
    assert result["workloads"]["stage7_pool"]["status"] == "CANNOT_CONFIRM"
    assert not (FORMAL_REVIEW_CORE_ROOT / "state" / "data" / "pool_pipeline").exists()
