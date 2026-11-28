"""Run the ACT-070A exact-oracle controls with synthetic fixtures and zero models."""

from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta

from research.act070a.case_contract import (
    B_SCHEMA, CHART_NAME, FROZEN_GUARDS, INPUT_SCHEMA, KB_RULES, SOURCE_HASHES,
    case_digest, json_bytes, sha256, strict_json,
)
from research.act070a.chart import CHART_SESSIONS, render_chart
from research.act070a.generate_cases import parse_plan
from research.act070a.validate_b_output import validate_output

CASE = "C01"
D = date(2020, 2, 4)
SCHEMA = B_SCHEMA.read_bytes()
KB = KB_RULES.read_bytes()


def ref(row_id, field):
    return {"row_id": row_id, "field": field}


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
        bars.append(row(bar_ref(position, "date")["row_id"], "CHART_BAR", stamp, fields))
    immutable_b2 = {
        "day_eligibility": "FALSE", "day_eligibility_reason": "B2_D0_NON_BULLISH_NECESSARY_CONDITION",
        "event_chain_state_b2": "UNKNOWN", "formal_b2_event_presence": "ABSENT",
    }
    extra_rows = [
        row("C01_PRIM_P1_01", "PRIMITIVE", D.isoformat(), {"registered_key_k": "UNKNOWN"}, "MISSING_SOURCE"),
        row("C01_B2_DAY", "A_DAY_STATUS", D.isoformat(), immutable_b2),
    ]
    chart = render_chart(bars)
    case = {
        "schema_version": INPUT_SCHEMA, "case_id": CASE, "d": D.isoformat(), "guards": FROZEN_GUARDS,
        "chart": {"path": CHART_NAME, "row_ids": [bar["row_id"] for bar in bars], "sha256": sha256(chart)},
        "schema_sha256": sha256(SCHEMA), "kb_sha256": sha256(KB),
        "kb_rule_ids": [card["id"] for card in strict_json(KB)["cards"]],
        "source_sha256": SOURCE_HASHES, "rows": bars + extra_rows, "immutable_b2": immutable_b2,
    }
    case["input_sha256"] = case_digest(case)
    claim = {
        "id": "C1", "type": "KEY_K", "status": "CANDIDATE",
        "span_refs": {"start": bar_ref(35, "date"), "end": bar_ref(35, "date")},
        "price_refs": {"low": bar_ref(35, "low"), "high": bar_ref(35, "high")},
        "anchor_links": [], "evidence_refs": [bar_ref(35, "close"), bar_ref(35, "volume")],
        "counterevidence_refs": [ref("C01_B2_DAY", "day_eligibility")],
        "kb_rule_ids": ["KB_KEY_K"], "gap_codes": [],
    }
    response = {
        "schema_version": "ACT070A_B_OUTPUT_V1", "case_id": CASE,
        "input_sha256": case["input_sha256"], "claims": [claim], "abstain_codes": [],
    }
    return case, chart, response


def test_result(name, family, expected, verdict):
    result = {"name": name, "family": family, "expected_code": expected, "actual_code": verdict["code"],
              "accepted": verdict["accepted"]}
    result["pass"] = verdict["code"] == expected and verdict["accepted"] == expected.startswith("ACCEPTED_")
    return result


def run_controls():
    case, chart, response = fixture()
    results = []

    def check(name, family, expected, *, value=None, raw=None, a_case=None, a_chart=None,
              schema=SCHEMA, kb=KB, trusted_digest=None):
        verdict = validate_output(
            raw if raw is not None else json_bytes(value if value is not None else response),
            a_case if a_case is not None else case, a_chart if a_chart is not None else chart,
            schema, kb, CASE, trusted_digest if trusted_digest is not None else case["input_sha256"],
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

    mutate("forged_price_ref", "forged_price", "UNKNOWN_REFERENCE",
           lambda _, claim: claim["price_refs"].update(low=bar_ref(35, "forged_price")))
    mutate("bare_price", "forged_price", "SCHEMA_INVALID",
           lambda _, claim: claim["price_refs"].update(low=9.01))
    mutate("price_embedded_in_ref", "forged_price", "SCHEMA_INVALID",
           lambda _, claim: claim["price_refs"]["low"].update(value=9.01))
    mutate("volume_as_price", "forged_price", "REFERENCE_ROLE_MISMATCH",
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
    embedded_future["rows"][-2]["fields"]["registered_key_k"] = {"date": future}
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
        anchor_links=[anchor_ref, threshold_ref], evidence_refs=[break_ref, close_ref],
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
    signed_unmapped_chart["chart"]["sha256"] = sha256(chart + b"\n")
    signed_unmapped_chart["input_sha256"] = case_digest(signed_unmapped_chart)
    check("signed_wrong_chart", "integrity", "INVALID_CHART_MAPPING", a_case=signed_unmapped_chart,
          a_chart=chart + b"\n", trusted_digest=signed_unmapped_chart["input_sha256"])
    check("tampered_schema", "integrity", "SCHEMA_HASH_MISMATCH", schema=SCHEMA + b"\n")
    check("tampered_kb", "integrity", "KB_HASH_MISMATCH", kb=KB + b"\n")

    valid_plan = {"calibration": [{"case_id": f"C{i:02d}", "d": f"2020-01-{i:02d}"} for i in range(1, 5)],
                  "first_test": []}
    results.append({"name": "known_calibration_plan", "family": "generator",
                    "pass": parse_plan(valid_plan) == valid_plan["calibration"]})
    try:
        parse_plan({**valid_plan, "first_test": [{"case_id": "T01", "d": D.isoformat()}]})
        actual = "ACCEPTED"
    except ValueError as exc:
        actual = exc.code
    results.append({"name": "uncertified_first_test_plan", "family": "generator",
                    "expected_code": "FIRST_TEST_NOT_CERTIFIED", "actual_code": actual,
                    "pass": actual == "FIRST_TEST_NOT_CERTIFIED"})
    return {"status": "PASS" if all(result["pass"] for result in results) else "FAIL",
            "guards": FROZEN_GUARDS, "models_called": 0, "market_source_opens": 0,
            "controls": results, "count": len(results)}


if __name__ == "__main__":
    result = run_controls()
    print(json_bytes(result).decode("utf-8"))
    raise SystemExit(result["status"] != "PASS")
