"""Assemble the ACT-071B A receipt and isolated B inputs from an approved Reader projection."""

from __future__ import annotations

import csv
import io
import re
import stat
from collections import Counter
from itertools import combinations
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from research.act069b.adapter import CANNOT_CONFIRM, EXTERNAL_GAPS, UNKNOWN, Adapter
from research.act070a.case_contract import (
    FROZEN_GUARDS, ISO_DATE_TOKEN, OHLCV_FIELDS, iso_day, json_bytes, require, row_id, sha256, strict_json,
)
from research.act070a.generate_cases import signed_rows
from research.act071a.build_cases import build_case, write_case
from research.act071a.case_contract import (
    B_SCHEMA, CASE_FILES, CHART_SESSIONS, FIRST_TEST_DIR, KB_RULES, RECEIPT_SCHEMA, STOCK_PATTERN,
)
from research.act071b.selection import (
    B2_FALSE_MINIMUM, FIRST_D, LAST_D, QUADRANTS, QUOTA, SEED, Proxy, Selection,
    b2_for_day, first_feasible, freeze_pool, stock_hash,
)

ACT069B_CONTRACT = Path(__file__).resolve().parents[1] / "act069b" / "adapter_contract.json"
ROSTER_NAME = "ACT071B_CERTIFIED_STOCK_EXCLUSION_ROSTER_57_20261128.csv"
ROSTER_SHA256 = "519b00ec3bc73ec35a0f4bc42c264c33c5cd0149a13dc306254050ad9a5f069d"
ROSTER_FILE_ID = "1TCh2U75zwihzazTamfCkhSXEZmmatYWK"
ALIASES = {"831039.BJ": "920039.BJ", "837748.BJ": "920748.BJ"}
ROSTER_ADDITIONS = {"002371.SZ", "301269.SZ", "601138.SH"}
EXPECTED_GENERATION = "ef7f12caa2f67a4a4f26d775d99735b5a9d2845d919087a689d99df6b6322329"
RECEIPT_NAME = "A_CASE_RECEIPT_FIRST_TEST_8D_V1_1.json"
AUDIT_NAME = "selection_and_skip_audit.json"
PANEL_DIGEST_KEYS = ("generation", "panel_sha256", "manifest_sha256")


def certify_exclusions(roster_path: Path) -> dict:
    require(roster_path.name == ROSTER_NAME, "INVALID_ROSTER_PATH", roster_path.name)
    raw = roster_path.read_bytes()
    require(sha256(raw) == ROSTER_SHA256, "EXCLUSION_ROSTER_HASH_MISMATCH", roster_path.name)
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    require("stock_code" in (reader.fieldnames or []), "INVALID_EXCLUSION_ROSTER", "stock_code")
    codes = [row["stock_code"] for row in reader]
    require(len(codes) == len(set(codes)) == 57 and all(STOCK_PATTERN.fullmatch(code) for code in codes),
            "INVALID_EXCLUSION_ROSTER", "57 distinct canonical codes")
    require(set(ALIASES.values()) | ROSTER_ADDITIONS <= set(codes) and not set(ALIASES) & set(codes),
            "INVALID_EXCLUSION_ROSTER", "certified additions and separate historical aliases")
    return {"file_id": ROSTER_FILE_ID, "sha256": ROSTER_SHA256,
            "canonical_codes": sorted(codes), "historical_aliases": ALIASES}


def verify_source_identity(identity: dict) -> None:
    require(identity.get("generation") == EXPECTED_GENERATION
            and identity.get("price_basis") == "QFQ_ASOF" and identity.get("volume_basis") == "QFQ_EVENT_VOLUME",
            "INCORRECT_MARKET_BASIS", "ACT071A generation, QFQ_ASOF and QFQ_EVENT_VOLUME")
    require(all(isinstance(identity.get(key), str) and identity[key] for key in ("panel_path", "manifest_path"))
            and all(isinstance(identity.get(key), str) and re.fullmatch(r"[a-f0-9]{64}", identity[key])
                    for key in PANEL_DIGEST_KEYS), "SOURCE_IDENTITY_MISSING", "canonical Reader identity")


def _signed_case(case_id: str, stock: str, proxy: Proxy, bars: list[dict], adapter: Adapter) -> tuple[list, dict]:
    """Project the frozen light A facts without importing another stock's prior evidence."""
    i, day = proxy.index, str(proxy.day)
    bar, prior = adapter.bars[-1], adapter.bars[-2]
    require(bar is not None and prior is not None and bar.day == proxy.day, "INVALID_CASE", case_id)
    market = adapter.market.at(f"stock_session_index={i};date={day}")
    ledger = adapter._p1(bar, i)
    support = adapter._p2_p3(bar, i, anchor_id=None)
    ledger.extend(support)
    ledger.extend(adapter._p4(segment_id=None))
    ledger.extend((
        adapter._row("P5", "stock_session_bar_observed", {
            "stock_session_index": i, "date": day, "prior_stock_session": str(prior.day),
        }, market),
        adapter._row("P5", "observation_basis_and_cutoff", {
            "market": stock.rsplit(".", 1)[-1], "symbol": stock,
            "source_generation": adapter.contract["source_generation"],
            "price_basis": adapter.contract["price_basis"], "volume_basis": adapter.contract["volume_basis"],
            "observations_used_through": day, "source_asof_vintage_pit": CANNOT_CONFIRM,
        }, market),
    ))
    for name, reason in zip(adapter.contract["primitive_fact_names"]["P5"][2:6], EXTERNAL_GAPS, strict=True):
        value = CANNOT_CONFIRM if name == "historical_point_in_time_status" else UNKNOWN
        ledger.append(adapter._source_gap("P5", name, reason, value))
    require(support[-1]["fact_name"] == "anchored_invalidation", "INVALID_PRIMITIVE_ROSTER", "P3")
    ledger.append({**support[-1], "primitive_id": "P5", "fact_name": "source_bound_structural_veto"})
    status = b2_for_day(bar)
    day_status = {
        "stock_session_index": i, "day_eligibility_method": "B2_D0", "day_eligibility": status,
        "day_eligibility_reason": ("B2_D0_NON_BULLISH_NECESSARY_CONDITION" if status == "FALSE"
                                   else "B2_FORMAL_EVIDENCE_UNBOUND"),
        "event_chain_state_b2": UNKNOWN, "source_locator": market,
    }
    _, rows, immutable_b2 = signed_rows(case_id, day, bars, ledger, day_status)
    for row in rows:
        if row["kind"] == "CHART_BAR":
            row["source"]["id"] = "v4_canonical_qfq_asof_d_only"
        elif row["kind"] == "A_DAY_STATUS":
            row["source"]["id"] = "act069b_independent_d0"
        else:
            row["source"]["id"] = "act069b_light_a_projection"
    rows.append({
        "row_id": row_id(case_id, "A", "CONTEXT"), "kind": "A_CONTEXT", "status": "OBSERVED_D_ONLY",
        "occurred_date": day, "first_knowable_date": day, "source": {"id": "act071b_phase2", "locator": market},
        "fields": {
            "a_proxy_quadrant": QUADRANTS[proxy.quadrant], "p4_segment_binding": "UNBOUND",
            "event_chain_state_b1": UNKNOWN, "event_chain_state_b2": UNKNOWN,
            "event_chain_state_strong_continuation": UNKNOWN, "event_chain_state_m25": UNKNOWN,
        },
    })
    first = iso_day(bars[i + 1 - CHART_SESSIONS]["date"])
    dates = [iso_day(token) for token in ISO_DATE_TOKEN.findall(json_bytes(rows).decode("utf-8"))]
    require(dates and min(dates) == first and max(dates) == proxy.day,
            "HISTORICAL_REFERENCE_OUTSIDE_WINDOW", case_id)
    return rows, immutable_b2


def _write_isolated_zip(path: Path, case_dir: Path) -> str:
    with ZipFile(path, "x", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for name in CASE_FILES:
            entry = ZipInfo(name, (2026, 11, 28, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(entry, (case_dir / name).read_bytes(), compress_type=ZIP_DEFLATED, compresslevel=9)
    return sha256(path.read_bytes())


def _write_cases(stage: Path, selection: Selection, identity: dict, exclusions: dict) -> dict:
    contract_raw = ACT069B_CONTRACT.read_bytes()
    contract = strict_json(contract_raw)
    source_hashes = {
        "generation": identity["generation"], "panel": identity["panel_sha256"],
        "panel_manifest": identity["manifest_sha256"], "certified_exclusion_roster": exclusions["sha256"],
        "act069b_adapter_contract": sha256(contract_raw), "state_machine_contract": contract["sources"]["contract"]["sha256"],
    }
    stock = selection.stock_code
    contract["symbol"] = stock
    contract["sources"]["bars"] = {
        "locator": f"v4_reader:QFQ_ASOF:{identity['generation']}:symbol={stock}",
        "sha256": identity["panel_sha256"],
    }
    schema, kb = B_SCHEMA.read_bytes(), KB_RULES.read_bytes()
    group = stage / FIRST_TEST_DIR
    group.mkdir()
    cases = {}
    bars = []
    for case_number, proxy in enumerate(selection.chosen, start=1):
        case_id = f"T{case_number:02d}"
        for session in selection.sessions[len(bars):proxy.index + 1]:
            bar = session.bar
            fields = {field: getattr(bar, field) for field in OHLCV_FIELDS} if bar else {}
            bars.append({"date": str(session.day), **fields})
        # ACT069B P1/P5 consume D and its prior observed session. Native indices
        # stay explicit, and every structural relation is unbound for this stock.
        adapter = Adapter(contract)
        for session in selection.sessions[proxy.index - 1:proxy.index + 1]:
            adapter.advance(session.bar)
        rows, immutable_b2 = _signed_case(case_id, stock, proxy, bars, adapter)
        bundle = build_case(case_id=case_id, stock_code=stock, day=str(proxy.day), scope="FIRST_TEST",
                            rows=rows, immutable_b2=immutable_b2, source_sha256=source_hashes, schema=schema, kb=kb)
        written = write_case(group, bundle, schema, kb)
        archive_name = f"{case_id}_isolated.zip"
        cases[case_id] = {
            **written, "a_proxy_quadrant": QUADRANTS[proxy.quadrant],
            "isolated_zip": archive_name,
            "isolated_zip_sha256": _write_isolated_zip(stage / archive_name, group / case_id),
        }
    return cases


def _verify_windows(selection: Selection, cases: dict) -> dict:
    quotas = Counter(case["a_proxy_quadrant"] for case in cases.values())
    require(len(cases) == 8 and all(quotas[cell] == QUOTA for cell in QUADRANTS), "INVALID_QUOTA_GRID", str(quotas))
    b2_false = 0
    for (case_id, case), proxy in zip(cases.items(), selection.chosen, strict=True):
        require(case["session_end"] == proxy.index and case["session_start"] == proxy.index + 1 - CHART_SESSIONS,
                "INVALID_NATIVE_WINDOW", case_id)
        actual_status = b2_for_day(selection.sessions[proxy.index].bar)
        require(case["immutable_b2"]["day_eligibility"] == actual_status, "INVALID_B2_INVARIANT", case_id)
        b2_false += actual_status == "FALSE"
    require(b2_false >= B2_FALSE_MINIMUM, "B2_FALSE_QUOTA", selection.stock_code)
    pair_checks = []
    for (left_id, left), (right_id, right) in combinations(cases.items(), 2):
        require(left["session_end"] < right["session_start"], "OVERLAPPING_FIRST_TEST_WINDOWS", f"{left_id}/{right_id}")
        pair_checks.append({"left": left_id, "right": right_id, "left_end": left["session_end"],
                            "right_start": right["session_start"], "nonoverlap": True})
    return {"quadrant_counts": dict(quotas), "b2_false_count": b2_false, "b2_false_minimum": B2_FALSE_MINIMUM,
            "all_references_inside_native_window": True, "pairwise_nonoverlap": pair_checks}


def execute(*, stock_codes, load_sessions, source_identity: dict, roster_path: Path, output_root: Path) -> dict:
    """Run over canonical A-share keys and lazy per-symbol Reader projections provided by A."""
    verify_source_identity(source_identity)
    require(not output_root.exists() and not output_root.is_symlink(), "OUTPUT_EXISTS", str(output_root))
    exclusions = certify_exclusions(roster_path)
    banned = set(exclusions["canonical_codes"]) | set(ALIASES)
    original = tuple(stock_codes)
    pool = freeze_pool(original, banned)
    audit = {
        "act": "ACT-071B", "status": "NO_FEASIBLE_STOCK", "seed": SEED, "guards": FROZEN_GUARDS,
        "requested_d_range_inclusive": [str(FIRST_D), str(LAST_D)],
        "stock_session_index_basis": "zero based from the first actual stock session supplied by the pinned logical Reader",
        "chart_window_width": CHART_SESSIONS, "source": source_identity, "certified_exclusions": exclusions,
        "source_stock_count": len(original), "excluded_count_present_in_source": len(set(original) & banned),
        "candidate_pool_count": len(pool), "candidate_pool_sha256": sha256(json_bytes(pool)),
        "ordered_candidate_pool": pool, "models_called": 0,
    }
    selection, skips = first_feasible(pool, load_sessions)
    audit["predecessor_mechanical_skips"] = skips
    with TemporaryDirectory(prefix=".act071b-", dir=output_root.parent) as temp:
        stage = Path(temp) / "pack"
        stage.mkdir()
        if selection is not None:
            cases = _write_cases(stage, selection, source_identity, exclusions)
            checks = _verify_windows(selection, cases)
            receipt = {
                "schema_version": RECEIPT_SCHEMA, "guards": FROZEN_GUARDS,
                "calibration_count": 0, "first_test_count": len(cases), "first_test_status": "CERTIFIED_STOCK_EXCLUSION",
                "stock_code": selection.stock_code, "cases": cases, "selection_proof": checks, "models_called": 0,
            }
            receipt_raw = json_bytes(receipt) + b"\n"
            (stage / RECEIPT_NAME).write_bytes(receipt_raw)
            audit.update({
                "status": "FIRST_FEASIBLE_STOCK_SELECTED", "selected_stock": selection.stock_code,
                "selected_order_sha256": stock_hash(selection.stock_code), "selected_order_rank": len(skips) + 1,
                "selected_session_coverage": [str(selection.sessions[0].day), str(selection.sessions[-1].day)],
                "effective_d_range_inclusive": [str(max(FIRST_D, selection.sessions[0].day)),
                                                str(min(LAST_D, selection.sessions[-1].day))],
                "cases": cases, "selection_proof": checks, "trusted_receipt_sha256": sha256(receipt_raw),
            })
        (stage / AUDIT_NAME).write_bytes(json_bytes(audit) + b"\n")
        require(not output_root.exists() and not output_root.is_symlink(), "OUTPUT_EXISTS", str(output_root))
        stage.rename(output_root)
    return audit
