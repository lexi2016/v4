"""Synthetic byte-contract checks only; no actual quote, collector or producer run."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import struct

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "ops/research_panel_qfq.py"
spec = importlib.util.spec_from_file_location("r27_qfq_contract", SOURCE)
qfq = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qfq)


def ref(path):
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def put(path, value):
    path.write_text(json.dumps(value, sort_keys=True))
    return ref(path)


def raw(day, *, malformed=False):
    row = struct.pack("<IIIIIfII", day, 1000, 1100, 900, 1000, 100000., 10000, 0)
    return row[:20] + struct.pack("<II", 0x00400000, 0) + row[28:] if malformed else row


@pytest.fixture
def case(tmp_path):
    code = "002335.SZ"
    original = raw(20260721) + raw(20260722, malformed=True)
    corrected = raw(20260721) + raw(20260722)
    dates = [20261020, 20261021, 20261022, 20261023]
    files = {}
    for name, payload in [("original", original), ("corrected", corrected),
                          ("after", corrected + b"".join(raw(day) for day in dates)),
                          ("archive", corrected)]:
        path = tmp_path / (name + ".day")
        path.write_bytes(payload)
        files[name] = ref(path)
    provider = put(tmp_path / "provider.json", {"synthetic_fixture_only": True})
    review_ref = {"path": "synthetic-independent-tail-review", "sha256": "1" * 64}
    seed_review = {"path": "synthetic-independent-seed-review", "sha256": "2" * 64}
    binding = dict(original_native_before=files["original"], native_before=files["corrected"],
                   native_after=files["after"], native_appended_dates=dates, added_dates=dates,
                   native_cutoff=20260722, independent_review=review_ref)
    before_item = dict(raw_files=[dict(files["archive"], source_role="archive"),
                                 dict(files["original"], source_role="native")], history_end_date=20260722)
    after_item = dict(raw_files=[dict(files["archive"], source_role="archive"),
                                dict(files["after"], source_role="native")])
    plan = dict(code=code, trade_date=20260722, record_bytes=32,
                target_native_before=files["original"], archive_payload=files["archive"],
                native_byte_offset=32, archive_byte_offset=32,
                native_original_row_sha256=hashlib.sha256(original[32:]).hexdigest(),
                archive_whole_row_sha256=hashlib.sha256(corrected[32:]).hexdigest())
    seed_report = dict(code=code, trade_date=20260722, original_native_before=files["original"],
                       restored_native_before=files["corrected"])
    tail_report = dict(code=code, native_before=files["corrected"], native_after=files["after"],
                       native_appended_dates=dates, added_dates=dates, native_cutoff=20260722,
                       provider_response=provider, provider_query_started_utc="SYNTHETIC_CAPTURE",
                       old_native_prefix_unchanged=True, full_seed_gate_passed=True,
                       field_signature_gate_passed=True, returned_continuity_gate_passed=True,
                       old_keys_lost=0, old_values_changed=0, buffer_admitted_as_full_history=False,
                       old_selected_raw_sha256=qfq._tail_selected_bytes_sha(before_item["raw_files"], dates[-1]),
                       staged_sha256=qfq._tail_selected_bytes_sha(after_item["raw_files"], dates[-1]))
    scope = dict(review_ref=review_ref, reports={code: tail_report},
                 rows={code: dict(native=files["original"], original_MAC_response=provider,
                                  source_query_started_utc="SYNTHETIC_CAPTURE")}, archive_only=set(),
                 restorations=dict(review_ref=seed_review, planned={code: plan}, reports={code: seed_report}))
    before = dict(sources=[dict(files["archive"], name="archive", kind="day_bytes"),
                           dict(files["original"], name="native", kind="day_bytes")])
    after = dict(sources=[before["sources"][0], dict(files["after"], name="native", kind="day_bytes")])
    retained = dict(accepted_evidence=[review_ref, seed_review])
    return locals()


def check(c):
    qfq._tail_batch_v2_code(c["scope"], c["code"], c["binding"], c["before"], c["after"],
                           c["before_item"], c["after_item"], c["retained"], c["dates"][-1])


def test_exact_original_restored_then_tail_chain(case):
    check(case)
    assert qfq.computation_kernel_sha(SOURCE) == qfq.computation_kernel_sha(
        Path(__import__("os").environ["R27_BASELINE_QFQ"]))


@pytest.mark.parametrize("mutation,match", [
    ("no_context", "PHYSICAL_OR_REVIEW"), ("extra_change", "NOT_EXACT_ARCHIVE_WHOLE_ROW"),
    ("field_splice", "NOT_EXACT_ARCHIVE_WHOLE_ROW"), ("offset", "RECORD_BOUNDARY"),
    ("archive", "ARCHIVE_CHANGED"), ("old_row_sha", "NOT_EXACT_ARCHIVE_WHOLE_ROW"),
    ("wrong_date", "PHYSICAL_BINDING"), ("original_identity", "PHYSICAL_BINDING"),
    ("missing_review", "PHYSICAL_BINDING"), ("tail_prefix", "OLD_NATIVE_BYTES_CHANGED"),
    ("tail_date", "NATIVE_NEW_KEYS_CHANGED"), ("extra_original_binding", "OUTSIDE_EXACT27"),
])
def test_rejects_restoration_or_strict_tail_drift(case, mutation, match):
    c = case
    if mutation == "no_context":
        c["scope"].pop("restorations")
        c["binding"].pop("original_native_before")
    elif mutation in {"extra_change", "field_splice"}:
        path = Path(c["files"]["corrected"]["path"])
        payload = bytearray(path.read_bytes())
        payload[0 if mutation == "extra_change" else 60] ^= 1
        path.write_bytes(payload)
        replacement = ref(path)
        c["binding"]["native_before"] = replacement
        c["seed_report"]["restored_native_before"] = replacement
    elif mutation == "offset":
        c["plan"]["native_byte_offset"] = 33
    elif mutation == "archive":
        c["plan"]["archive_payload"] = dict(c["files"]["archive"], sha256="0" * 64)
    elif mutation == "old_row_sha":
        c["plan"]["native_original_row_sha256"] = "0" * 64
    elif mutation == "wrong_date":
        c["seed_report"]["trade_date"] = 20260723
    elif mutation == "original_identity":
        c["binding"]["original_native_before"] = c["files"]["corrected"]
    elif mutation == "missing_review":
        c["retained"]["accepted_evidence"].remove(c["seed_review"])
    elif mutation == "tail_prefix":
        path = Path(c["files"]["after"]["path"])
        path.write_bytes(c["original"] + b"".join(raw(day) for day in c["dates"]))
        replacement = ref(path)
        c["binding"]["native_after"] = replacement
        c["tail_report"]["native_after"] = replacement
    elif mutation == "tail_date":
        c["binding"]["native_appended_dates"] = c["dates"][:-1]
        c["tail_report"]["native_appended_dates"] = c["dates"][:-1]
    elif mutation == "extra_original_binding":
        c["scope"]["restorations"]["planned"] = {}
    with pytest.raises(qfq.QfqGateError, match=match):
        check(c)


def test_no_restoration_context_retains_original_strict_path(case):
    c = case
    c["scope"].pop("restorations")
    c["binding"].pop("original_native_before")
    c["binding"]["native_before"] = c["files"]["original"]
    c["tail_report"]["native_before"] = c["files"]["original"]
    path = Path(c["files"]["after"]["path"])
    path.write_bytes(c["original"] + b"".join(raw(day) for day in c["dates"]))
    c["files"]["after"] = ref(path)
    c["binding"]["native_after"] = c["files"]["after"]
    c["tail_report"]["native_after"] = c["files"]["after"]
    c["after"]["sources"][1].update(c["files"]["after"])
    c["after_item"]["raw_files"][1].update(c["files"]["after"])
    check(c)


@pytest.mark.parametrize("mutation", ["plan_pin", "self_review", "duplicate", "outside_code", "network", "301139"])
def test_scope_rejects_unapproved_plan_or_review(tmp_path, monkeypatch, mutation):
    codes = [f"{200000 + i:06d}.SZ" for i in range(27)]
    original = {"sha256": "3" * 64}
    rows = [dict(code=code, target_native_before=original) for code in codes]
    observed = {code: dict(native=original) for code in codes}
    plan = put(tmp_path / "synthetic_plan.json", dict(schema="R27_EXACT27_ACCEPTED_ARCHIVE_ROW_RESTORATION_PLAN", rows=rows))
    monkeypatch.setattr(qfq, "TAIL_SEED_RESTORATION_PLAN_SHA", plan["sha256"])
    review = dict(schema="qfq_native_seed_restoration_review_v1", plan=plan,
                  verdict="REVIEWED/PASS_EXACT27_ORIGINAL_ARCHIVE_SEED_RESTORATION",
                  reviewer_id="/independent/SYNTHETIC_ONLY", network_requests=0,
                  research_only=True, production_allowed=False, buy_gate_updated=False, orders_sent=False,
                  reports=[dict(code=code) for code in codes])
    if mutation == "plan_pin":
        review["plan"] = dict(plan, sha256="0" * 64)
    elif mutation == "self_review":
        review["reviewer_id"] = "/root/local_panel_completion_main"
    elif mutation == "duplicate":
        review["reports"][-1] = copy.deepcopy(review["reports"][0])
    elif mutation == "outside_code":
        observed.pop(codes[-1])
    elif mutation == "network":
        review["network_requests"] = 1
    elif mutation == "301139":
        rows[-1]["code"] = "301139.SZ"
        review["reports"][-1]["code"] = "301139.SZ"
        observed["301139.SZ"] = observed.pop(codes[-1])
        plan = put(tmp_path / "synthetic_plan.json", dict(schema="R27_EXACT27_ACCEPTED_ARCHIVE_ROW_RESTORATION_PLAN", rows=rows))
        monkeypatch.setattr(qfq, "TAIL_SEED_RESTORATION_PLAN_SHA", plan["sha256"])
        review["plan"] = plan
    reviewed = put(tmp_path / "synthetic_review.json", review)
    with pytest.raises(qfq.QfqGateError, match="TAIL_SEED_RESTORATION"):
        qfq._tail_seed_restoration_scope(dict(seed_restoration=reviewed), observed)
