"""Focused ownership and explicit-binding checks for the V4 Review Core closure."""
from __future__ import annotations

import hashlib
import importlib
import sys
import types
from pathlib import Path

import pytest


APP_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_PARENT = APP_ROOT / "upstreams"
PACKAGE_DIR = PACKAGE_PARENT / "review_core"
EXPECTED_FILES = {
    "__init__.py": (984, "8261659887ffa4cae3cc53dfa6e4e072659aa2e36abe2cc14cadefad0b8231f6"),
    "config.py": (3145, "da9a7acd3381e9c87b7f5442eeb381b78fba352d4cd073ae373c50e4cc12751e"),
    "consumer.py": (18043, "6ed804d5ddc427596af17d66c192111c4f20a47fa341f206f1007d7dc113808c"),
    "core.py": (59792, "edc10ea4bc837b6f307d897a6bbfde5d555fc289b537cf7f8831edf56428854b"),
    "fupan_pool.py": (12200, "6a3a01e46fa832e8d10d84bbfdd5ac0a873e0eed14fddf50380dcd4da59cf7c3"),
    "fupan_sources.py": (22904, "1d6744f13e5c254ce397b82d001000b030bd77191242ca1545126eced80ee091"),
    "hk_review.py": (12382, "2da147824393add8ba55244d96da7ec4ef2b811e354f5f4bdacf400e6c2f3294"),
    "hk_sources.py": (14112, "73500aa92a9751acbee96934fc6f426d6cf66e00eec17e5ac0156ad1a15f427c"),
    "pool_pipeline.py": (21453, "a36efa1ca99222740bab34934013ffa7e8a43ceddf0dda3c6602c9fdfdea0c77"),
    "pool_store.py": (14382, "d449e051effbbd61eaf2f78a3344e5d71474564962a2072f1320681cff4ae21d"),
    "producer.py": (87088, "b98b7905302bdad5f3e601b09f566672bfbf1508794085bac10ef6668e7c92c7"),
    "review.py": (58050, "08d6c5e24e7c673be4c9dfa3a5882c4f1f5b0e03c6184c5d64b8d2a4ece37a38"),
    "scheduler.py": (16049, "8e848508559d83fe35f997ef465f84ed7113dcff92d0b16e7889fda55adebbb7"),
    "stage7_pool.py": (14485, "1a07eb58863e92ae09d99d0500d373740dad4df4806db1976be762dc1e442aeb"),
    "stage7_sources.py": (13255, "aa76fa64815048cfcdcde645e62938a85d0ca3bdba4485f3a61a540cca4d56b5"),
}
EXPECTED_UNION = "685ca6b7d07baac6383edbe4f06c909cb150ea7429d5be37ae5ed05b00e9d5b9"


def test_owned_review_core_is_exact_regular_closure() -> None:
    assert PACKAGE_DIR.is_dir()
    assert not PACKAGE_DIR.is_symlink()
    entries = sorted(path.relative_to(PACKAGE_DIR).as_posix() for path in PACKAGE_DIR.rglob("*"))
    assert entries == sorted(EXPECTED_FILES)
    hashes: list[str] = []
    for relative, (expected_bytes, expected_sha) in EXPECTED_FILES.items():
        path = PACKAGE_DIR / relative
        assert path.is_file()
        assert not path.is_symlink()
        payload = path.read_bytes()
        actual_sha = hashlib.sha256(payload).hexdigest()
        assert len(payload) == expected_bytes
        assert actual_sha == expected_sha
        hashes.append(f"{relative}\0{actual_sha}\n")
    assert hashlib.sha256("".join(hashes).encode("utf-8")).hexdigest() == EXPECTED_UNION


def test_isolated_active_leaves_resolve_inside_owned_vendor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.syspath_prepend(str(PACKAGE_PARENT))
    loader = importlib.import_module("infrastructure.isolated_package_loader").load_isolated_package_module
    modules = [
        loader(PACKAGE_PARENT, package_directory="review_core", module_leaf=leaf, namespace_prefix=f"ownership_{leaf[:-3]}")
        for leaf in ("consumer", "fupan_pool", "stage7_pool", "pool_pipeline")
    ]
    for module in modules:
        assert Path(module.__file__).resolve().is_relative_to(PACKAGE_DIR.resolve())
    consumer = modules[0]
    core = consumer._core_module()
    assert Path(core.__file__).resolve().is_relative_to(PACKAGE_DIR.resolve())
    assert core.__name__.startswith(f"{consumer.__package__}.")


def test_close_video_loader_rejects_implicit_old_root(monkeypatch: pytest.MonkeyPatch) -> None:
    close_node = importlib.import_module("ops.run_v35_close_review_node")
    for name in (
        "REVIEW_CORE_PACKAGE_ROOT",
        "V35_REVIEW_CORE_PACKAGE_ROOT",
        "REVIEW_CORE_DATA_ROOT",
        "V35_REVIEW_CORE_RUNTIME_ROOT",
    ):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(RuntimeError, match="binding is missing"):
        close_node._load_shared_video_layer("20260911")


def test_close_video_loader_passes_explicit_parent_and_data_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    close_node = importlib.import_module("ops.run_v35_close_review_node")
    data_root = tmp_path / "review-core-data"
    monkeypatch.setenv("REVIEW_CORE_PACKAGE_ROOT", str(PACKAGE_PARENT))
    monkeypatch.setenv("V35_REVIEW_CORE_PACKAGE_ROOT", str(PACKAGE_PARENT))
    monkeypatch.setenv("REVIEW_CORE_DATA_ROOT", str(data_root))
    monkeypatch.setenv("V35_REVIEW_CORE_RUNTIME_ROOT", str(data_root))
    calls: dict[str, object] = {}

    class FakeConsumer:
        def load_v35_video_layer(self, trade_date: str, root: Path) -> dict[str, object]:
            calls["trade_date"] = trade_date
            calls["data_root"] = root
            return {"status": "CANNOT_CONFIRM", "target_trade_date": trade_date}

    def fake_loader(root: Path, **kwargs: object) -> FakeConsumer:
        calls["package_root"] = root
        calls["kwargs"] = kwargs
        return FakeConsumer()

    monkeypatch.setattr(close_node, "load_isolated_package_module", fake_loader)
    result = close_node._load_shared_video_layer("20260911")
    assert result["status"] == "CANNOT_CONFIRM"
    assert calls["package_root"] == PACKAGE_PARENT.resolve()
    assert calls["data_root"] == data_root.resolve()
    assert calls["kwargs"] == {
        "package_directory": "review_core",
        "module_leaf": "consumer",
        "namespace_prefix": "v35_review_core_video",
    }


def test_close_video_loader_rejects_conflicting_aliases(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    close_node = importlib.import_module("ops.run_v35_close_review_node")
    monkeypatch.setenv("REVIEW_CORE_PACKAGE_ROOT", str(PACKAGE_PARENT))
    monkeypatch.setenv("V35_REVIEW_CORE_PACKAGE_ROOT", str(PACKAGE_PARENT / "review_core"))
    monkeypatch.setenv("REVIEW_CORE_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("V35_REVIEW_CORE_RUNTIME_ROOT", str(tmp_path / "data"))
    with pytest.raises(RuntimeError, match="bindings disagree"):
        close_node._load_shared_video_layer("20260911")


def test_pool_wrappers_keep_missing_explicit_roots_cannot_confirm(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("REVIEW_CORE_PACKAGE_ROOT", str(PACKAGE_PARENT))
    fupan_root = tmp_path / "fupan-missing"
    stage7_root = tmp_path / "stage7-missing"
    monkeypatch.setenv("REVIEW_CORE_FUPAN_POOL_ROOT", str(fupan_root))
    monkeypatch.setenv("REVIEW_CORE_STAGE7_POOL_ROOT", str(stage7_root))
    fupan = importlib.import_module("infrastructure.review_core_fupan_pool_source")
    stage7 = importlib.import_module("infrastructure.review_core_stage7_pool_source")
    fupan_result = fupan.load_review_core_fupan_pool("20260911")
    stage7_result = stage7.load_review_core_stage7_pool("20260911")
    assert fupan_result["status"] == "CANNOT_CONFIRM"
    assert fupan_result["data_root"] == str(fupan_root.resolve())
    assert fupan_result["stage_selection_eligible"] is False
    assert stage7_result["status"] == "CANNOT_CONFIRM"
    assert stage7_result["data_root"] == str(stage7_root.resolve())
    assert stage7_result["stage_selection_eligible"] is False


def test_natural_adapter_requires_parent_package_root() -> None:
    adapter = importlib.import_module("ops.run_review_core_natural_pool_pipeline")
    assert adapter._package_module_path(PACKAGE_PARENT).is_file()
    assert not adapter._package_module_path(PACKAGE_DIR).exists()
    request = adapter.PipelineRequest(
        trade_date="20260911",
        previous_trade_date="20260910",
        target_date="20260912",
        calendar_path=APP_ROOT / "contracts" / "market_calendar_2026.json",
        calendar_sha256="calendar-sha",
        review_core_package_root=PACKAGE_PARENT,
        shared_package_root=APP_ROOT / "upstreams" / "v3_shared_data",
        shared_store_root=Path("/tmp/review-core-shared"),
        runtime_root=Path("/tmp/review-core-runtime"),
        hk_root=Path("/tmp/review-core-hk"),
        close_root=Path("/tmp/review-core-close"),
        fupan_store_root=Path("/tmp/review-core-fupan"),
        stage7_store_root=Path("/tmp/review-core-stage7"),
        bundle_root=Path("/tmp/review-core-bundle"),
    )
    environment = adapter.build_environment(request, base_env={"OLD_CHECKOUT": "/old"})
    assert environment["PYTHONPATH"] == str(PACKAGE_PARENT)
    assert environment["V3_SHARED_DATA_PACKAGE_ROOT"] == str(request.shared_package_root)
    assert environment["STORE_ROOT"] == str(request.shared_store_root)
    assert environment["V3_SHARED_DATA_STORE_ROOT"] == str(request.shared_store_root)
    assert "OLD_CHECKOUT" in environment


def test_close_node_no_longer_references_workspace_discovery() -> None:
    source = (APP_ROOT / "ops" / "run_v35_close_review_node.py").read_text(encoding="utf-8")
    assert "_WORKSPACE_ROOT" not in source
    assert "_review_core_package_parent" in source
    assert "_review_core_data_root" in source


def test_private_core_import_ignores_preloaded_global_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old_root = Path(
        "/Users/lexi/Library/Application Support/com.lexi.v35.local/"
        "releases/20260818T140000Z-v35-stage-input-owner/app/upstreams/review_core"
    )
    hostile_package = types.ModuleType("review_core")
    hostile_package.__path__ = [str(old_root)]  # type: ignore[attr-defined]
    hostile_package.__file__ = str(old_root / "__init__.py")
    hostile_core = types.ModuleType("review_core.core")
    hostile_core.__file__ = str(old_root / "core.py")
    hostile_core.marker = "HOSTILE_GLOBAL_PRELOAD"
    monkeypatch.setitem(sys.modules, "review_core", hostile_package)
    monkeypatch.setitem(sys.modules, "review_core.core", hostile_core)

    loader = importlib.import_module(
        "infrastructure.isolated_package_loader"
    ).load_isolated_package_module
    consumer = loader(
        PACKAGE_PARENT,
        package_directory="review_core",
        module_leaf="consumer",
        namespace_prefix="hostile_global",
    )
    core = consumer._core_module()

    assert getattr(core, "marker", None) != "HOSTILE_GLOBAL_PRELOAD"
    assert Path(core.__file__).resolve().is_relative_to(PACKAGE_DIR.resolve())
    assert core.__name__.startswith("_hostile_global_")


def test_private_core_import_ignores_old_package_search_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old_root = Path(
        "/Users/lexi/Library/Application Support/com.lexi.v35.local/"
        "releases/20260818T140000Z-v35-stage-input-owner/app/upstreams/review_core"
    )
    monkeypatch.syspath_prepend(str(old_root.parent))
    hostile_package = types.ModuleType("review_core")
    hostile_package.__path__ = [str(old_root)]  # type: ignore[attr-defined]
    hostile_package.__file__ = str(old_root / "__init__.py")
    monkeypatch.setitem(sys.modules, "review_core", hostile_package)
    monkeypatch.delitem(sys.modules, "review_core.core", raising=False)

    loader = importlib.import_module(
        "infrastructure.isolated_package_loader"
    ).load_isolated_package_module
    consumer = loader(
        PACKAGE_PARENT,
        package_directory="review_core",
        module_leaf="consumer",
        namespace_prefix="hostile_path",
    )
    core = consumer._core_module()

    assert Path(core.__file__).resolve().is_relative_to(PACKAGE_DIR.resolve())
    assert old_root.resolve() not in Path(core.__file__).resolve().parents
    assert core.__name__.startswith("_hostile_path_")
