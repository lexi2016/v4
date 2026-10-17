## Source excerpt: `tests/manager_workbench/engines/test_us_mapping.py`

Original source path: `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/announcement-continuation-api-20261017-r11c/app/tests/manager_workbench/engines/test_us_mapping.py`

Original full-file SHA-256: `0f43577011e141a1f3b804e08d0454396d4a73984a0fb2d344348314b79272d7`

Release/worktree group: `api`

Existing 48-symbol scope and proposal observation-only regression tests; no 1,003 relation consumer test.

### Full-source lines 84-135

```python

def test_v3_48_symbol_scope_and_proposed_relations_remain_observation_only():
    contract = build_us_universe_contract()
    c = ctx()
    universe_ref = "us:" + contract["version"] + ":" + c["target_date"]
    c["scope_refs"]["US_MAPPING"] = dict(
        universe_ref=universe_ref,
        configured_symbols=contract["symbols"],
        universe_version=contract["version"],
        universe_contract=contract,
        universe_contract_sha256=contract["contract_sha256"],
        source_session="20261012",
        verification="VERIFIED",
        calendar_verified=True,
        sha256="c" * 64,
    )
    records = [
        dict(
            us_symbol=symbol,
            source_session="20261012",
            source_status="CANNOT_CONFIRM",
            owner="US-owner",
            source_sha256="a" * 64,
            available_at="2026-10-13T09:00:00+08:00",
            positive_change_required=True,
            quote={"change_pct": 1.0},
            relations=[dict(
                status="PROPOSED",
                pit_status="PIT_UNCONFIRMED",
                target_symbol="HK.00700",
                target_name="Tencent Holdings",
                relation_type="BUSINESS_SEGMENT_PEER",
                relation_source_refs=[{"url": "https://example.invalid/filing"}],
            )],
        )
        for symbol in contract["symbols"]
    ]
    data = dict(context=c, records=records, lane="US_MAPPING", evidence_refs=[],
        universe_ref=universe_ref, input_sha256="d" * 64,
        scope_description="48 configured US observations",
        coverage=dict(scope_count=48, observed_count=48), gaps=[])
    result = run_us_mapping(ctx(), data)
    assert result["coverage"]["scope_count"] == 48
    assert len(result["rows"]) == 48
    assert {row["decision"] for row in result["rows"]} == {"UNASSESSED"}
    assert {row["reason"] for row in result["rows"]} == {"US_RELATION_PROPOSED_PIT_UNCONFIRMED"}
    assert not any(row["decision"] == "SELECTED" for row in result["rows"])

    data["records"].pop()
    incomplete = run_us_mapping(ctx(), data)
    assert "US_SOURCE_UNIVERSE_COVERAGE_INCOMPLETE" in incomplete["gaps"]



```
