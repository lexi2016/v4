from copy import deepcopy
from hashlib import sha256

from v4.manager_workbench.engines.us_factor import run_us_factor


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
