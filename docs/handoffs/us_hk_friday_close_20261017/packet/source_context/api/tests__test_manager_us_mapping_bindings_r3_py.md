## Source excerpt: `tests/test_manager_us_mapping_bindings_r3.py`

Original source path: `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/announcement-continuation-api-20261017-r11c/app/tests/test_manager_us_mapping_bindings_r3.py`

Original full-file SHA-256: `199c22c890b75ec9d65429965f2bea656492ac7ba98eeffd4362044c1d145b1d`

Release/worktree group: `api`

Existing tests for configured quote scope, proposal visibility, target-date artifact precedence, receipt binding, and partial status.

### Full-source lines 28-145

```python

def test_source_binding_carries_configured_quote_scope_and_proposal_sources(tmp_path, monkeypatch):
    install_root = tmp_path / "com.lexi.v4.local"
    app_root = install_root / "releases" / "isolated-test" / "app"
    app_root.mkdir(parents=True)
    config_value = {"source_bindings": {"_extra": {"us_universe_extra_symbols": ["TSLA"]}}}
    config_path = install_root / "config" / "manager-workbench-v7.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(json.dumps(config_value), encoding="utf-8")
    monkeypatch.delenv("V4_MANAGER_WORKBENCH_CONFIG_PATH", raising=False)
    monkeypatch.setenv("V35_APP_ROOT", str(app_root))
    contract = build_us_universe_contract(["TSLA"])
    requested_urls = []
    quote_snapshot = build_us_market_snapshot(
        "20261012",
        capture_phase="POST_CLOSE",
        captured_at="2026-10-12T16:18:00-04:00",
        fetch_quotes=lambda url, _timeout: (requested_urls.append(url) or {
            symbol: dict(last=101.0, previous_close=100.0, session_date="20261012", session_time="16:00:00")
            for symbol in contract["symbols"] if symbol not in {"META", "PDD"}
        }),
    )
    assert len(requested_urls) == 1
    assert "usTSLA" in requested_urls[0]
    assert quote_snapshot["requested_symbol_count"] == 49
    assert len(quote_snapshot["quotes"]) == 47
    assert len(quote_snapshot["rows"]) == 24
    quote_root = tmp_path / "quotes"
    payload = build_external_finance_payload(
        "20261012",
        fetched_at="2026-10-13T07:00:00Z",
        subscriptions=(),
    )
    payload["market_snapshot"] = quote_snapshot
    payload["market_snapshot_status"] = quote_snapshot["status"]
    if quote_snapshot["status"] != "READY":
        payload["status"] = "CANNOT_CONFIRM"
    payload["us_session_captures"] = [dict(
        us_session_date="20261012",
        capture_phase="POST_CLOSE",
        session_timezone="America/New_York",
        capture_window_start="2026-10-12T16:15:00-04:00",
        capture_window_end="2026-10-12T16:20:00-04:00",
        capture_id="isolated-test-capture-20261012-post-close",
        run_id="isolated-test-run",
        captured_at="2026-10-12T16:18:00-04:00",
        capture_origin="ORIGINAL_TIME_CAPTURE",
        original_time_capture=True,
    )]
    store = ResearchPeripheralStore(quote_root)
    published = store.publish(payload)
    assert store.read_exact("20261012", "external_finance")["market_snapshot"] == quote_snapshot
    quote_relative = published["payload_path"]

    relation_root = tmp_path / "relations"
    evidence_relative = "legacy/evidence.json"
    review_relative = "legacy/review.json"
    evidence = {"schema_version": "frozen", "relations": [], "symbol_assessments": []}
    evidence["artifact_sha256"] = source_bindings.owner_digest(evidence)
    evidence_sha = _write(relation_root, evidence_relative, evidence)
    review = {
        "status": "PASS",
        "evidence_file_sha256": evidence_sha,
        "declared_artifact_sha256": evidence["artifact_sha256"],
        "recomputed_artifact_sha256": evidence["artifact_sha256"],
        "reviewer_identity": "isolated-test-reviewer",
        "reviewed_at": "2026-10-13T07:00:00Z",
        "reviewed_pairs": [],
        "reviewed_symbol_assessments": [],
        "safety": {"production_allowed": False},
    }
    _write(relation_root, review_relative, review)
    config = SimpleNamespace(
        us_root=quote_root,
        relation_root=relation_root,
        relation_evidence_relative=evidence_relative,
        relation_review_relative=review_relative,
        source_bindings={},
    )
    context = SimpleNamespace(
        source_sessions={"us": "20261012"},
        cutoff="2026-10-14T09:00:00+08:00",
        target_date="20261014",
    )
    monkeypatch.setattr(source_bindings, "priority_review", lambda *_: [])
    monkeypatch.setattr(source_bindings, "reviewed_seed", lambda *_: ([], []))
    monkeypatch.setattr(source_bindings, "us_factor_exposure", lambda *_: (None, [], None))
    monkeypatch.setattr(source_bindings, "hk_industry_classification", lambda *_: {"checked_files": []})

    pin = source_bindings.us_mapping(config, context)

    proposals = [card for card in pin["relation_projection"]["cards"] if card.get("status") == "PROPOSED"]
    assert pin["universe_version"] == "US_MAPPING_UNIVERSE_CONTRACT_V3"
    assert len(pin["configured_symbols"]) == 49
    assert pin["configured_symbols"][-1] == "TSLA"
    assert len(proposals) == 22
    registry_path = Path(source_bindings.__file__).resolve().parents[1] / "data" / "us_mapping_business_relations_20261014_v3.json"
    registry = json.loads(registry_path.read_text())
    assert registry["source_asof"] is None
    assert registry["pit_status"] == "PIT_UNCONFIRMED"
    assert registry["strict_selection_eligible"] is False
    assert all(source.get("supports") for relation in registry["relations"] for source in relation["sources"])
    assert not any("edgar/data/1526520/" in source["url"] for relation in registry["relations"] for source in relation["sources"])
    tcom_peer = next(relation for relation in registry["relations"]
        if relation.get("us_symbol") == "TCOM" and relation.get("hk_symbol") == "HK.00780")
    assert "annual reports" in tcom_peer["reason"]
    assert "20-F" not in tcom_peer["reason"]
    assert any(source["url"] == "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0428/2026042803041.pdf"
        for source in tcom_peer["sources"])
    assert all(card["pit_status"] == "PIT_UNCONFIRMED" for card in proposals)
    assert all(card["strict_selection_supported"] is False for card in proposals)
    assert all(card["relation_source_refs"] and card["relation_source_refs"][0]["url"].startswith("https://")
        for card in proposals)
    assert pin["relation_projection"]["strict_selection_eligible"] is False
    assert pin["source_gaps_by_symbol"]["META"] == ["QUOTE_SYMBOL_MISSING:META"]
    assert pin["source_gaps_by_symbol"]["PDD"] == ["QUOTE_SYMBOL_MISSING:PDD"]

    by_symbol = {}
    for card in proposals:

```

### Full-source lines 265-305

```python

def test_target_date_48_quote_artifact_precedes_legacy_us_session(tmp_path, monkeypatch):
    from ops.us_market_digest import build_us_market_phase_payload

    contract = build_us_universe_contract()
    mixed_time_symbols = {"BABA", "CIEN", "COHR", "DLR", "UBER", "VRT"}
    quote_rows = {
        symbol: dict(
            last=101.0,
            previous_close=100.0,
            session_date="20261013",
            session_time="16:08:30" if symbol in mixed_time_symbols else "16:00:01",
        )
        for symbol in contract["symbols"]
    }
    captured_at = "2026-10-14T07:52:00-04:00"
    target_payload = build_us_market_phase_payload(
        "20261014",
        capture_phase="POST_CLOSE",
        us_session_date="20261013",
        fetched_at=captured_at,
        capture_id="R6-TARGET-20261014-POST-CLOSE",
        run_id="R6-TARGET-20261014-POST-CLOSE",
        fetch_rss=lambda *_args, **_kwargs: b"<rss><channel></channel></rss>",
        fetch_quotes=lambda *_args, **_kwargs: quote_rows,
        allow_late_post_close=True,
        now=captured_at,
    )
    target_snapshot = target_payload["market_snapshot"]
    assert target_payload["trade_date"] == "20261014"
    assert target_snapshot["capture_session_date"] == "20261013"
    assert target_snapshot["requested_symbol_count"] == 48
    assert target_snapshot["available_symbol_count"] == 48
    assert target_snapshot["status"] == "CANNOT_CONFIRM"
    assert "QUOTE_SESSION_TIME_MIXED" in target_snapshot["cannot_confirm"]
    assert {row["symbol"] for row in target_snapshot["quotes"]
        if row["session_time"] == "16:08:30"} == mixed_time_symbols

    data_root = tmp_path / "owner-data"
    store = ResearchPeripheralStore(data_root)
    legacy_quote_rows = {
        symbol: dict(quote_rows[symbol], session_time="16:00:01")

```

### Full-source lines 386-410

```python

    target_relative = "research/peripherals/20261014/external_finance.json"
    target_receipt_relative = "receipts/research/peripherals/20261014/external_finance.json"
    assert legacy_store_result["payload_path"] == "research/peripherals/20261013/external_finance.json"
    assert target_store_result["payload_path"] == target_relative
    assert pin["quote_relative"] == target_relative
    assert pin["quote_artifact_date"] == "20261014"
    assert pin["quote_source_session"] == "20261013"
    assert len(pin["configured_symbols"]) == 48
    assert pin["universe_version"] == "US_MAPPING_UNIVERSE_CONTRACT_V3"
    receipt_check = next(row for row in pin["checked_files"]
        if row.get("relative") == target_receipt_relative)
    assert receipt_check["sha256"] == hashlib.sha256(
        (data_root / target_receipt_relative).read_bytes()
    ).hexdigest()
    assert target_receipt_relative.endswith("/20261014/external_finance.json")

    native_batch = adapter.us_mapping(prepared)
    assert native_batch.coverage.scope_count == 48
    assert len(native_batch.records) == 48
    assert all(record["source_status"] == "CANNOT_CONFIRM" for record in native_batch.records)
    quote_ref = next(ref for ref in native_batch.evidence_refs
        if ref.role == "US_UNIVERSE_CONTRACT_QUOTES")
    assert quote_ref.artifact_ref == target_relative
    assert quote_ref.source_session == "20261013"
    assert prepared.scope_refs["US_MAPPING"]["universe_version"] == "US_MAPPING_UNIVERSE_CONTRACT_V3"

```
