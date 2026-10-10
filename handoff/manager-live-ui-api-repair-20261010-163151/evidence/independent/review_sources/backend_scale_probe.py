"""Synthetic 1,970-material/40-binding diagnostic probe; no owner reads."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "candidate"))
from v4.manager_research.workspace_identity import (
    INPUT_IDENTITY_SCHEMA, identity_component, input_identity_diagnostics, semantic_digest,
)

def sha(value):
    return hashlib.sha256(value.encode()).hexdigest()

refs = []
for i in range(40):
    slot = f"07{i:02d}"
    payload = f"research/hourly/live/20261008/{slot}.json"
    refs.append(dict(source_id="V35_RESEARCH_DATA_ROOT", source_root="/ISOLATED_REVIEW/data",
        source_date="20261008", status="VERIFIED", slot=slot, mode="LIVE",
        write_policy="read_only", recommendation_status="RESEARCH_ONLY",
        production_allowed=False, buy_gate_updated=False, orders_sent=False,
        manifest_path="manifest.json", manifest_sha256=sha("global-before"),
        payload_path=payload, payload_sha256=sha(f"payload-{i}"),
        manifest_entry_sha256=sha(f"payload-{i}"),
        receipt_path="receipts/" + payload, receipt_sha256=sha(f"receipt-{i}")))
materials = [dict(material_id=f"synthetic-{i}", available_at="2026-10-08T17:00:00+08:00",
    source_row={"body": "SYNTHETIC_REVIEW_CONTENT " * 320},
    source_refs=[deepcopy(refs[i % 40])]) for i in range(1970)]

def projection(rows):
    return dict(input_identity_schema=INPUT_IDENTITY_SCHEMA,
        input_identity=semantic_digest({"materials": rows}),
        input_identity_components={"projection.materials": identity_component(rows)})

started = perf_counter()
saved = projection(materials)
current_rows = deepcopy(materials)
for row in current_rows:
    row["source_refs"][0]["manifest_sha256"] = sha("global-after-unconsumed-entry")
current = projection(current_rows)
assert saved["input_identity"] == current["input_identity"]
assert input_identity_diagnostics(saved, current)["status"] == "MATCH"
assert len(saved["input_identity_components"]["projection.materials"]["sources"]) == 40
assert len(current["input_identity_components"]["projection.materials"]["sources"]) == 40
target_path = refs[0]["payload_path"]
for row in current_rows:
    if row["source_refs"][0]["payload_path"] == target_path:
        row["source_refs"][0]["receipt_sha256"] = sha("receipt-changed")
changed = projection(current_rows)
diagnostics = input_identity_diagnostics(saved, changed)
assert diagnostics["status"] == "CHANGED"
assert [row["component"] for row in diagnostics["changed_components"]] == ["projection.materials"]
component = diagnostics["changed_components"][0]
assert len(component["saved_sources"]) == len(component["current_sources"]) == 40
by_path = lambda rows: {row["payload_path"]: row for row in rows}
old_refs, new_refs = by_path(component["saved_sources"]), by_path(component["current_sources"])
receipt_changes = [key for key in old_refs if old_refs[key]["receipt_sha256"] != new_refs[key]["receipt_sha256"]]
assert receipt_changes == [target_path]
assert materials[0]["source_refs"][0] == refs[0]
result = dict(status="PASS_SYNTHETIC_DIAGNOSTIC_SCALE", material_count=len(materials),
    unique_source_bindings=40, changed_consumed_binding_count=1,
    diagnostic_component_count=len(diagnostics["changed_components"]),
    source_rows_in_each_diagnostic_side=40,
    diagnostic_json_bytes=len(json.dumps(diagnostics, ensure_ascii=False).encode()),
    synthetic_material_json_bytes=len(json.dumps(materials, ensure_ascii=False).encode()),
    elapsed_seconds=round(perf_counter() - started, 3),
    scope="Synthetic fixture only; no historical raw materials, service latency SLA, or Mac owner/runtime verified.")
(Path(__file__).parent / "backend_scale_probe.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result, indent=2))
