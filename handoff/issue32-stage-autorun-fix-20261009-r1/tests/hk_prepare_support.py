"""Synthetic import dependencies only; not an actual-owner closure or business data."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import types
import uuid
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TREE = ROOT / os.environ.get("ISSUE32_HK_PREPARE_TREE", "after")


class SyntheticStoreError(ValueError):
    pass


def canonical_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_json(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def resolve_under(root, relative):
    root = Path(root).resolve()
    result = (root / relative).resolve()
    result.relative_to(root)
    return result


def validate_date(value):
    if not isinstance(value, str) or len(value) != 8:
        raise ValueError("date must use YYYYMMDD")
    datetime.strptime(value, "%Y%m%d")
    return value


def load_master(monkeypatch, owner):
    namespace = "_issue32_hk_prepare_" + uuid.uuid4().hex
    package = types.ModuleType(namespace)
    package.__path__ = []
    monkeypatch.setitem(sys.modules, namespace, package)
    dependencies = {
        "hashing": {
            "canonical_bytes": canonical_bytes,
            "sha256_json": sha256_json,
            "sha256_file": lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest(),
        },
        "paths": {"validate_date": validate_date, "resolve_under": resolve_under},
        "store": {"StoreError": SyntheticStoreError},
    }
    for leaf, attrs in dependencies.items():
        module = types.ModuleType(namespace + "." + leaf)
        module.__dict__.update(attrs)
        monkeypatch.setitem(sys.modules, module.__name__, module)
    relative = (
        "source/actual_shared_owner/shared_data/hk_security_master.py"
        if owner == "actual"
        else "source/canonical_reference/upstreams/v3_shared_data/shared_data/hk_security_master.py"
    )
    spec = importlib.util.spec_from_file_location(namespace + ".hk_security_master", TREE / relative)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def rows():
    return [{
        "code": "HK.00001", "name": "SYNTHETIC HK FIXTURE",
        "outstanding_shares": 1000, "circular_market_val": 5000,
        "listing_date": "2000-01-01", "lot_size": 100,
        "stock_owner": "SYNTHETIC", "stock_child_type": "",
        "sec_status": "NORMAL",
    }]


def publish(master, root, *, trade_date="20261008", captured_at="2026-10-08T17:30:00+08:00", name=None):
    values = rows()
    if name:
        values[0]["name"] = name
    return master.publish_hk_security_master(
        root, trade_date=trade_date, rows=values,
        universe_codes_sha256=sha256_json(["HK.00001"]), captured_at=captured_at,
    )


def file_bytes(root):
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def load_ensure(monkeypatch, owner, master, *, codes=None, collector=None):
    """Real ensure plus test-boundary acquire facade, because its source is absent."""
    codes = codes or ["HK.00001"]
    def unexpected_collection(*args, **kwargs):
        raise AssertionError("current Futu collection must not run during verified restore")
    acquire = types.SimpleNamespace(
        load_verified_hk_security_master=master.load_verified_hk_security_master,
        publish_hk_security_master=master.publish_hk_security_master,
        StoreError=SyntheticStoreError,
        resolve_stage_universe=lambda *args: types.SimpleNamespace(codes=codes, codes_sha256=sha256_json(codes)),
        collect_futu_hk_security_master=collector or unexpected_collection,
    )
    def isolated_loader(package_root, *, package_directory, module_leaf, namespace_prefix):
        if (package_directory, module_leaf) == ("scripts", "acquire_hk_security_master"):
            return acquire
        if (package_directory, module_leaf) == ("shared_data", "hk_security_master"):
            return master
        raise AssertionError("unexpected missing-owner module request")
    infrastructure = types.ModuleType("infrastructure")
    infrastructure.__path__ = []
    loader = types.ModuleType("infrastructure.isolated_package_loader")
    loader.load_isolated_package_module = isolated_loader
    infrastructure.isolated_package_loader = loader
    monkeypatch.setitem(sys.modules, "infrastructure", infrastructure)
    monkeypatch.setitem(sys.modules, loader.__name__, loader)
    relative = (
        "source/actual_pool_scheduler/ops/ensure_hk_security_master.py"
        if owner == "actual"
        else "source/canonical_reference/ops/ensure_hk_security_master.py"
    )
    namespace = "_issue32_hk_ensure_" + uuid.uuid4().hex
    spec = importlib.util.spec_from_file_location(namespace, TREE / relative)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, namespace, module)
    spec.loader.exec_module(module)
    return module
