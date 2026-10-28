"""Read-only adapter for the shared exact-date Baimao observation store.

The shared package remains the sole verifier for artifact, manifest, receipt and
SHA integrity.  This module only locates that package from an explicit trusted
root and projects its verified payload into the V4 response DTO.
"""
from __future__ import annotations

import datetime as _datetime
import importlib
import importlib.util
import os
import re
import sys
from pathlib import Path
from typing import Any, Mapping

_SCHEMA_VERSION = "BAIMAO_RESEARCH_OBSERVATION_V1"
_PACKAGE_ENV = "V3_SHARED_DATA_PACKAGE_ROOT"
_STORE_ENV = "V3_SHARED_BAIMAO_OBSERVATION_ROOT"
_DATE_RE = re.compile(r"^\d{8}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_CODE_RE = re.compile(r"^(?:\d{6}\.(?:SH|SZ|BJ)|\d{5,6}\.HK)$")
_STATES = frozenset({"RESEARCH_MAP", "WATCH_ONLY", "UNVERIFIED", "CANNOT_CONFIRM"})
_MARKETS = frozenset({"A/BJ", "HK"})
_SAFETY = {
    "source_merge_role": "SOURCE_ONLY",
    "stage_selection_eligible": False,
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}
_ROW_FIELDS = (
    "market",
    "code",
    "name",
    "theme",
    "source_refs",
    "evidence_grade",
    "state",
    "capture_mechanism",
    "strongest_link",
    "weakest_link",
    "upgrade_conditions",
    "invalidation_conditions",
)
def _invalid(message: str) -> ValueError:
    return ValueError(f"invalid shared Baimao observations: {message}")

def _date(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _DATE_RE.fullmatch(value):
        raise _invalid(f"{field} must use YYYYMMDD")
    try:
        _datetime.datetime.strptime(value, "%Y%m%d")
    except ValueError as error:
        raise _invalid(f"{field} is not a real calendar date") from error
    return value

def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid(f"{field} is missing")
    return value.strip()

def _sha(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _SHA_RE.fullmatch(value):
        raise _invalid(f"{field} is invalid")
    return value

def _safety_matches(value: Any, expected: Any) -> bool:
    return value is expected if isinstance(expected, bool) else value == expected

def _default_package_root() -> Path:
    source = Path(__file__).resolve()
    for parent in source.parents:
        candidate = parent / "v3_shared_data"
        if (candidate / "shared_data" / "baimao_observations.py").is_file():
            return candidate
    raise _invalid("v3_shared_data package root not found")

def _package_root() -> Path:
    configured = os.environ.get(_PACKAGE_ENV, "").strip()
    root = Path(configured).expanduser() if configured else _default_package_root()
    return root.resolve()
def _trusted_shared_module(root: Path) -> Any:
    package_dir = root / "shared_data"
    expected_init = (package_dir / "__init__.py").resolve()
    expected_module = (package_dir / "baimao_observations.py").resolve()
    if not expected_init.is_file() or not expected_module.is_file():
        raise _invalid("trusted shared module is missing")

    package = sys.modules.get("shared_data")
    if package is None:
        spec = importlib.util.spec_from_file_location(
            "shared_data",
            expected_init,
            submodule_search_locations=[str(package_dir)],
        )
        if spec is None or spec.loader is None:
            raise _invalid("trusted shared package spec unavailable")
        package = importlib.util.module_from_spec(spec)
        sys.modules["shared_data"] = package
        try:
            spec.loader.exec_module(package)
        except Exception as error:
            sys.modules.pop("shared_data", None)
            raise _invalid("trusted shared package failed to load") from error

    package_file = Path(str(getattr(package, "__file__", ""))).resolve()
    package_paths = getattr(package, "__path__", ())
    package_path_values = [Path(str(item)).resolve() for item in package_paths]
    if package_file != expected_init or package_path_values != [package_dir.resolve()]:
        raise _invalid("cached shared package resolved outside configured root")

    module = sys.modules.get("shared_data.baimao_observations")
    if module is None:
        try:
            module = importlib.import_module("shared_data.baimao_observations")
        except Exception as error:
            raise _invalid("trusted shared observation module failed to load") from error
    module_file = Path(str(getattr(module, "__file__", ""))).resolve()
    if module_file != expected_module:
        raise _invalid("cached shared observation module resolved outside configured root")
    verifier = getattr(module, "load_verified_observations", None)
    if not callable(verifier):
        raise _invalid("shared observation verifier is unavailable")
    return module

def _store_root(package_root: Path, explicit: Path | str | None) -> Path:
    if explicit is not None:
        return Path(explicit).expanduser()
    configured = os.environ.get(_STORE_ENV, "").strip()
    if configured:
        return Path(configured).expanduser()
    return package_root / ".runtime" / "data" / "baimao_observations"

def _list_of_text(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise _invalid(f"{field} is invalid")
    result = [_text(item, field) for item in value]
    return result
def _row(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid("observation row is not an object")
    missing = [field for field in _ROW_FIELDS if field not in value]
    if missing:
        raise _invalid("observation row fields missing: " + ",".join(missing))

    market = value["market"]
    code = value["code"]
    if market not in _MARKETS or not isinstance(code, str) or not _CODE_RE.fullmatch(code):
        raise _invalid("observation market/code is invalid")
    expected_market = "HK" if code.endswith(".HK") else "A/BJ"
    if market != expected_market:
        raise _invalid("observation market/code mismatch")
    state = value["state"]
    if state not in _STATES or (market == "HK" and state != "CANNOT_CONFIRM"):
        raise _invalid("observation state is invalid")

    result: dict[str, Any] = {
        "market": market,
        "code": code,
        "name": _text(value["name"], "observation name"),
        "theme": _text(value["theme"], "observation theme"),
        "source_refs": _list_of_text(value["source_refs"], "source_refs"),
        "evidence_grade": _text(value["evidence_grade"], "evidence_grade"),
        "state": state,
        "capture_mechanism": _text(value["capture_mechanism"], "capture_mechanism"),
        "strongest_link": _text(value["strongest_link"], "strongest_link"),
        "weakest_link": _text(value["weakest_link"], "weakest_link"),
        "upgrade_conditions": _list_of_text(value["upgrade_conditions"], "upgrade_conditions"),
        "invalidation_conditions": _list_of_text(
            value["invalidation_conditions"], "invalidation_conditions"
        ),
    }
    if "chokepoint" in value:
        chokepoint = value["chokepoint"]
        if chokepoint is not None and (not isinstance(chokepoint, str) or not chokepoint.strip()):
            raise _invalid("observation chokepoint is invalid")
        if isinstance(chokepoint, str) and chokepoint.strip():
            result["chokepoint"] = chokepoint.strip()
    for key, expected in _SAFETY.items():
        if key in value and not _safety_matches(value[key], expected):
            raise _invalid(f"row safety flag {key} is unsafe")
    result.update(_SAFETY)
    return result

def _project(payload: Any, source_date: str) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise _invalid("verifier payload is not an object")
    if payload.get("schema_version") != _SCHEMA_VERSION:
        raise _invalid("schema_version mismatch")
    for key, expected in _SAFETY.items():
        if not _safety_matches(payload.get(key), expected):
            raise _invalid(f"top-level safety flag {key} is unsafe")
    if payload.get("source_date") != source_date:
        raise _invalid("source_date mismatch")

    effective_trade_date = _date(payload.get("effective_trade_date"), "effective_trade_date")
    source_run_id = _text(payload.get("source_run_id"), "source_run_id")
    source_artifact_sha256 = _sha(payload.get("source_artifact_sha256"), "source_artifact_sha256")
    source_report_sha256 = _sha(payload.get("source_report_sha256"), "source_report_sha256")
    article_url = _text(payload.get("article_url"), "article_url")
    title = _text(payload.get("title"), "title")
    published_at = _text(payload.get("published_at"), "published_at")

    counts = payload.get("counts")
    observations = payload.get("observations")
    if not isinstance(counts, Mapping) or not isinstance(observations, Mapping):
        raise _invalid("counts/observations missing")
    a_bj_raw = observations.get("a_bj")
    hk_raw = observations.get("hk")
    if not isinstance(a_bj_raw, list) or not isinstance(hk_raw, list):
        raise _invalid("observation market groups are invalid")
    a_bj = [_row(item) for item in a_bj_raw]
    hk = [_row(item) for item in hk_raw]
    expected_counts = {"a_bj": len(a_bj), "hk": len(hk), "total": len(a_bj) + len(hk)}
    actual_counts: dict[str, int] = {}
    for key in expected_counts:
        value = counts.get(key)
        if isinstance(value, bool) or not isinstance(value, int):
            raise _invalid("observation counts are invalid")
        actual_counts[key] = value
    if actual_counts != expected_counts:
        raise _invalid("observation counts mismatch")
    codes = [item["code"] for item in a_bj + hk]
    if len(codes) != len(set(codes)):
        raise _invalid("duplicate observation code")

    return {
        "schema_version": _SCHEMA_VERSION,
        "source_date": source_date,
        "effective_trade_date": effective_trade_date,
        "source_run_id": source_run_id,
        "source_artifact_sha256": source_artifact_sha256,
        "source_report_sha256": source_report_sha256,
        "article_url": article_url,
        "title": title,
        "published_at": published_at,
        "counts": expected_counts,
        "observations": {"a_bj": a_bj, "hk": hk},
        **_SAFETY,
    }

def load_baimao_research_observations(
    source_date: str, store_root: Path | str | None = None
) -> dict[str, Any]:
    """Load one exact source date from the verified shared observation store."""
    exact_source_date = _date(source_date, "source_date")
    package_root = _package_root()
    module = _trusted_shared_module(package_root)
    root = _store_root(package_root, store_root)
    verifier = module.load_verified_observations
    try:
        payload = verifier(root, exact_source_date)
    except Exception as error:
        raise _invalid("shared verifier rejected exact source date") from error
    return _project(payload, exact_source_date)


__all__ = ["load_baimao_research_observations"]
