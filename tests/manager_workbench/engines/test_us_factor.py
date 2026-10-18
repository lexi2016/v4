from copy import deepcopy
from hashlib import sha256
import json
from types import SimpleNamespace

from v4.manager_workbench.engines.us_factor import _industry_time_state, run_us_factor
from v4.manager_workbench.contracts import EvidenceRef, Verification
from v4.manager_workbench.inputs.native import _project_current_membership_for_industry
from v4.manager_workbench.inputs.validation import owner_digest
from v4.manager_workbench.inputs.source_bindings import hk_industry_classification


def context():
    return dict(target_date="20261013", phase="RETROSPECTIVE", cutoff="2026-10-13T14:00:00+08:00",
                source_sessions={"US": "20261012"})


def membership():
    return dict(verification="VERIFIED", eligible=True, owner="monthly-connect", sha256="a" * 64,
                available_at="2026-10-12T17:00:00+08:00", effective_from="20261001", effective_through="20261031")


def fact(symbol="HK.09660", theme="自动驾驶", proxy_symbols=None, decision="ACCEPT"):
    statement = "The company is engaged in autonomous driving technology."
    return dict(id="b" * 64, symbol=symbol, theme=theme, proxy_symbols=proxy_symbols or ["DRIV"],
        statement=statement, statement_sha256=sha256(statement.encode()).hexdigest(),
        source_raw_sha256="c" * 64, source_row_sha256="d" * 64, source_field="body",
        source_ref=dict(path="archive/article.json", receipt_path="archive/receipt.json", raw_article_field="body",
            receipt_raw_sha256="e" * 64, archive_metadata_raw_sha256="f" * 64),
        span=dict(start=0, end=len(statement)), subject_verification=dict(
            status="CURRENT_OWNER_NAME_AND_CONNECT_VERIFIED_ORIGINAL_SENTENCE_ANCHORED", target_date="20261013",
            in_current_692=True, identity_refs=["current-master-row"]),
        source_available_at="2026-10-10T12:00:00+08:00", publication_at="2026-10-10T12:00:00+08:00",
        collected_at="2026-10-10T12:00:00+08:00", archive_recorded_at="2026-10-10T12:01:00+08:00",
        fact_effective_from=None, fact_effective_through=None, fact_effective_status="UNKNOWN")


def payload(change_pct=10, review_decision="ACCEPT"):
    quote = dict(session_date="20261012", last=100 + change_pct, previous_close=100, change_pct=change_pct)
    owner_row = dict(label="自动驾驶", mapping_type="etf_proxy", proxy_symbols=["DRIV"],
        available_symbols=["DRIV"], requested_symbols=["DRIV"], coverage=dict(available=1, requested=1),
        status="READY", quote_session_dates=["20261012"], change_pct=change_pct)
    source_sha = "1" * 64
    record = dict(us_symbol="DRIV", owner="quote-owner", source_sha256=source_sha,
        available_at="2026-10-12T17:00:00+08:00", quote=quote,
        proxy_metadata=[dict(owner="quote-owner", source_sha256=source_sha,
            available_at="2026-10-12T17:00:00+08:00", owner_row=owner_row)])
    candidate_fact = fact()
    review_row = dict(id=candidate_fact["id"], decision=review_decision, reasons=[
        "ACCEPT_AS_OF_REPORTED_QUALITATIVE_EXPOSURE_ONLY", "LIMITS_REQUIRED"] if review_decision == "ACCEPT" else ["NO_MATCH"])
    candidate_sha = "2" * 64
    review = dict(schema="v4.manager_workbench.us_factor_exposure_review.v1", artifact_sha256=candidate_sha,
        review_owner="independent-reviewer", reviewed_at="2026-10-13T13:00:00+08:00", rows=[review_row])
    candidate = dict(schema_version="v4.manager_workbench.us_factor_exposure_candidate.v1", target_date="20261013",
        RESEARCH_ONLY=True, production_allowed=False, orders_sent=False, buy_gate_updated=False, rows=[candidate_fact])
    return dict(candidate=candidate, review=review, candidate_sha256=candidate_sha, review_sha256="3" * 64,
        target_memberships={candidate_fact["id"]: membership()}, hk_scope_count=692,
        evidence_ids=["quote", "membership", "candidate", "review"]), dict(records=[record])


def r2_midea_payload():
    """Freeze the actual R2 Midea row identity and its accepted reason tokens."""
    real_id = "9da47b2098f6d73d6ba44ff5d5cb7de102a24b971cefce6192b3fee8f228488c"
    candidate_sha = "2" * 64
    statement = "白电龙头美的集团、海尔智家、格力电器"
    r2_fact = fact(symbol="HK.00300", theme="消费", proxy_symbols=["XLY", "XLP"])
    r2_fact.update(
        id=real_id,
        statement=statement,
        statement_sha256=sha256(statement.encode()).hexdigest(),
        source_field="source_row.evidence_sentence",
        span={"start": 132, "end": 150},
        source_raw_sha256="3cd1b52bb1ec5888fe59452488cf06957d1376cfa59c189970d6496a33bafd63",
        source_row_sha256="03f870d6a56aafb11c4f2fab6e854d5a69e5d3edbac74d0c6739a802eb887c85",
        source_available_at="2026-10-13T14:17:18.497111+08:00",
        publication_at="2026-10-08T10:00:23+08:00",
        collected_at="2026-10-09T08:30:00+08:00",
        archive_recorded_at="2026-10-09T08:30:12+08:00",
        fact_effective_status="UNKNOWN",
    )
    r2_fact["subject_verification"].update(
        target_date="20261013", in_current_692=True,
        identity_refs=["current-security-master-row", "20261012-hk-connect-universe"],
    )
    candidate = dict(schema_version="v4.manager_workbench.us_factor_exposure_candidate.v1",
        target_date="20261013", RESEARCH_ONLY=True, production_allowed=False,
        orders_sent=False, buy_gate_updated=False, rows=[r2_fact])
    reasons = [
        "ACCEPT_AS_OF_REPORTED_QUALITATIVE_EXPOSURE: same frozen Eastmoney content binds HK00300/market116 and lists Shenzhen A share 000333.",
        "LIMITS: this is a reported qualitative classification; effective endpoints and income weights remain unknown.",
    ]
    review_row = dict(id=real_id, decision="ACCEPT", reasons=reasons)
    review = dict(schema="v4.manager_workbench.us_factor_exposure_review.v1",
        artifact_sha256=candidate_sha, review_owner="independent-reviewer",
        reviewed_at="2026-10-13T14:44:23.005624+00:00", rows=[review_row])
    data = dict(candidate=candidate, review=review, candidate_sha256=candidate_sha,
        review_sha256="3" * 64, target_memberships={real_id: membership()}, hk_scope_count=698,
        evidence_ids=["quote", "membership", "candidate", "review"])

    symbols = ["XLY", "XLP"]
    owner = dict(label="消费", mapping_type="etf_basket_proxy", proxy_symbols=symbols,
        available_symbols=symbols, requested_symbols=symbols, coverage=dict(available=2, requested=2),
        status="READY", quote_session_dates=["20261012"], change_pct=1.5)
    source_sha = "1" * 64
    records = []
    for symbol, change in zip(symbols, [1.0, 2.0]):
        records.append(dict(us_symbol=symbol, owner="quote-owner", source_sha256=source_sha,
            available_at="2026-10-12T17:00:00+08:00",
            quote=dict(session_date="20261012", last=100 + change, previous_close=100, change_pct=change),
            proxy_metadata=[dict(owner="quote-owner", source_sha256=source_sha,
                available_at="2026-10-12T17:00:00+08:00", owner_row=owner)]))
    return data, dict(records=records)


def test_positive_verified_proxy_becomes_conditional_watch_only():
    data, batch = payload(10)
    rows, summary = run_us_factor(context(), batch, data)
    assert len(rows) == 1
    assert rows[0]["decision"] == "CONDITIONAL_WATCH"
    assert rows[0]["factor_paths"][0]["return_pct"] == "10.0"
    assert rows[0]["historical_pit_verified"] is False
    assert rows[0]["factor_paths"][0]["fact_effective_status"] == "UNKNOWN"
    assert rows[0]["membership"]["eligible"] is True
    assert summary["eligible_hk_scope_count"] == 692
    assert not any(row["decision"] == "SELECTED" for row in rows)


def test_actual_r2_midea_positive_reason_tokens_remain_research_only():
    data, batch = r2_midea_payload()
    ctx = context()
    ctx["cutoff"] = "2026-10-13T23:59:59+08:00"
    rows, summary = run_us_factor(ctx, batch, data)
    assert len(rows) == 1 and rows[0]["symbol"] == "HK.00300"
    assert rows[0]["decision"] == "CONDITIONAL_WATCH"
    assert rows[0]["factor_paths"][0]["conditions"] == []
    assert rows[0]["factor_paths"][0]["return_pct"] == "1.50"
    assert summary["eligible_hk_scope_count"] == 698


def test_unapproved_similar_review_reason_tokens_stay_unassessed():
    data, batch = r2_midea_payload()
    data["review"]["rows"][0]["reasons"] = [
        "ACCEPT_AS_OF_REPORTED_QUALITATIVE_EXPOSURE_ONLY_EXTRA: not an approved exact label",
        "LIMITS_REQUIRED_EXTRA: not an approved exact label",
    ]
    ctx = context()
    ctx["cutoff"] = "2026-10-13T23:59:59+08:00"
    rows, _ = run_us_factor(ctx, batch, data)
    assert rows[0]["decision"] == "UNASSESSED"
    assert "AS_REPORTED_RETROSPECTIVE_SCOPE_NOT_EXPLICIT" in rows[0]["factor_paths"][0]["conditions"]


def test_zero_and_negative_returns_are_not_selected():
    for change in (0, -1):
        data, batch = payload(change)
        rows, _ = run_us_factor(context(), batch, data)
        assert rows[0]["decision"] == "NOT_SELECTED"


def test_rejected_or_membership_unverified_path_stays_unassessed():
    data, batch = payload(10, "REJECT")
    rows, _ = run_us_factor(context(), batch, data)
    assert rows[0]["decision"] == "UNASSESSED"
    assert "EXPOSURE_NOT_INDEPENDENTLY_ACCEPTED" in rows[0]["factor_paths"][0]["conditions"]

    data, batch = payload(10)
    data["target_memberships"]["b" * 64]["eligible"] = False
    rows, _ = run_us_factor(context(), batch, data)
    assert rows[0]["decision"] == "UNASSESSED"


def test_missing_basket_member_quote_keeps_proxy_unassessed():
    data, batch = payload(10)
    batch["records"][0]["proxy_metadata"][0]["owner_row"].update(
        mapping_type="etf_basket_proxy", proxy_symbols=["DRIV", "BOTZ"],
        available_symbols=["DRIV", "BOTZ"], requested_symbols=["DRIV", "BOTZ"],
        coverage=dict(available=2, requested=2), change_pct=10)
    data["candidate"]["rows"][0]["proxy_symbols"] = ["DRIV", "BOTZ"]
    rows, summary = run_us_factor(context(), batch, data)
    assert rows[0]["decision"] == "UNASSESSED"
    assert rows[0]["factor_paths"][0]["proxy_status"] == "UNASSESSED"
    assert summary["unknown_proxy_source_count"] == 24


def test_paired_review_id_mismatch_fails_closed():
    data, batch = payload(10)
    data["review"]["rows"][0]["id"] = "9" * 64
    rows, summary = run_us_factor(context(), batch, data)
    assert rows == []
    assert summary["paired_review_available"] is False
    assert summary["paired_review_gap"] == "US_FACTOR_PAIRED_ROW_COVERAGE_INVALID"


def _industry_codes(count=698):
    return ["HK.00300", *[f"HK.{90000 + i:05d}" for i in range(1, count)]]


def _industry_record(symbol, industry, *, response_sha="5" * 64, response_ref="fixture://row"):
    row_material = dict(symbol=symbol, issuer_name=f"Fixture {symbol}", source_industry=industry)
    row_sha = sha256(json.dumps(row_material, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode("utf-8")).hexdigest()
    return {**row_material, "source_row_sha256": row_sha,
        "source_response_sha256": response_sha, "source_response_ref": response_ref,
        "mapping_type": "EXACT_PROVIDER_INDUSTRY"}


def _industry_input(target_date, captured_at, codes, *, include_full_scope=True, source_asof=None):
    codes_sha = owner_digest(dict(market="HK_CONNECT", codes=sorted(codes)))
    member_sha = "a" * 64
    rows = [_industry_record("HK.00300", "家庭电器及用品")]
    if include_full_scope:
        rows.append(_industry_record(codes[1], "SYNTHETIC_UNMAPPED_CATEGORY"))
        rows.extend(_industry_record(code, None) for code in codes[2:])
    artifact = dict(schema_version="v4.manager_workbench.hk_industry_classification.v1",
        source_id="EASTMONEY_F10_RPT_HKF10_INFO_ORGPROFILE", source_owner="eastmoney-f10-canary",
        source_url="https://datacenter.eastmoney.com/securities/api/data/v1/get",
        target_date=target_date, market="HK_CONNECT", scope_type="HK_CONNECT_FULL_MARKET",
        scope_count=len(codes), membership_codes_sha256=codes_sha,
        membership_artifact_sha256=member_sha, source_asof=source_asof,
        source_asof_status="UNKNOWN" if source_asof is None else "KNOWN",
        captured_at=captured_at, batch_response_sha256="6" * 64, rows=rows)
    binding = dict(status="READY", owner="eastmoney-f10-canary", artifact=artifact,
        artifact_relative="fixture://hk-industry.json", artifact_sha256="7" * 64,
        evidence_ids=["industry-fixture"], hk_scope_codes=sorted(codes), hk_scope_count=len(codes),
        membership_codes_sha256=codes_sha, membership_artifact_sha256=member_sha,
        membership_owner="monthly-connect", membership_available_at="2026-10-13T08:00:00+08:00",
        membership_effective_from=target_date[:6] + "01", membership_effective_through=target_date[:6] + "31",
        membership_version="fixture-membership-v1")
    return binding, codes_sha


def _industry_identity(codes, source_date, *, master_codes=None):
    """Synthetic exact D-1 security-master identity pin for unit coverage only."""
    master_codes = sorted(master_codes if master_codes is not None else codes)
    return dict(status="READY", master_codes=master_codes, master_scope_count=len(master_codes),
        owner="v3_shared_data", source_date=source_date, available_at="2026-10-13T08:00:00+08:00",
        artifact_sha256="8" * 64, manifest_sha256="9" * 64,
        identity_codes_sha256=owner_digest(dict(market="HK_CONNECT", codes=master_codes)),
        evidence_ids=["synthetic-security-master"])


def _industry_payload(binding, codes, source_date, *, master_codes=None):
    return dict(hk_scope_count=len(codes), hk_scope_codes=sorted(codes),
        membership_codes_sha256=binding["membership_codes_sha256"],
        membership_artifact_sha256=binding["membership_artifact_sha256"],
        hk_industry_identity=_industry_identity(codes, source_date, master_codes=master_codes),
        hk_industry_classification=binding)


def _industry_proxy_batch(session):
    symbols = ["XLY", "XLP"]
    owner_row = dict(label="消费", mapping_type="etf_basket_proxy", proxy_symbols=symbols,
        available_symbols=symbols, requested_symbols=symbols, coverage=dict(available=2, requested=2),
        status="READY", quote_session_dates=[session], change_pct=1.5)
    records = []
    for symbol, change in zip(symbols, [1.0, 2.0]):
        records.append(dict(us_symbol=symbol, owner="quote-owner", source_sha256="1" * 64,
            available_at="2026-10-14T08:00:00+08:00",
            quote=dict(session_date=session, last=100 + change, previous_close=100, change_pct=change),
            proxy_metadata=[dict(owner="quote-owner", source_sha256="1" * 64,
                available_at="2026-10-14T08:00:00+08:00", owner_row=owner_row)]))
    return dict(records=records)


def test_hk_industry_single_same_day_canary_uses_positive_proxy_only_as_watch():
    codes = ["HK.00300"]
    binding, _ = _industry_input("20261014", "2026-10-14T09:30:00+08:00", codes, include_full_scope=False, source_asof="20261014")
    context_today = dict(target_date="20261014", phase="INTRADAY", cutoff="2026-10-14T13:00:00+08:00",
        source_sessions={"us": "20261013", "hk_price": "20261013"})
    payload_today = _industry_payload(binding, codes, "20261013")
    rows, summary = run_us_factor(context_today, _industry_proxy_batch("20261013"), payload_today)
    candidate = next(row for row in rows if row["subtype"] == "HK_INDUSTRY_PROXY_FACTOR_CANDIDATE")
    assert candidate["symbol"] == "HK.00300"
    assert candidate["theme"] == "消费" and candidate["return_pct"] == "1.50"
    assert candidate["decision"] == "CONDITIONAL_WATCH"
    assert candidate["temporal_status"] == "SOURCE_ASOF_TARGET_DATE"
    assert candidate["historical_pit_verified"] is False
    assert candidate["identity_status"] == "VERIFIED"
    assert summary["industry_summary"]["triggered_unique_stock_count"] == 1
    assert summary["industry_summary"]["identity_resolved_count"] == 1
    assert summary["industry_summary"]["identity_gap_count"] == 0
    assert not any(row["decision"] == "SELECTED" for row in rows)


def test_late_capture_valid_proxy_retrospective_creates_diagnostic_candidate_without_changing_decision():
    codes = ["HK.00300"]

    binding, _ = _industry_input(
        "20261013",
        "2026-10-14T09:30:00+08:00",
        codes,
        include_full_scope=False,
    )

    context_retro = dict(
        target_date="20261013",
        phase="RETROSPECTIVE",
        cutoff="2026-10-13T09:25:00+08:00",
        source_sessions={
            "us": "20261012",
            "hk_price": "20261012",
        },
    )

    proxy_batch = _industry_proxy_batch("20261012")

    for record in proxy_batch["records"]:
        record["available_at"] = "2026-10-13T08:00:00+08:00"
        for metadata in record["proxy_metadata"]:
            metadata["available_at"] = "2026-10-13T08:00:00+08:00"

    rows, _ = run_us_factor(
        context_retro,
        proxy_batch,
        _industry_payload(binding, codes, "20261012"),
    )

    candidate = next(
        row for row in rows
        if row["subtype"] == "HK_INDUSTRY_PROXY_FACTOR_CANDIDATE"
    )

    assert candidate["diagnostic_candidate"] is True
    assert candidate["diagnostic_status"] == (
        "CURRENT_CLASSIFICATION_DIAGNOSTIC"
    )
    assert candidate["diagnostic_pit_status"] == "PIT_UNCONFIRMED"

    assert candidate["historical_pit_verified"] is False
    assert candidate["decision"] == "UNASSESSED"


def test_late_capture_same_input_preopen_has_no_retrospective_diagnostic():
    codes = ["HK.00300"]

    binding, _ = _industry_input(
        "20261013",
        "2026-10-14T09:30:00+08:00",
        codes,
        include_full_scope=False,
    )

    context_preopen = dict(
        target_date="20261013",
        phase="PREOPEN",
        cutoff="2026-10-13T09:25:00+08:00",
        source_sessions={
            "us": "20261012",
            "hk_price": "20261012",
        },
    )

    proxy_batch = _industry_proxy_batch("20261012")

    for record in proxy_batch["records"]:
        record["available_at"] = "2026-10-13T08:00:00+08:00"
        for metadata in record["proxy_metadata"]:
            metadata["available_at"] = "2026-10-13T08:00:00+08:00"

    rows, _ = run_us_factor(
        context_preopen,
        proxy_batch,
        _industry_payload(binding, codes, "20261012"),
    )

    candidate = next(
        row for row in rows
        if row["subtype"] == "HK_INDUSTRY_PROXY_FACTOR_CANDIDATE"
    )

    assert candidate["diagnostic_candidate"] is False
    assert candidate["diagnostic_status"] is None
    assert candidate["diagnostic_pit_status"] == "PIT_UNCONFIRMED"

    assert candidate["historical_pit_verified"] is False
    assert candidate["decision"] == "UNASSESSED"


def test_late_capture_unmapped_has_no_diagnostic_candidate():
    codes = ["HK.00300"]

    binding, _ = _industry_input(
        "20261013",
        "2026-10-14T09:30:00+08:00",
        codes,
        include_full_scope=False,
    )

    binding["artifact"]["rows"][0]["source_industry"] = (
        "SYNTHETIC_UNMAPPED_CATEGORY"
    )

    context_retro = dict(
        target_date="20261013",
        phase="RETROSPECTIVE",
        cutoff="2026-10-13T09:25:00+08:00",
        source_sessions={
            "us": "20261012",
            "hk_price": "20261012",
        },
    )

    proxy_batch = _industry_proxy_batch("20261012")

    for record in proxy_batch["records"]:
        record["available_at"] = "2026-10-13T08:00:00+08:00"
        for metadata in record["proxy_metadata"]:
            metadata["available_at"] = "2026-10-13T08:00:00+08:00"

    rows, _ = run_us_factor(
        context_retro,
        proxy_batch,
        _industry_payload(binding, codes, "20261012"),
    )

    candidate = next(
        row for row in rows
        if row["subtype"] == "HK_INDUSTRY_PROXY_FACTOR_CANDIDATE"
    )

    assert candidate["diagnostic_candidate"] is False
    assert candidate["diagnostic_status"] is None
    assert candidate["decision"] == "UNASSESSED"

def test_hk_industry_full_698_fixture_keeps_missing_unmapped_and_retrospective_unknown_separate():
    # Synthetic fixture only: 698 rows exercise scope accounting; this is not a real full-date capture.
    codes = _industry_codes()
    binding, codes_sha = _industry_input("20261013", "2026-10-14T09:30:00+08:00", codes)
    context_retro = dict(target_date="20261013", phase="RETROSPECTIVE", cutoff="2026-10-14T13:00:00+08:00",
        source_sessions={"us": "20261012", "hk_price": "20261012"})
    rows, summary = run_us_factor(context_retro, _industry_proxy_batch("20261012"),
        _industry_payload(binding, codes, "20261012", master_codes=codes[:-1]))
    industry_rows = [row for row in rows if row["subtype"] == "HK_INDUSTRY_PROXY_FACTOR_CANDIDATE"]
    by_symbol = {row["symbol"]: row for row in industry_rows}
    funnel = summary["industry_summary"]
    assert len(industry_rows) == 698 and len(by_symbol) == 698
    assert funnel["scope_count"] == 698 and funnel["membership_codes_sha256"] == codes_sha
    assert funnel["classified_count"] == 2 and funnel["mapping_covered_count"] == 1
    assert funnel["industry_unmapped_count"] == 1 and funnel["classification_missing_count"] == 696
    assert funnel["unknown_unique_stock_count"] == 698
    assert funnel["decision_counts"]["UNASSESSED"] == 698
    assert funnel["identity_resolved_count"] == 697 and funnel["identity_gap_count"] == 1
    assert funnel["identity_gap_symbols"] == [codes[-1]]
    assert by_symbol[codes[-1]]["identity_status"] == "UNASSESSED_IDENTITY"
    assert by_symbol[codes[-1]]["reason"] == "UNASSESSED_IDENTITY"
    assert funnel["triggered_unique_stock_count"] == 0
    assert by_symbol["HK.00300"]["theme"] == "消费"
    assert by_symbol["HK.00300"]["return_pct"] == "1.50"
    assert by_symbol["HK.00300"]["decision"] == "UNASSESSED"
    assert "CLASSIFICATION_SOURCE_ASOF_UNKNOWN" in by_symbol["HK.00300"]["conditions"]
    assert by_symbol[codes[1]]["reason"] == "HK_INDUSTRY_PROXY_MAPPING_UNAVAILABLE"
    assert by_symbol[codes[2]]["reason"] == "HK_INDUSTRY_CLASSIFICATION_MISSING"
    assert funnel["temporal_status"] == "CLASSIFICATION_SOURCE_ASOF_UNKNOWN"


def test_hk_industry_out_of_scope_and_nonobject_rows_are_isolated_from_valid_member_canary():
    codes = ["HK.00300"]
    binding, _ = _industry_input("20261014", "2026-10-14T09:30:00+08:00", codes, include_full_scope=False, source_asof="20261014")
    binding["artifact"]["rows"].append(_industry_record("HK.09999", "SYNTHETIC_EXTRA_CATEGORY"))
    binding["artifact"]["rows"].append(None)
    context_today = dict(target_date="20261014", phase="INTRADAY", cutoff="2026-10-14T13:00:00+08:00",
        source_sessions={"us": "20261013", "hk_price": "20261013"})
    rows, summary = run_us_factor(context_today, _industry_proxy_batch("20261013"),
        _industry_payload(binding, codes, "20261013"))
    candidate = next(row for row in rows if row["subtype"] == "HK_INDUSTRY_PROXY_FACTOR_CANDIDATE")
    funnel = summary["industry_summary"]
    assert candidate["symbol"] == "HK.00300" and candidate["decision"] == "CONDITIONAL_WATCH"
    assert candidate["conditions"] == []
    assert funnel["out_of_scope_row_count"] == 1 and funnel["bad_row_count"] == 1
    assert funnel["unknown_unique_stock_count"] == 0
    assert funnel["source_status"] == "PARTIAL"


def test_hk_industry_reader_requires_exact_date_pinned_local_bytes(tmp_path):
    codes = ["HK.00300"]
    binding, _ = _industry_input("20261013", "2026-10-13T09:00:00+08:00", codes, include_full_scope=False)
    artifact = binding["artifact"]
    raw = (json.dumps(artifact, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    (tmp_path / "industry.json").write_bytes(raw)
    pin = dict(root=str(tmp_path), relative="industry.json", sha256=sha256(raw).hexdigest(), owner="eastmoney-f10")
    cfg = SimpleNamespace(shared_root=tmp_path, source_bindings={"hk_industry_classification": {"20261013": pin}})
    ctx = SimpleNamespace(target_date="20261013", scope_refs={})
    loaded = hk_industry_classification(cfg, ctx)
    assert loaded["status"] == "READY" and loaded["artifact_sha256"] == pin["sha256"]
    ctx.target_date = "20261014"
    unavailable = hk_industry_classification(cfg, ctx)
    assert unavailable["status"] == "UNAVAILABLE"
    assert unavailable["gap"] == "HK_INDUSTRY_CLASSIFICATION_EXACT_DATE_BINDING_MISSING"


def test_manual_daily_fact_without_effective_period_stays_unassessed():
    data, batch = payload(10)
    target = "20261020"
    fact_row = data["candidate"]["rows"][0]
    fact_row["subject_verification"]["target_date"] = target
    data["candidate"]["target_date"] = target
    data["review"]["reviewed_at"] = "2026-10-19T17:00:00+08:00"
    for record in batch["records"]:
        record["quote"]["session_date"] = "20261016"
        record["available_at"] = "2026-10-16T17:00:00+08:00"
        record["proxy_metadata"][0]["available_at"] = record["available_at"]
        record["proxy_metadata"][0]["owner_row"]["quote_session_dates"] = ["20261016"]
    member = data["target_memberships"][fact_row["id"]]
    member["effective_from"] = "20261001"
    member["effective_through"] = "20261031"
    member["available_at"] = "2026-10-16T17:00:00+08:00"
    context_value = dict(target_date=target, phase="MANUAL", cutoff="2026-10-20T10:00:00+08:00",
        source_sessions={"US": "20261016"})

    rows, _ = run_us_factor(context_value, batch, data)

    assert len(rows) == 1
    assert rows[0]["decision"] == "UNASSESSED"
    conditions = rows[0]["factor_paths"][0]["conditions"]
    assert "EXPOSURE_EFFECTIVE_PERIOD_UNVERIFIED" in conditions
    assert "US_FACTOR_RETROSPECTIVE_ONLY" not in conditions


def test_industry_capture_time_does_not_substitute_for_unknown_source_asof():
    eligible, status, _ = _industry_time_state(
        {"captured_at": "2026-10-20T09:00:00+08:00", "source_asof": None},
        {"target_date": "20261020", "cutoff": "2026-10-20T10:00:00+08:00"},
    )

    assert eligible is False
    assert status == "CLASSIFICATION_SOURCE_ASOF_UNKNOWN"


def test_latest_observed_unknown_source_asof_is_usable_without_claiming_pit():
    codes = ["HK.00300", "HK.00001", "HK.00002"]
    binding, _ = _industry_input(
        "20261020", "2026-10-14T11:03:29+08:00", codes,
        include_full_scope=True, source_asof=None,
    )
    artifact = binding["artifact"]
    artifact.update(classification_policy="LATEST_OBSERVED", observed_trade_date="20261014",
        observed_scope_count=len(codes), source_membership_codes_sha256="a" * 64,
        source_membership_artifact_sha256="b" * 64, status="PARTIAL",
        source_date_semantics="CAPTURED_ON_OR_BEFORE_TARGET_DATE_SOURCE_ASOF_UNKNOWN")
    context = dict(target_date="20261020", phase="MANUAL", cutoff="2026-10-20T10:00:00+08:00",
        source_sessions={"us": "20261016", "hk_price": "20261016"})

    rows, result = run_us_factor(context, _industry_proxy_batch("20261016"),
        _industry_payload(binding, codes, "20261016"))

    by_symbol = {row["symbol"]: row for row in rows if row["subtype"] == "HK_INDUSTRY_PROXY_FACTOR_CANDIDATE"}
    candidate = by_symbol["HK.00300"]
    funnel = result["industry_summary"]
    assert candidate["decision"] == "CONDITIONAL_WATCH"
    assert candidate["classification_policy"] == "LATEST_OBSERVED"
    assert candidate["observed_trade_date"] == "20261014"
    assert candidate["source_asof"] is None and candidate["source_asof_status"] == "UNKNOWN"
    assert candidate["temporal_status"] == "LATEST_OBSERVED_SOURCE_ASOF_UNKNOWN"
    assert candidate["historical_pit_verified"] is False
    assert "NOT_PIT_VERIFIED" in candidate["risks"]
    assert funnel["source_status"] == "PARTIAL"
    assert funnel["classification_policy"] == "LATEST_OBSERVED"
    assert funnel["source_asof"] is None and funnel["historical_pit_verified"] is False
    assert by_symbol["HK.00001"]["decision"] == "UNASSESSED"
    assert by_symbol["HK.00001"]["reason"] == "HK_INDUSTRY_PROXY_MAPPING_UNAVAILABLE"
    assert by_symbol["HK.00002"]["decision"] == "UNASSESSED"
    assert by_symbol["HK.00002"]["reason"] == "HK_INDUSTRY_CLASSIFICATION_MISSING"
    assert funnel["classification_missing_count"] == 1
    assert funnel["industry_unmapped_count"] == 1


def test_latest_observed_policy_rejects_future_observation_and_late_capture():
    cutoff = "2026-10-20T10:00:00+08:00"
    context = {"target_date": "20261020", "cutoff": cutoff}
    base = {"captured_at": "2026-10-14T11:03:29+08:00", "source_asof": None,
        "source_asof_status": "UNKNOWN", "classification_policy": "LATEST_OBSERVED",
        "observed_trade_date": "20261014"}

    eligible, status, _ = _industry_time_state(base, context)
    future, future_status, _ = _industry_time_state({**base, "observed_trade_date": "20261021"}, context)
    late, late_status, _ = _industry_time_state({**base, "captured_at": "2026-10-20T10:00:01+08:00"}, context)

    assert eligible is True and status == "LATEST_OBSERVED_SOURCE_ASOF_UNKNOWN"
    assert future is False and future_status == "CLASSIFICATION_OBSERVATION_AFTER_TARGET"
    assert late is False and late_status == "CLASSIFICATION_CAPTURE_AFTER_CUTOFF"


def test_latest_observed_verified_nonpositive_proxy_is_not_selected():
    codes = ["HK.00300"]
    binding, _ = _industry_input(
        "20261020", "2026-10-14T11:03:29+08:00", codes,
        include_full_scope=False, source_asof=None,
    )
    binding["artifact"].update(classification_policy="LATEST_OBSERVED", observed_trade_date="20261014",
        observed_scope_count=1, source_membership_codes_sha256="a" * 64,
        source_membership_artifact_sha256="b" * 64, status="PARTIAL")
    batch = _industry_proxy_batch("20261016")
    for record in batch["records"]:
        record["quote"].update(last=99, change_pct=-1)
        record["proxy_metadata"][0]["owner_row"]["change_pct"] = -1
    context = dict(target_date="20261020", phase="MANUAL", cutoff="2026-10-20T10:00:00+08:00",
        source_sessions={"us": "20261016", "hk_price": "20261016"})

    rows, _ = run_us_factor(context, batch, _industry_payload(binding, codes, "20261016"))

    candidate = next(row for row in rows if row["subtype"] == "HK_INDUSTRY_PROXY_FACTOR_CANDIDATE")
    assert candidate["decision"] == "NOT_SELECTED"
    assert candidate["reason"] == "HK_INDUSTRY_US_PROXY_RETURN_NOT_POSITIVE"
    assert candidate["temporal_status"] == "LATEST_OBSERVED_SOURCE_ASOF_UNKNOWN"
    assert candidate["historical_pit_verified"] is False


def test_latest_observed_missing_proxy_remains_unassessed():
    codes = ["HK.00300"]
    binding, _ = _industry_input(
        "20261020", "2026-10-14T11:03:29+08:00", codes,
        include_full_scope=False, source_asof=None,
    )
    binding["artifact"].update(classification_policy="LATEST_OBSERVED", observed_trade_date="20261014",
        observed_scope_count=1, source_membership_codes_sha256="a" * 64,
        source_membership_artifact_sha256="b" * 64, status="PARTIAL")
    context = dict(target_date="20261020", phase="MANUAL", cutoff="2026-10-20T10:00:00+08:00",
        source_sessions={"us": "20261016", "hk_price": "20261016"})

    rows, _ = run_us_factor(context, {"records": []}, _industry_payload(binding, codes, "20261016"))

    candidate = next(row for row in rows if row["subtype"] == "HK_INDUSTRY_PROXY_FACTOR_CANDIDATE")
    assert candidate["decision"] == "UNASSESSED"
    assert candidate["proxy_status"] == "UNASSESSED"
    assert candidate["temporal_status"] == "LATEST_OBSERVED_SOURCE_ASOF_UNKNOWN"
    assert candidate["historical_pit_verified"] is False


def test_observed_owner_projection_binds_only_verified_current_membership_and_preserves_source_hashes():
    owner_artifact = {
        "classification_policy": "LATEST_OBSERVED",
        "source_membership_codes_sha256": "a" * 64,
        "source_membership_artifact_sha256": "b" * 64,
    }
    current_member = EvidenceRef(
        evidence_id="current-membership-fixture",
        owner="synthetic-current-membership-test-only",
        role="MONTHLY_CONNECT_MEMBERSHIP",
        source_date="20261016",
        available_at="2026-10-16T16:00:00+08:00",
        sha256="f" * 64,
        verification=Verification.VERIFIED,
    )

    projected = _project_current_membership_for_industry(owner_artifact, current_member)

    assert projected is not owner_artifact
    assert projected["membership_artifact_sha256"] == current_member.sha256
    assert projected["source_membership_codes_sha256"] == "a" * 64
    assert projected["source_membership_artifact_sha256"] == "b" * 64
    assert "membership_artifact_sha256" not in owner_artifact


def test_observed_owner_projection_keeps_missing_or_unverified_current_membership_unknown():
    owner_artifact = {
        "classification_policy": "LATEST_OBSERVED",
        "source_membership_artifact_sha256": "b" * 64,
    }
    unverified_member = EvidenceRef(
        evidence_id="unverified-current-membership-fixture",
        owner="synthetic-current-membership-test-only",
        role="MONTHLY_CONNECT_MEMBERSHIP",
        source_date="20261016",
        available_at="2026-10-16T16:00:00+08:00",
        sha256="f" * 64,
        verification=Verification.CANNOT_CONFIRM,
    )

    assert _project_current_membership_for_industry(owner_artifact, None)[
        "membership_artifact_sha256"
    ] is None
    assert _project_current_membership_for_industry(owner_artifact, unverified_member)[
        "membership_artifact_sha256"
    ] is None
    assert owner_artifact["source_membership_artifact_sha256"] == "b" * 64


def test_latest_observed_owner_pin_checks_artifact_receipt_manifest_and_capture(tmp_path):
    from v4.manager_workbench.inputs.source_bindings import hk_industry_classification

    artifact_relative = "research/peripherals/20261014/hk_industry_classification.json"
    receipt_relative = "receipts/research/peripherals/20261014/hk_industry_classification.json"
    manifest_relative = "research/peripherals/manifest.json"
    payload = dict(schema_version="v3_5.research_peripheral.v1", source="hk_industry_classification",
        source_id="EASTMONEY_F10_RPT_HKF10_INFO_ORGPROFILE", trade_date="20261014",
        captured_at="2026-10-14T11:03:29+08:00", source_asof=None, source_asof_status="UNKNOWN",
        source_date_semantics="CAPTURED_ON_OR_BEFORE_TARGET_DATE_SOURCE_ASOF_UNKNOWN",
        status="PARTIAL", scope_count=1, items=[{"symbol": "HK.00300"}], failures=["MISSING_ROW"],
        batch_response_sha256="c" * 64)
    receipt = dict(schema_version="v3_5.research_peripheral_receipt.v1", trade_date="20261014",
        source="hk_industry_classification", payload_path=artifact_relative, captured_at=payload["captured_at"],
        payload_sha256=None, item_count=1, failure_count=1,
        batch_response_sha256=payload["batch_response_sha256"])
    artifact_bytes = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
    artifact_sha = sha256(artifact_bytes).hexdigest()
    receipt["payload_sha256"] = artifact_sha
    receipt_bytes = (json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n").encode()
    receipt_sha = sha256(receipt_bytes).hexdigest()
    manifest = {artifact_relative: artifact_sha}
    manifest_bytes = (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode()
    manifest_sha = sha256(manifest_bytes).hexdigest()
    for relative, raw in ((artifact_relative, artifact_bytes), (receipt_relative, receipt_bytes),
        (manifest_relative, manifest_bytes)):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    pin = dict(policy="LATEST_OBSERVED", target_date="20261020", observed_trade_date="20261014",
        source_asof=None, source_asof_status="UNKNOWN", captured_at=payload["captured_at"],
        source_date_semantics=payload["source_date_semantics"],
        expected_status="PARTIAL", expected_scope_count=1, expected_item_count=1, expected_failure_count=1,
        source_local_path=str(tmp_path), artifact_relative=artifact_relative, artifact_sha256=artifact_sha,
        receipt_relative=receipt_relative, receipt_sha256=receipt_sha,
        manifest_relative=manifest_relative, manifest_sha256=manifest_sha,
        owner="research_peripheral.hk_industry_classification")
    cfg = SimpleNamespace(shared_root=tmp_path, source_bindings={"hk_industry_classification": {"20261020": pin}})
    ctx = SimpleNamespace(target_date="20261020", cutoff="2026-10-20T10:00:00+08:00", scope_refs={})

    loaded = hk_industry_classification(cfg, ctx)

    assert loaded["status"] == "READY"
    assert loaded["policy"] == "LATEST_OBSERVED"
    assert loaded["observed_trade_date"] == "20261014"
    assert loaded["artifact"]["target_date"] == "20261020"
    assert loaded["artifact"]["source_asof"] is None
    assert loaded["artifact"]["source_asof_status"] == "UNKNOWN"
    assert {row["relative"] for row in loaded["checked_files"]} == {
        artifact_relative, receipt_relative, manifest_relative}
    pin["captured_at"] = "2026-10-20T10:00:01+08:00"
    assert hk_industry_classification(cfg, ctx)["status"] == "UNAVAILABLE"

