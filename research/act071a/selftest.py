"""Exercise the frozen V1.1 protocol with synthetic cases and zero model calls."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import date, timedelta

from research.act070a.case_contract import FROZEN_GUARDS, SOURCE_HASHES, case_digest, json_bytes, sha256
from research.act070a.chart import CHART_SESSIONS
from research.act071a.build_cases import build_case
from research.act071a.case_contract import B_SCHEMA, KB_RULES, OUTPUT_SCHEMA
from research.act071a.validate_b_output import validate_output

CASE = "C01"
D = date(2020, 2, 4)
SCHEMA, KB = B_SCHEMA.read_bytes(), KB_RULES.read_bytes()


def ref(row_id, field):
    return {"row_id": row_id, "field": field}


def link(relation, reference):
    return {"relation": relation, "ref": reference}


def bar_ref(number, field):
    return ref(f"{CASE}_BAR_{number:02d}", field)


def row(item_id, kind, stamp, fields, status="OBSERVED_D_ONLY"):
    return {"row_id": item_id, "kind": kind, "status": status, "occurred_date": stamp,
            "first_knowable_date": stamp, "fields": fields}


def fixture():
    bars = []
    for position in range(1, CHART_SESSIONS + 1):
        stamp = (D + timedelta(days=position - CHART_SESSIONS)).isoformat()
        fields = {"date": stamp, "open": "10", "high": "11", "low": "8", "close": "9", "volume": "100"}
        bar = row(bar_ref(position, "date")["row_id"], "CHART_BAR", stamp, fields)
        bar["source"] = {"id": "synthetic", "stock_session_index": position - 1}
        bars.append(bar)
    immutable_b2 = {
        "day_eligibility": "FALSE", "day_eligibility_reason": "B2_D0_NON_BULLISH_NECESSARY_CONDITION",
        "event_chain_state_b2": "UNKNOWN", "formal_b2_event_presence": "ABSENT",
    }
    facts = [
        row("C01_PRIM_P1_01", "PRIMITIVE", D.isoformat(), {"registered_key_k": "UNKNOWN"}, "MISSING_SOURCE"),
        row("C01_B2_DAY", "A_DAY_STATUS", D.isoformat(), immutable_b2),
        row("C01_AGGREGATE", "PRIMITIVE", D.isoformat(), {"OHLCV": {"open": "10", "close": "9"}}),
    ]
    case, chart, png = build_case(case_id=CASE, stock_code="002865.SZ", day=D.isoformat(),
                                  scope="EXPOSED_REGRESSION", rows=bars + facts, immutable_b2=immutable_b2,
                                  source_sha256=SOURCE_HASHES, schema=SCHEMA, kb=KB)
    assert "OHLCV" in facts[-1]["fields"] and set(case["rows"][-1]["fields"]) == {"ohlcv"}
    claim = {
        "id": "C1", "type": "KEY_K", "status": "CANDIDATE", "phase_label": None,
        "span_refs": {"start": bar_ref(35, "date"), "end": bar_ref(35, "date")},
        "price_refs": {"low": bar_ref(35, "low"), "high": bar_ref(35, "high")},
        "anchor_links": [], "evidence_refs": [bar_ref(35, "close"), bar_ref(35, "volume")],
        "counterevidence_refs": [ref("C01_B2_DAY", "day_eligibility")],
        "kb_rule_ids": ["KB_KEY_K"], "gap_codes": [],
    }
    response = {
        "schema_version": OUTPUT_SCHEMA, "case_id": CASE,
        "input_sha256": case["input_sha256"], "claims": [claim], "abstain_codes": [],
    }
    return case, chart, png, response


def test_result(name, family, expected, verdict):
    result = {"name": name, "family": family, "expected_code": expected, "actual_code": verdict["code"],
              "accepted": verdict["accepted"]}
    result["pass"] = verdict["code"] == expected and verdict["accepted"] == expected.startswith("ACCEPTED_")
    return result


def run_controls():
    case, chart, png, response = fixture()
    results = []

    def check(name, family, expected, *, value=None, raw=None, a_case=None, a_chart=None, a_png=None,
              schema=SCHEMA, kb=KB, trusted_digest=None):
        returned_hash = trusted_digest if trusted_digest is not None else case["input_sha256"]
        verdict = validate_output(
            raw if raw is not None else json_bytes(value if value is not None else response),
            a_case if a_case is not None else case, a_chart if a_chart is not None else chart,
            a_png if a_png is not None else png, schema, kb, CASE, returned_hash,
        )
        results.append(test_result(name, family, expected, verdict))
        return verdict

    legal = check("legal_candidate", "legal", "ACCEPTED_CANDIDATE_ONLY")
    first = legal.get("claims", [{}])[0]
    results[-1]["pass"] &= (
        first.get("occurred_date") == first.get("first_knowable_date") == D.isoformat()
        and first.get("time_rule") == "SINGLE_BAR_KEY_K_V1" and legal.get("immutable_b2") == case["immutable_b2"]
    )
    pivot = deepcopy(response)
    pivot["claims"][0].update(type="PIVOT", kb_rule_ids=["KB_N_BREATHING"],
                              gap_codes=["PIVOT_UNCONFIRMED_AT_D"])
    pivot["claims"][0]["span_refs"]["end"] = None
    pending = check("legal_open_pivot", "legal", "ACCEPTED_CANDIDATE_ONLY", value=pivot)
    first = pending.get("claims", [{}])[0]
    results[-1]["pass"] &= first.get("occurred_date") == first.get("first_knowable_date") == "UNRESOLVED"
    abstain = {**response, "claims": [], "abstain_codes": ["SOURCE_UNBOUND"]}
    check("legal_abstention", "legal", "ACCEPTED_CANDIDATE_ONLY", value=abstain)

    def mutate(name, family, expected, edit):
        value = deepcopy(response)
        edit(value, value["claims"][0])
        check(name, family, expected, value=value)

    mutate("forged_price_ref", "forged_price", "SCHEMA_INVALID",
           lambda _, claim: claim["price_refs"].update(low=bar_ref(35, "forged_price")))
    mutate("bare_price", "forged_price", "SCHEMA_INVALID",
           lambda _, claim: claim["price_refs"].update(low=9.01))
    mutate("price_embedded_in_ref", "forged_price", "SCHEMA_INVALID",
           lambda _, claim: claim["price_refs"]["low"].update(value=9.01))
    mutate("volume_as_price", "forged_price", "SCHEMA_INVALID",
           lambda _, claim: claim["price_refs"].update(low=bar_ref(35, "volume")))
    mutate("out_of_d_row", "reference_boundary", "UNKNOWN_REFERENCE",
           lambda _, claim: claim["evidence_refs"].append(bar_ref(36, "close")))
    mutate("unknown_or_cross_case_row", "reference_boundary", "UNKNOWN_REFERENCE",
           lambda _, claim: claim["evidence_refs"].append(ref("C02_BAR_35", "close")))
    mutate("missing_source_row", "reference_boundary", "MISSING_SOURCE_REFERENCE",
           lambda _, claim: claim["evidence_refs"].append(ref("C01_PRIM_P1_01", "registered_key_k")))
    mutate("raw_date_as_ref", "reference_boundary", "SCHEMA_INVALID",
           lambda _, claim: claim["span_refs"].update(end=D.isoformat()))
    future_case = deepcopy(case)
    future = (D + timedelta(days=1)).isoformat()
    future_case["rows"].append(row("C01_FUTURE", "PRIMITIVE", future, {"foo": "BAR"}))
    future_case["input_sha256"] = case_digest(future_case)
    check("signed_row_after_d", "reference_boundary", "OUT_OF_D_REFERENCE",
          a_case=future_case, trusted_digest=future_case["input_sha256"])

    embedded_future = deepcopy(case)
    embedded_future["rows"][-3]["fields"]["registered_key_k"] = {"date": future}
    embedded_future["input_sha256"] = case_digest(embedded_future)
    check("nested_a_fact_after_d", "reference_boundary", "OUT_OF_D_REFERENCE",
          a_case=embedded_future, trusted_digest=embedded_future["input_sha256"])

    for status in ("RISK_CLEAR", "FORMAL", "CONFIRMED", "CONFIRMED_PIVOT"):
        mutate(f"forbidden_{status.lower()}", "promotion_or_override", "SCHEMA_INVALID",
               lambda _, claim: claim.update(status=status))
    mutate("risk_clear_claim_type", "promotion_or_override", "SCHEMA_INVALID",
           lambda _, claim: claim.update(type="RISK_CLEAR"))
    mutate("b2_override", "promotion_or_override", "SCHEMA_INVALID",
           lambda value, _: value.update(day_eligibility="TRUE", formal_b2_event_presence="PRESENT"))
    mutate("b2_override_as_positive_evidence", "promotion_or_override", "IMMUTABLE_B2_REFERENCE",
           lambda _, claim: claim["evidence_refs"].append(ref("C01_B2_DAY", "day_eligibility")))
    mutate("duplicate_claim_id", "promotion_or_override", "DUPLICATE_CLAIM_ID",
           lambda value, claim: value["claims"].append(deepcopy(claim)))
    raw = json_bytes(response)
    check("duplicate_top_level_key", "promotion_or_override", "DUPLICATE_JSON_KEY",
          raw=b'{"case_id":"C02",' + raw[1:])
    check("duplicate_nested_key", "promotion_or_override", "DUPLICATE_JSON_KEY",
          raw=raw.replace(b'"field":"close"', b'"field":"open","field":"close"', 1))
    mutate("uncorroborated_old_anchor_break", "promotion_or_override", "OLD_ANCHOR_PROOF_REQUIRED",
           lambda _, claim: claim.update(type="OLD_ANCHOR_INVALIDATION", kb_rule_ids=["KB_SUPPORT_BREAK"]))

    anchored_case = deepcopy(case)
    anchor_ref = ref("C01_PRIOR_ANCHOR", "registered_support_object")
    break_ref = ref("C01_BOUND_BREAK", "anchored_invalidation")
    threshold_ref = bar_ref(34, "high")
    close_ref = bar_ref(35, "close")
    anchored_case["rows"].extend((
        row(anchor_ref["row_id"], "PRIMITIVE", (D - timedelta(days=1)).isoformat(),
            {anchor_ref["field"]: {"anchor_id": "SYNTHETIC_ANCHOR", "threshold_ref": threshold_ref}}),
        row(break_ref["row_id"], "PRIMITIVE", D.isoformat(),
            {break_ref["field"]: {"anchor_id": "SYNTHETIC_ANCHOR", "kind": "ACTIVE_ANCHOR_CLOSE_BREAK",
                                  "close_ref": close_ref}}),
    ))
    anchored_case["input_sha256"] = case_digest(anchored_case)
    anchored_response = deepcopy(response)
    anchored_response["input_sha256"] = anchored_case["input_sha256"]
    anchored_response["claims"][0].update(
        type="OLD_ANCHOR_INVALIDATION", kb_rule_ids=["KB_SUPPORT_BREAK"],
        anchor_links=[link("INVALIDATES", anchor_ref), link("REFERENCE", threshold_ref)], evidence_refs=[break_ref, close_ref],
    )
    anchored = check("legal_synthetic_same_anchor_break", "legal", "ACCEPTED_CANDIDATE_ONLY",
                     value=anchored_response, a_case=anchored_case, trusted_digest=anchored_case["input_sha256"])
    first = anchored.get("claims", [{}])[0]
    results[-1]["pass"] &= (first.get("occurred_date") == first.get("first_knowable_date") == D.isoformat()
                            and first.get("time_rule") == "ANCHORED_BREAK_V1"
                            and anchored.get("immutable_b2") == case["immutable_b2"])

    mutate("response_wrong_case", "integrity", "CASE_ID_MISMATCH", lambda value, _: value.update(case_id="C02"))
    mutate("response_wrong_hash", "integrity", "INPUT_HASH_MISMATCH",
           lambda value, _: value.update(input_sha256="0" * 64))
    tampered_facts = deepcopy(case)
    tampered_facts["rows"][0]["fields"]["volume"] = "999"
    check("tampered_facts", "integrity", "INPUT_HASH_MISMATCH", a_case=tampered_facts)
    omitted_mapping = deepcopy(case)
    omitted_mapping["chart"]["row_ids"].pop()
    omitted_mapping["input_sha256"] = case_digest(omitted_mapping)
    check("missing_chart_mapping", "integrity", "INVALID_CHART_MAPPING", a_case=omitted_mapping,
          trusted_digest=omitted_mapping["input_sha256"])
    check("tampered_chart_bytes", "integrity", "CHART_HASH_MISMATCH", a_chart=chart + b"\n")
    signed_unmapped_chart = deepcopy(case)
    signed_unmapped_chart["chart"]["svg"]["sha256"] = sha256(chart + b"\n")
    signed_unmapped_chart["input_sha256"] = case_digest(signed_unmapped_chart)
    check("signed_wrong_chart", "integrity", "INVALID_CHART_MAPPING", a_case=signed_unmapped_chart,
          a_chart=chart + b"\n", trusted_digest=signed_unmapped_chart["input_sha256"])
    check("tampered_schema", "integrity", "SCHEMA_HASH_MISMATCH", schema=SCHEMA + b"\n")
    check("tampered_kb", "integrity", "KB_HASH_MISMATCH", kb=KB + b"\n")

    check("tampered_png_bytes", "integrity", "CHART_HASH_MISMATCH", a_png=png + b"\n")
    signed_wrong_png = deepcopy(case)
    signed_wrong_png["chart"]["png"]["sha256"] = sha256(png + b"\n")
    signed_wrong_png["input_sha256"] = case_digest(signed_wrong_png)
    check("signed_wrong_png", "integrity", "INVALID_CHART_MAPPING", a_case=signed_wrong_png,
          a_png=png + b"\n", trusted_digest=signed_wrong_png["input_sha256"])
    upper = deepcopy(case)
    upper["rows"][-1]["fields"]["OHLCV"] = upper["rows"][-1]["fields"]["ohlcv"]
    upper["input_sha256"] = case_digest(upper)
    check("signed_uppercase_alias", "integrity", "INVALID_WHITELIST", a_case=upper,
          trusted_digest=upper["input_sha256"])

    for label in ("UP_LEG", "DOWN_LEG", "RANGE", "MIXED", "UNRESOLVED"):
        phase = deepcopy(response)
        phase["claims"][0].update(type="PHASE", phase_label=label, kb_rule_ids=["KB_N_BREATHING"])
        validated = check(f"legal_phase_{label.lower()}", "legal", "ACCEPTED_CANDIDATE_ONLY", value=phase)
        results[-1]["pass"] &= validated.get("claims", [{}])[0].get("phase_label") == label
    mutate("invalid_phase_label", "v11_1_phase_label", "SCHEMA_INVALID",
           lambda _, claim: claim.update(type="PHASE", phase_label="BEAR", kb_rule_ids=["KB_N_BREATHING"]))
    mutate("missing_phase_label", "v11_1_phase_label", "SCHEMA_INVALID",
           lambda _, claim: claim.update(type="PHASE", phase_label=None, kb_rule_ids=["KB_N_BREATHING"]))
    mutate("non_phase_labeled", "v11_2_non_phase_label", "SCHEMA_INVALID",
           lambda _, claim: claim.update(phase_label="UP_LEG"))
    mutate("invalid_relation", "v11_3_relation", "SCHEMA_INVALID",
           lambda _, claim: claim.update(anchor_links=[link("BROKE", bar_ref(34, "high"))]))
    mutate("non_old_type_invalidates", "v11_3_relation", "SCHEMA_INVALID",
           lambda _, claim: claim.update(anchor_links=[link("INVALIDATES", bar_ref(34, "high"))]))
    mutate("invalidates_ordinary_price", "v11_4_bound_invalidation", "OLD_ANCHOR_PROOF_REQUIRED",
           lambda _, claim: claim.update(type="OLD_ANCHOR_INVALIDATION", kb_rule_ids=["KB_SUPPORT_BREAK"],
                                          anchor_links=[link("INVALIDATES", bar_ref(34, "high"))]))
    wrong = deepcopy(anchored_response)
    wrong["claims"][0]["evidence_refs"] = [close_ref]
    check("invalidates_without_observed_break", "v11_4_bound_invalidation", "OLD_ANCHOR_PROOF_REQUIRED",
          value=wrong, a_case=anchored_case, trusted_digest=anchored_case["input_sha256"])
    substitute_case = deepcopy(anchored_case)
    decoy_ref = ref("C01_DECOY_ANCHOR", "registered_support_object")
    substitute_case["rows"].append(
        row(decoy_ref["row_id"], "PRIMITIVE", (D - timedelta(days=1)).isoformat(),
            {decoy_ref["field"]: {"legacy_level": "11"}})
    )
    substitute_case["input_sha256"] = case_digest(substitute_case)
    substitute_response = deepcopy(anchored_response)
    substitute_response["input_sha256"] = substitute_case["input_sha256"]
    substitute_response["claims"][0]["anchor_links"] = [
        link("INVALIDATES", decoy_ref), link("REFERENCE", anchor_ref), link("REFERENCE", threshold_ref),
    ]
    check("invalidates_cannot_substitute_reference_anchor", "v11_4_bound_invalidation",
          "OLD_ANCHOR_PROOF_REQUIRED", value=substitute_response, a_case=substitute_case,
          trusted_digest=substitute_case["input_sha256"])
    wrong_identity = deepcopy(anchored_case)
    wrong_identity["rows"][-1]["fields"][break_ref["field"]]["anchor_id"] = "DIFFERENT_ANCHOR"
    wrong_identity["input_sha256"] = case_digest(wrong_identity)
    mismatch = {**anchored_response, "input_sha256": wrong_identity["input_sha256"]}
    check("invalidates_different_anchor", "v11_4_bound_invalidation", "OLD_ANCHOR_PROOF_REQUIRED",
          value=mismatch, a_case=wrong_identity, trusted_digest=wrong_identity["input_sha256"])
    mutate("ohlcv_as_price", "v11_5_aggregate_reference", "SCHEMA_INVALID",
           lambda _, claim: claim["price_refs"].update(low=ref("C01_AGGREGATE", "ohlcv")))
    mutate("ohlcv_as_span", "v11_5_aggregate_reference", "SCHEMA_INVALID",
           lambda _, claim: claim["span_refs"].update(start=ref("C01_AGGREGATE", "ohlcv")))

    timing = deepcopy(response)
    timing["claims"][0].update(
        span_refs={"start": bar_ref(34, "date"), "end": bar_ref(34, "date")},
        price_refs={"low": bar_ref(34, "low"), "high": bar_ref(34, "high")},
        anchor_links=[link("REFERENCE", bar_ref(33, "high"))],
        evidence_refs=[bar_ref(34, "close"), bar_ref(34, "volume")],
        counterevidence_refs=[ref("C01_B2_DAY", "day_eligibility"), ref("C01_AGGREGATE", "ohlcv")],
    )
    timed = check("legal_reference_and_latest_counterevidence", "legal", "ACCEPTED_CANDIDATE_ONLY",
                  value=timing)
    observed = timed.get("claims", [{}])[0]
    results[-1]["pass"] &= (observed.get("occurred_date") == (D - timedelta(days=1)).isoformat()
                            and observed.get("first_knowable_date") == D.isoformat())

    rejected = Counter(r["family"] for r in results if r["pass"] and not r["accepted"])
    inherited = sum(rejected[key] for key in ("forged_price", "reference_boundary", "promotion_or_override"))
    v11 = {key: value for key, value in rejected.items() if key.startswith("v11_")}
    passed = all(result["pass"] for result in results) and inherited == 21 and len(v11) == 5
    return {
        "status": "PASS" if passed else "FAIL", "guards": FROZEN_GUARDS,
        "models_called": 0, "market_source_opens": 0, "historical_forward_source_opens": 0,
        "controls": results, "count": len(results), "inherited_attacks_rejected": inherited,
        "v11_attacks_rejected_by_class": v11,
    }


if __name__ == "__main__":
    result = run_controls()
    print(json_bytes(result).decode("utf-8"))
    raise SystemExit(result["status"] != "PASS")
