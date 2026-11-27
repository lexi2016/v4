"""Read same-day formula groups from sealed copies of the original owner products."""
from __future__ import annotations

from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any


FORMULA_LABELS = {"b23_entry": "192选股", "pb2_confirm": "回测选股"}
APPROVED_FORMULA_SHA256 = {
    "b23_entry": "7834657819023edfbe5c77628e478c0fca996e728689b7dcc609f3a8c3254581",
    "pb2_confirm": "f7b5f5a543325c2e681671ca23c4039cb9cf6749931eb7c262b36e77d38a2307",
}
ASSETS = frozenset({"owner_pointer.json", "owner_artifact.json", "owner_receipt.json", "numeric_manifest.json", "visible_scope.json"})
SAFETY_FLAGS = {"RESEARCH_ONLY": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}


def _require(condition: object) -> None:
    if not condition:
        raise ValueError("Formula-group owner binding is missing or inconsistent")


def _iso_day(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 10 and date.fromisoformat(value).isoformat() == value


def _is_sha(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch("[0-9a-f]{64}", value) is not None


def _read_object(path: Path, digest: str | None = None) -> dict[str, Any]:
    _require(not path.is_symlink() and path.is_file())
    raw = path.read_bytes()
    _require(digest is None or sha256(raw).hexdigest() == digest)
    obj = json.loads(raw)
    _require(isinstance(obj, dict))
    return obj


def _reference(value: Any, digest: str) -> bool:
    return (isinstance(value, dict) and isinstance(value.get("path"), str)
            and bool(value["path"]) and value.get("sha256") == digest)


def _safe(*objects: dict[str, Any]) -> bool:
    return all(obj.get(key) is expected for obj in objects for key, expected in SAFETY_FLAGS.items())


def _counts_match(reported: Any, actual: dict[str, int]) -> bool:
    return (isinstance(reported, dict) and reported == actual
            and all(type(count) is int for count in reported.values()))


def _read_rows(artifact: dict, scope: dict) -> tuple[list[dict], dict[str, int], dict[str, int], int]:
    original_rows: dict[str, tuple[str, set[str]]] = {}
    raw_counts = dict.fromkeys(FORMULA_LABELS, 0)
    _require(isinstance(artifact.get("rows"), list))
    for row in artifact["rows"]:
        _require(isinstance(row, dict))
        symbol, name, groups = row.get("symbol"), row.get("display_name"), row.get("groups")
        _require(isinstance(symbol, str) and re.fullmatch(r"\d{6}\.(SH|SZ|BJ)", symbol) and symbol not in original_rows)
        _require(isinstance(name, str) and name.strip())
        _require(isinstance(groups, list) and groups and all(isinstance(group, str) and group in FORMULA_LABELS for group in groups))
        unique_groups = set(groups)
        _require(len(unique_groups) == len(groups))
        original_rows[symbol] = (name, unique_groups)
        for group in unique_groups:
            raw_counts[group] += 1
    _require(_counts_match(artifact.get("group_counts"), raw_counts))

    visible_rows = []
    seen = set()
    visible_counts = dict.fromkeys(FORMULA_LABELS, 0)
    quarantined = 0
    _require(isinstance(scope.get("rows"), list))
    for row in scope["rows"]:
        _require(isinstance(row, dict))
        symbol = row.get("symbol")
        _require(isinstance(symbol, str) and symbol in original_rows and symbol not in seen)
        seen.add(symbol)
        name, owner_groups = original_rows[symbol]
        _require(row.get("display_name") == name)
        eligible, states = row.get("eligible_candidate"), row.get("group_states")
        _require(type(eligible) is bool and isinstance(states, dict) and states.keys() == FORMULA_LABELS.keys())
        classification: dict[str, Any] = {"classification": None}
        if eligible:
            _require(all(states[group] == ("TRUE" if group in owner_groups else "FALSE") for group in FORMULA_LABELS))
            for group in owner_groups:
                visible_counts[group] += 1
        else:
            _require(row.get("source_groups") is None and all(state == "UNKNOWN" for state in states.values()))
            classification["identity_status"] = "IDENTITY_CONFLICT_NAME"
            quarantined += 1
        visible_rows.append({
            "symbol": symbol,
            "display_name": name,
            "enriched_display_name": name,
            "source_row": {"symbol": symbol, "display_name": name},
            "group_states": states,
            "eligible_candidate": eligible,
            "classification": classification,
            "history_rates": {},
        })
    _require(_counts_match(scope.get("group_counts"), visible_counts))
    _require(seen == original_rows.keys())
    _require(type(scope.get("quarantined_identity_count")) is int and scope["quarantined_identity_count"] == quarantined)
    return visible_rows, raw_counts, visible_counts, quarantined


def read_formula_day(root: Path, source_date: str) -> dict[str, Any] | None:
    """Resolve fixed local copies only. Never follow the paths in the owner records."""
    try:
        _require(_iso_day(source_date))
        folder = root / source_date
        _require(not root.is_symlink() and not folder.is_symlink())
        binding = _read_object(folder / "binding.json")
        date_pair = (source_date, binding.get("observation_date"))
        _require(binding.get("schema") == "V4_R20_ISOLATED_FORMULA_BINDING_V1" and binding.get("source_date") == source_date)
        _require(_iso_day(date_pair[1]) and date_pair[1] > source_date)
        _require(binding.get("approved_formula_sha256") == APPROVED_FORMULA_SHA256)
        _require(_is_sha(binding.get("original_day_sha256")))
        refs = binding.get("files")
        _require(isinstance(refs, dict) and refs.keys() == ASSETS and all(_is_sha(digest) for digest in refs.values()))
        assets = {filename: _read_object(folder / filename, refs[filename]) for filename in ASSETS}
        pointer, artifact, receipt, numeric, scope = (
            assets[name] for name in ("owner_pointer.json", "owner_artifact.json", "owner_receipt.json", "numeric_manifest.json", "visible_scope.json")
        )
        _require(_safe(pointer, artifact, receipt, numeric))
        _require(pointer.get("schema") == "V4_WORKBENCH_MODULE_COMMIT_V1" and pointer.get("module") == "formula_groups")
        _require(pointer.get("date") == source_date and receipt.get("source_date") == source_date and receipt.get("status") == "COMMITTED")
        _require(_reference(pointer.get("artifact"), refs["owner_artifact.json"]) and pointer.get("artifact") == receipt.get("artifact"))
        _require(_reference(pointer.get("receipt"), refs["owner_receipt.json"]))
        _require(artifact.get("schema") == "V4_WORKBENCH_FORMULA_GROUP_OVERRIDE_V1")
        _require(artifact.get("formula_sha256") == APPROVED_FORMULA_SHA256)
        _require(all((obj.get("source_date"), obj.get("observation_date")) == date_pair for obj in (artifact, scope)))
        numeric_ref = artifact.get("numeric_manifest")
        _require(_reference(numeric_ref, refs["numeric_manifest.json"]) and receipt.get("numeric_manifest") == numeric_ref)
        _require(numeric.get("schema_version") == "v4.a_share.daily_product_manifest.v1" and numeric.get("data_date") == source_date.replace("-", ""))
        generation, input_sha, selector = artifact.get("generation"), artifact.get("input_sha256"), artifact.get("selector_sha256")
        _require(all(_is_sha(value) for value in (generation, input_sha, selector)))
        _require(receipt.get("generation") == numeric.get("source_generation") == scope.get("generation") == generation)
        _require(numeric.get("input_sha256") == scope.get("input_sha256") == input_sha and scope.get("source_selector_sha256") == selector)
        _require(scope.get("original_day_sha256") == binding["original_day_sha256"])
        rows, raw_counts, visible_counts, quarantined = _read_rows(artifact, scope)
        processed = numeric.get("processed_count")
        _require(type(processed) is int and processed >= len(rows) and numeric.get("sample_only") is False)
        return {
            "source_date": source_date,
            "observation_date": date_pair[1],
            "revision": generation,
            "generation": generation,
            "input_sha256": input_sha,
            "source_selector_sha256": selector,
            "numeric_manifest": numeric_ref,
            "schema": "RESEARCH_SYSTEM_DAY_V1",
            "rows": rows,
            "count": len(rows),
            "scope_count": len(rows),
            "original_processed_count": processed,
            "formula_review": "PENDING",
            "chart_review": "UNKNOWN_NOT_REVIEWED",
            "formula_groups": {
                "labels": FORMULA_LABELS,
                "group_counts": visible_counts,
                "source_group_counts": raw_counts,
                "quarantined_identity_count": quarantined,
                "formula_sha256": APPROVED_FORMULA_SHA256,
                "status": "READY" if any(visible_counts.values()) else "READY_EMPTY",
                "artifact": pointer["artifact"],
            },
            "source_refs": {"owner_pointer_sha256": refs["owner_pointer.json"],
                            "original_day_sha256": binding["original_day_sha256"]},
            "workflow": [],
            "materials": [],
            "reference_links": [],
            **SAFETY_FLAGS,
        }
    except (ValueError, OSError):
        return None


def list_formula_days(root: Path) -> dict[str, dict[str, Any]]:
    try:
        return {child.name: day for child in root.iterdir() if (day := read_formula_day(root, child.name)) is not None}
    except OSError:
        return {}
