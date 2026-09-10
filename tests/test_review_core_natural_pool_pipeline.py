from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest


APP_ROOT = Path(__file__).resolve().parents[1]
ADAPTER_PATH = APP_ROOT / "ops" / "run_review_core_natural_pool_pipeline.py"
SAFETY_FLAGS = ("production_allowed", "buy_gate_updated", "orders_sent")
WORKLOADS = ("hk_close_review", "fupan_pool", "stage7_pool")


def _load_adapter() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "review_core_natural_pool_pipeline_adapter", ADAPTER_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


adapter = _load_adapter()


def _calendar(path: Path, *, a_holidays=(), hk_holidays=()) -> Path:
    def periods(values):
        return [{"start": value, "end": value} for value in values]

    payload = {
        "schema_version": "test.market_calendar.v1",
        "year": 2026,
        "timezone": "Asia/Shanghai",
        "markets": {
            "a_share": {"holiday_periods": periods(a_holidays)},
            "hk_securities": {"holiday_periods": periods(())},
            "hk_connect_southbound": {
                "holiday_periods": periods(hk_holidays),
            },
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _workload(name: str, status: str = "READY", *, provenance: bool = True) -> dict[str, object]:
    value: dict[str, object] = {"status": status}
    if provenance:
        value.update(
            {
                "run_id": f"run-{name}",
                "artifact_sha256": "a" * 64,
                "manifest_sha256": "b" * 64,
                "receipt_sha256": "c" * 64,
            }
        )
    return value


def _official(
    *,
    status: str = "READY",
    workloads: dict[str, object] | None = None,
    safety: dict[str, object] | None = None,
    run_id: str | None = "official-run",
) -> dict[str, object]:
    result: dict[str, object] = {
        "schema": "review_core.pool_pipeline.receipt.v1",
        "status": status,
        "run_id": run_id,
        "receipt_path": "/tmp/review-core/receipt.json",
        "workloads": workloads
        or {name: _workload(name) for name in WORKLOADS},
        **(safety or {name: False for name in SAFETY_FLAGS}),
    }
    return result


def _fake_package(root: Path, result: dict[str, object]) -> Path:
    package = root / "review_core"
    package.mkdir(parents=True, exist_ok=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    encoded = json.dumps(result, ensure_ascii=False, sort_keys=True)
    (package / "pool_pipeline.py").write_text(
        "import json\n"
        "import os\n"
        "import sys\n"
        f"result = json.loads({encoded!r})\n"
        "result['observed_args'] = sys.argv[1:]\n"
        "result['observed_env'] = {key: os.environ.get(key) for key in ("
        "'PYTHONPATH', 'V3_SHARED_DATA_PACKAGE_ROOT', 'STORE_ROOT', "
        "'V3_SHARED_DATA_STORE_ROOT')}\n"
        "print(json.dumps(result, sort_keys=True))\n",
        encoding="utf-8",
    )
    return root


def _request_kwargs(root: Path, calendar_path: Path) -> dict[str, object]:
    return {
        "trade_date": "20260821",
        "calendar_path": calendar_path,
        "review_core_package_root": _fake_package(
            root / "review-package", _official()
        ),
        "shared_package_root": root / "shared-package",
        "shared_store_root": root / "shared-store",
        "runtime_root": root / "runtime",
        "hk_root": root / "hk-store",
        "close_root": root / "close-store",
        "fupan_store_root": root / "fupan-store",
        "stage7_store_root": root / "stage7-store",
        "bundle_root": root / "bundle-store",
    }


def _request(tmp_path: Path, calendar_path: Path):
    return adapter.validate_request(**_request_kwargs(tmp_path, calendar_path))


def test_dynamic_calendar_resolves_hk_previous_and_a_share_next_with_weekend_and_holiday(
    tmp_path: Path,
) -> None:
    calendar = _calendar(
        tmp_path / "calendar.json",
        a_holidays=("20260824",),
        hk_holidays=("20260820",),
    )

    trade, previous, target, calendar_text, digest = adapter.resolve_trade_dates(
        "20260821", calendar_path=calendar
    )

    assert (trade, previous, target) == ("20260821", "20260819", "20260825")
    assert calendar_text == str(calendar)
    assert len(digest) == 64


def test_frozen_candidate_calendar_resolves_20260821_to_20260820_and_20260824() -> None:
    calendar = APP_ROOT / "contracts" / "market_calendar_2026.json"
    trade, previous, target, _path, _digest = adapter.resolve_trade_dates(
        "20260821", calendar_path=calendar
    )

    assert (trade, previous, target) == ("20260821", "20260820", "20260824")


def test_optional_dates_must_match_calendar_resolution(tmp_path: Path) -> None:
    calendar = _calendar(tmp_path / "calendar.json")
    with pytest.raises(adapter.CalendarValidationError):
        adapter.validate_request(
            **{
                **_request_kwargs(tmp_path, calendar),
                "previous_trade_date": "20260819",
            }
        )


def test_request_binds_all_roots_and_separates_package_from_store_environment(
    tmp_path: Path,
) -> None:
    calendar = _calendar(tmp_path / "calendar.json")
    request = _request(tmp_path, calendar)

    command = adapter.build_command(request, python_executable="/test/python")
    assert command[:5] == ["/test/python", "-X", "utf8", "-m", "review_core.pool_pipeline"]
    assert command[command.index("--shared-root") + 1] == str(request.shared_store_root)
    assert command[command.index("--shared-store-root") + 1] == str(request.shared_store_root)
    assert command[command.index("--stage7-store-root") + 1] == str(request.stage7_store_root)

    environment = adapter.build_environment(request, base_env={"PATH": "/usr/bin"})
    assert environment["PYTHONPATH"] == str(request.review_core_package_root)
    assert environment["V3_SHARED_DATA_PACKAGE_ROOT"] == str(request.shared_package_root)
    assert environment["STORE_ROOT"] == str(request.shared_store_root)
    assert environment["V3_SHARED_DATA_STORE_ROOT"] == str(request.shared_store_root)


def test_symlink_escape_and_desktop_windows_paths_are_rejected(tmp_path: Path) -> None:
    calendar = _calendar(tmp_path / "calendar.json")
    outside = Path.home()
    link = tmp_path / "escape"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unavailable")

    with pytest.raises(adapter.PathBoundaryError):
        adapter.validate_request(
            **{**_request_kwargs(tmp_path, calendar), "runtime_root": link / "runtime"}
        )
    with pytest.raises(adapter.PathBoundaryError):
        adapter.validate_request(
            **{**_request_kwargs(tmp_path, calendar), "close_root": str(tmp_path / "Desktop" / "close")}
        )
    with pytest.raises(adapter.PathBoundaryError):
        adapter.validate_request(
            **{**_request_kwargs(tmp_path, calendar), "bundle_root": r"C:\\review-core"}
        )


@pytest.mark.parametrize("forbidden_root", ["/tmp", "/private/tmp", "/var/folders"])
@pytest.mark.parametrize(
    "field",
    [
        "review_core_package_root",
        "shared_package_root",
        "shared_store_root",
        "runtime_root",
        "calendar_path",
    ],
)
def test_system_temp_roots_are_rejected_for_every_path_category(
    tmp_path: Path, forbidden_root: str, field: str
) -> None:
    calendar = _calendar(tmp_path / "calendar.json")
    kwargs = _request_kwargs(tmp_path, calendar)
    kwargs[field] = str(Path(forbidden_root) / "v35-natural-forbidden")

    with pytest.raises(adapter.PathBoundaryError):
        adapter.validate_request(**kwargs)


def test_in_scope_leaf_and_ancestor_symlinks_are_rejected(tmp_path: Path) -> None:
    calendar = _calendar(tmp_path / "calendar.json")
    real_store = tmp_path / "real-store"
    real_store.mkdir()

    leaf = tmp_path / "leaf-store"
    ancestor_target = tmp_path / "ancestor-target"
    ancestor_target.mkdir()
    ancestor = tmp_path / "ancestor-store"
    try:
        leaf.symlink_to(real_store, target_is_directory=True)
        ancestor.symlink_to(ancestor_target, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unavailable")

    with pytest.raises(adapter.PathBoundaryError):
        adapter.validate_request(
            **{**_request_kwargs(tmp_path, calendar), "runtime_root": leaf / "runtime"}
        )
    with pytest.raises(adapter.PathBoundaryError):
        adapter.validate_request(
            **{**_request_kwargs(tmp_path, calendar), "runtime_root": ancestor / "runtime"}
        )


def test_run_uses_shell_false_and_official_module_with_explicit_environment(
    tmp_path: Path,
) -> None:
    calendar = _calendar(tmp_path / "calendar.json")
    request = _request(tmp_path, calendar)
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return subprocess.CompletedProcess(
            command,
            0,
            json.dumps(_official()),
            "",
        )

    result = adapter.run_pipeline(request, runner=fake_run)

    assert result["status"] == "READY"
    assert result["overall_status"] == "READY"
    assert captured["shell"] is False
    assert captured["cwd"] == str(request.review_core_package_root)
    assert captured["env"]["PYTHONPATH"] == str(request.review_core_package_root)
    assert captured["env"]["V3_SHARED_DATA_PACKAGE_ROOT"] == str(request.shared_package_root)
    assert captured["env"]["STORE_ROOT"] == str(request.shared_store_root)
    assert all(result[name] is False for name in SAFETY_FLAGS)


@pytest.mark.parametrize(
    "official",
    [
        _official(status="PARTIAL", workloads={name: _workload(name, "PARTIAL") for name in WORKLOADS}),
        _official(status="CANNOT_CONFIRM"),
        _official(status="FAILED"),
        _official(workloads={**{name: _workload(name) for name in WORKLOADS}, "stage7_pool": None}),
        _official(workloads={**{name: _workload(name) for name in WORKLOADS}, "fupan_pool": _workload("fupan", provenance=False)}),
        _official(safety={"production_allowed": True, "buy_gate_updated": False, "orders_sent": False}),
    ],
)
def test_non_ready_missing_stage7_missing_provenance_and_unsafe_results_exit_two(
    tmp_path: Path, official: dict[str, object]
) -> None:
    calendar = _calendar(tmp_path / "calendar.json")
    request = _request(tmp_path, calendar)

    result = adapter.run_pipeline(
        request,
        runner=lambda command, **kwargs: subprocess.CompletedProcess(
            command, 0, json.dumps(official), ""
        ),
    )

    assert result["status"] in {"PARTIAL", "CANNOT_CONFIRM"}
    assert result["exit_code"] == 2
    assert all(result[name] is False for name in SAFETY_FLAGS)


def test_ready_requires_provenance_on_every_workload_even_ready_empty(tmp_path: Path) -> None:
    calendar = _calendar(tmp_path / "calendar.json")
    request = _request(tmp_path, calendar)
    official = _official(
        workloads={
            "hk_close_review": _workload("hk", "READY"),
            "fupan_pool": _workload("fupan", "READY_EMPTY", provenance=False),
            "stage7_pool": _workload("stage7", "READY"),
        }
    )
    result = adapter.run_pipeline(
        request,
        runner=lambda command, **kwargs: subprocess.CompletedProcess(
            command, 0, json.dumps(official), ""
        ),
    )
    assert result["status"] == "CANNOT_CONFIRM"
    assert result["exit_code"] == 2
    assert result["workloads"]["fupan_pool"]["error"]["type"] == "MissingProvenance"


def test_cli_requires_all_explicit_paths_and_returns_zero_only_for_full_ready(
    tmp_path: Path,
) -> None:
    calendar = _calendar(tmp_path / "calendar.json")
    package = _fake_package(tmp_path / "package", _official())
    kwargs = _request_kwargs(tmp_path, calendar)
    kwargs["review_core_package_root"] = package
    argv = [str(ADAPTER_PATH)]
    for name, value in kwargs.items():
        option = "--" + name.replace("_", "-")
        argv.extend([option, str(value)])

    completed = subprocess.run(
        [sys.executable, *argv],
        cwd=APP_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "READY"
    assert payload["overall_status"] == "READY"
    assert payload["official_result"]["observed_env"]["PYTHONPATH"] == str(package)
    assert payload["official_result"]["observed_env"]["V3_SHARED_DATA_PACKAGE_ROOT"] == str(
        kwargs["shared_package_root"]
    )
    assert payload["official_result"]["observed_env"]["STORE_ROOT"] == str(
        kwargs["shared_store_root"]
    )


def test_cli_nonzero_for_partial_official_result(tmp_path: Path) -> None:
    calendar = _calendar(tmp_path / "calendar.json")
    official = _official(
        status="PARTIAL",
        workloads={name: _workload(name, "PARTIAL") for name in WORKLOADS},
    )
    package = _fake_package(tmp_path / "package", official)
    kwargs = _request_kwargs(tmp_path, calendar)
    kwargs["review_core_package_root"] = package
    argv = [str(ADAPTER_PATH)]
    for name, value in kwargs.items():
        argv.extend(["--" + name.replace("_", "-"), str(value)])

    completed = subprocess.run(
        [sys.executable, *argv],
        cwd=APP_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 2
    payload = json.loads(completed.stdout)
    assert payload["status"] == "PARTIAL"
    assert payload["exit_code"] == 2
