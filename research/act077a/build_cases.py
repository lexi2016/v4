"""Construct a case from a locked TDX prefix or bind frozen Route C inputs."""

from __future__ import annotations

from pathlib import Path

from research.act069b.adapter import Adapter, Bar
from research.act070a.case_contract import iso_day, require, sha256, strict_json
from research.act071a.build_cases import build_case, write_case
from research.act071a.case_contract import B_SCHEMA, KB_RULES, verify_case
from research.act071b.generate_cases import ACT069B_CONTRACT, _signed_case
from research.act071b.selection import Proxy, b2_for_day
from research.act077a.p4 import BINDING, CHART_SESSIONS, bind_p4, chart_bars
from research.act077a.route_c_cli import ROUTE, ROUTE_CASES, register_routes


def _scope(case_id: str) -> str:
    chosen = next((scope for scope, pattern in ROUTE_CASES.items() if pattern.fullmatch(case_id)), None)
    require(chosen is not None, "UNREGISTERED_ACT077A_CASE", case_id)
    return chosen


def _bind_and_write(group: Path, base: dict, svg: bytes, png: bytes, schema: bytes, kb: bytes) -> dict:
    patched = bind_p4(base)
    case_id = base["case_id"]
    verify_case(patched, svg, png, schema, kb, case_id, patched["input_sha256"], verify_raster=False)
    receipt = write_case(group, (patched, svg, png), schema, kb)
    receipt.update({
        "base_input_sha256": base["input_sha256"], "p4_binding": BINDING,
        "p4_updated_row_ids": [row["row_id"] for row in patched["rows"] if row.get("primitive_id") == "P4"],
        "min_delivered_chart_date": chart_bars(patched)[0]["fields"]["date"],
    })
    return receipt


def write_bound_case(case_dir: Path, group: Path, *, trusted_case_sha256: str) -> dict:
    """Verify the original A-held package and write the derivative to a separate group."""
    register_routes()
    case_id = case_dir.name
    scope = _scope(case_id)
    require(not (group / case_id).resolve().is_relative_to(case_dir.parent.resolve()),
            "OUTPUT_TOUCHES_FROZEN_GROUP", case_id)
    base = strict_json((case_dir / "input.json").read_bytes())
    require(base["scope"] == scope, "ACT077A_SCOPE_MISMATCH", case_id)
    svg, png = (case_dir / "chart.svg").read_bytes(), (case_dir / "chart.png").read_bytes()
    schema, kb = (case_dir / B_SCHEMA.name).read_bytes(), (case_dir / KB_RULES.name).read_bytes()
    verify_case(base, svg, png, schema, kb, case_id, trusted_case_sha256)
    return _bind_and_write(group, base, svg, png, schema, kb)


def case_bundle(case_id: str, case: dict, market: list[dict], lock: dict, group: Path) -> dict:
    """Transcribe the ACT076A build interface over a previously locked exact prefix."""
    register_routes()
    scope = _scope(case_id)
    code, day = case["code"], case["d"]
    parsed = [iso_day(row["date"]) for row in market]
    require(len(parsed) >= CHART_SESSIONS and parsed == sorted(set(parsed)) and str(parsed[-1]) == day,
            "INVALID_D_PREFIX", case_id)
    contract_raw = ACT069B_CONTRACT.read_bytes()
    contract = strict_json(contract_raw)
    source_id = "act066d_tdx_raw_d_only" if scope == ROUTE else "act077a_prelocked_tdx_raw_d_only"
    contract.update({"symbol": code, "source_generation": lock["raw_archive_sha256"],
                     "price_basis": lock["price_basis"], "volume_basis": lock["volume_basis"]})
    contract["sources"]["bars"] = {
        "locator": f"{source_id}:symbol={code};through={day}",
        "sha256": case["raw_prefix_sha256"],
    }
    adapter = Adapter(contract)
    for bar in market[-2:]:
        adapter.advance(Bar.from_row(bar))
    prior, last = adapter.bars
    quadrant = (0 if last.close > last.open else 2) + (0 if last.volume > prior.volume else 1)
    proxy = Proxy(len(market) - 1, last.day, quadrant)
    rows, immutable = _signed_case(case_id, code, proxy, market, adapter)
    for row in rows:
        if row["kind"] == "CHART_BAR":
            row["source"]["id"] = source_id
        if row["kind"] == "A_CONTEXT":
            row["source"]["id"] = "act077a_route_c"
    require(immutable["day_eligibility"] == b2_for_day(last), "INVALID_B2_INVARIANT", case_id)
    schema, kb = B_SCHEMA.read_bytes(), KB_RULES.read_bytes()
    hashes = {
        "tdx_raw_archive": lock["raw_archive_sha256"], "tdx_d_prefix": case["raw_prefix_sha256"],
        "act069b_adapter_contract": sha256(contract_raw),
        "state_machine_contract": contract["sources"]["contract"]["sha256"],
    }
    base, svg, png = build_case(case_id=case_id, stock_code=code, day=day, scope=scope, rows=rows,
                                immutable_b2=immutable, source_sha256=hashes, schema=schema, kb=kb)
    receipt = _bind_and_write(group, base, svg, png, schema, kb)
    if "kb_case_id" in case:
        receipt["kb_case_id"] = case["kb_case_id"]
    return receipt
