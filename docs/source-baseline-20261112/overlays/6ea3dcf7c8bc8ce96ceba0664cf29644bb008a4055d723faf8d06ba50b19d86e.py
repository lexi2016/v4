from __future__ import annotations

import ast
import hashlib
import importlib.util
import inspect
import subprocess
import sys
from pathlib import Path
from types import FunctionType, ModuleType

import ops.macos_research_panel_daily as facade


ROOT = Path(__file__).resolve().parents[1]
PREIMAGE_COMMIT = "fdc34096bb3ebefe82ed1f8b90ee16e9c0727aaf"
PREIMAGE_SOURCE_SHA256 = "bae30a149e7301d463cd069a24a0d83a5197d25f4d33503391624ce612f31506"

FUNCTION_NAMES = (
    "_today_shanghai",
    "_scheduled_day_is_cross_market_trading_day",
    "_frame_records",
    "_compact_datetime",
    "_canonical_sha",
    "_universe_code",
    "collect_a_pytdx_rows",
    "collect_hk_futu_rows",
    "_date",
    "_rows",
    "_number",
    "_code",
    "_validate_rows",
    "_sha",
    "_atomic_write",
    "_panel_frame",
    "bootstrap_a_vipdoc_from_panel",
    "_validate_seed_rows",
    "_load_authority_module",
    "_day_file_last_date",
    "_accepted_formula_input_root",
    "run_windows_a_sync_authority",
    "_parquet_max_date",
    "selector_pointer_is_ready",
    "_after_1700_attempt_path",
    "_normalize_lane",
    "_not_requested_lane",
    "_read_lane_receipt",
    "_receipt_safety_is_false",
    "_a_lane_receipt_ready",
    "_hk_lane_receipt_ready",
    "ensure_after_1700",
    "ensure_exit_code",
    "_ensure_pointer_seed",
    "run_windows_a_formula_authority",
    "run_hk_0_2_authority",
    "_existing_records",
    "_a_record",
    "_hk_record",
    "_pack_day_file",
    "_a_exchange",
    "_grouped_result",
    "pack_a_day",
    "pack_hk_day",
    "validate_snapshot",
    "_receipt",
    "run_lanes",
    "_non_trading_day_result",
    "run_scheduled_lanes",
    "build_subprocess_command",
    "_load_universe",
    "_a_day_files",
    "_absolute_path_argument",
    "main",
)

CONSTANT_NAMES = (
    "A_DAY_STRUCT",
    "HK_DAY_STRUCT",
    "SAFETY_FLAGS",
    "LANE_CHOICES",
    "HKCONNECT_PLATE_CODES",
    "PYTDX_KLINE_DAY",
    "MAX_EXCLUDED_EVIDENCE",
    "COMMON_A_PREFIXES",
    "AUTHORITY_DAY_MINIMUM_DEFAULT",
)

IMPORTED_NAMES = (
    "argparse",
    "csv",
    "_datetime",
    "hashlib",
    "json",
    "os",
    "importlib",
    "shutil",
    "subprocess",
    "sys",
    "struct",
    "tempfile",
    "ZoneInfo",
    "Path",
    "Any",
    "Callable",
    "Iterable",
    "Mapping",
    "Sequence",
)


def _load_preimage(tmp_path: Path) -> ModuleType:
    source = subprocess.run(
        ["git", "show", f"{PREIMAGE_COMMIT}:ops/macos_research_panel_daily.py"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    assert hashlib.sha256(source).hexdigest() == PREIMAGE_SOURCE_SHA256
    source_path = tmp_path / "macos_research_panel_daily_preimage.py"
    source_path.write_bytes(source)
    module_name = f"macos_research_panel_daily_preimage_{id(tmp_path)}"
    spec = importlib.util.spec_from_file_location(module_name, source_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_facade_rebinds_the_complete_legacy_function_surface(tmp_path: Path) -> None:
    preimage = _load_preimage(tmp_path)
    source_path = ROOT / "ops/macos_research_panel_daily.py"
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(source_path))
    assert len([name for name in FUNCTION_NAMES if isinstance(getattr(facade, name, None), FunctionType)]) == 54
    assert len(source.splitlines()) < 1000
    assert not hasattr(facade, "__all__")

    for name in CONSTANT_NAMES:
        current = getattr(facade, name)
        before = getattr(preimage, name)
        if name.endswith("_STRUCT"):
            assert (current.format, current.size) == (before.format, before.size)
        else:
            assert current == before
    for name in FUNCTION_NAMES:
        current = getattr(facade, name)
        before = getattr(preimage, name)
        assert isinstance(current, FunctionType), name
        assert current.__globals__ is vars(facade), name
        assert current.__module__ == "ops.macos_research_panel_daily", name
        assert current.__qualname__ == before.__qualname__, name
        assert current.__doc__ == before.__doc__, name
        assert current.__defaults__ == before.__defaults__, name
        assert current.__kwdefaults__ == before.__kwdefaults__, name
        assert current.__annotations__ == before.__annotations__, name
        assert current.__dict__ == before.__dict__, name
        assert inspect.signature(current) == inspect.signature(before), name


def test_facade_preserves_imported_bindings_and_snapshot_gate_class(tmp_path: Path) -> None:
    preimage = _load_preimage(tmp_path)
    for name in IMPORTED_NAMES:
        assert hasattr(facade, name), name
        assert getattr(facade, name) is getattr(preimage, name), name
    current = facade.SnapshotGateError
    before = preimage.SnapshotGateError
    assert current.__name__ == before.__name__ == "SnapshotGateError"
    assert current.__qualname__ == before.__qualname__ == "SnapshotGateError"
    assert current.__doc__ == before.__doc__
    assert current.__module__ == "ops.macos_research_panel_daily"
    assert issubclass(current, ValueError)


def test_children_are_source_only_modules_with_expected_size_and_dag() -> None:
    children = {
        "ops/macos_research_panel_daily_common.py": 800,
        "ops/macos_research_panel_daily_collectors.py": 800,
        "ops/macos_research_panel_daily_authority.py": 800,
        "ops/macos_research_panel_daily_pack.py": 800,
        "ops/macos_research_panel_daily_gate.py": 800,
    }
    expected_defs = {
        "common": (
            "_today_shanghai", "_scheduled_day_is_cross_market_trading_day", "_frame_records",
            "_compact_datetime", "_canonical_sha", "_universe_code", "_date", "_rows",
            "_number", "_code", "_validate_rows", "_sha", "_atomic_write", "_after_1700_attempt_path",
            "_normalize_lane", "_not_requested_lane", "build_subprocess_command", "_load_universe",
            "_a_day_files", "_absolute_path_argument",
        ),
        "collectors": ("collect_a_pytdx_rows", "collect_hk_futu_rows"),
        "authority": (
            "_load_authority_module", "_formula_artifact_binding", "_accepted_formula_input_root", "run_windows_a_sync_authority",
            "_parquet_max_date", "_ensure_pointer_seed", "run_windows_a_formula_authority", "run_hk_0_2_authority",
        ),
        "pack": (
            "_panel_frame", "bootstrap_a_vipdoc_from_panel", "_validate_seed_rows", "_day_file_last_date",
            "_existing_records", "_a_record", "_hk_record", "_pack_day_file", "_a_exchange", "_grouped_result",
            "pack_a_day", "pack_hk_day", "validate_snapshot",
        ),
        "gate": (
            "selector_pointer_is_ready", "_read_lane_receipt", "_receipt_safety_is_false", "_a_lane_receipt_ready",
            "_hk_lane_receipt_ready", "ensure_after_1700", "ensure_exit_code", "_receipt", "run_lanes",
            "_non_trading_day_result", "run_scheduled_lanes", "main",
        ),
    }
    actual_defs = {}
    for relative, limit in children.items():
        path = ROOT / relative
        source = path.read_text(encoding="utf-8")
        assert len(source.splitlines()) < limit
        tree = ast.parse(source, filename=str(path))
        compile(source, str(path), "exec")
        assert "from .macos_research_panel_daily import" not in source
        module_name = path.stem.removeprefix("macos_research_panel_daily_")
        actual_defs[module_name] = tuple(
            node.name for node in tree.body if isinstance(node, ast.FunctionDef)
        )

    assert actual_defs == expected_defs

    graph = {"facade": set(), "common": set(), "collectors": set(), "authority": set(), "pack": set(), "gate": set()}
    paths = {
        "facade": ROOT / "ops/macos_research_panel_daily.py",
        **{name: ROOT / f"ops/macos_research_panel_daily_{name}.py" for name in ("common", "collectors", "authority", "pack", "gate")},
    }
    for owner, path in paths.items():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.level != 1:
                continue
            if node.module is None:
                graph[owner].update(
                    alias.name.removeprefix("macos_research_panel_daily_")
                    for alias in node.names
                    if alias.name.startswith("macos_research_panel_daily_")
                )
            elif node.module.startswith("macos_research_panel_daily_"):
                graph[owner].add(node.module.removeprefix("macos_research_panel_daily_"))
    assert graph == {
        "facade": {"common", "collectors", "authority", "pack", "gate"},
        "common": set(),
        "collectors": {"common"},
        "authority": {"common", "pack"},
        "pack": {"common"},
        "gate": {"common", "collectors", "authority", "pack"},
    }

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        assert node not in visiting
        if node in visited:
            return
        visiting.add(node)
        for child in graph[node]:
            visit(child)
        visiting.remove(node)
        visited.add(node)

    for node in graph:
        visit(node)
