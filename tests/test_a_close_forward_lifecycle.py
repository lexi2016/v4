"""Forward-only lifecycle correction using the captured issuer notice."""
from copy import deepcopy
import hashlib
from pathlib import Path

import pytest

from ops import a_share_daily_sync as sync
from ops import research_panel_factor_cache as cache


def facts():
    return sync._load_verified_lifecycle_facts()


def source_row(tmp_path, code, fact):
    path = tmp_path / (code[-2:].lower() + code[:6] + ".day")
    path.write_bytes(b"unchanged existing historical bars")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return dict(symbol=code[:6], market=0, path=str(path),
                classification="QUARANTINED", quarantine=True,
                target_date_ready=False, lifecycle_skip=True,
                reason_code=cache._LIFECYCLE_REASON, records_written=0,
                source_sha256_before=digest, source_sha256_after=digest,
                lifecycle_fact=fact, lifecycle_policy_ref=fact["source_policy_ref"],
                lifecycle_asset_sha256=fact["source_policy_ref"]["sha256"])


def test_new_delisting_is_applied_only_from_november_20(tmp_path):
    bound = facts()
    original = deepcopy(bound["002731.SZ"])
    assert sync._lifecycle_fact_for_target(bound, "002731", 0, 20261119) is None
    assert sync._lifecycle_fact_for_target(bound, "002731", 0, 20261120) == original
    assert sync._lifecycle_fact_for_target(bound, "002731", 1, 20261120) is None
    row = source_row(tmp_path, "002731.SZ", original)
    assert cache._verified_sop_skip("002731.SZ", row, 20261119, None) is None
    skipped = cache._verified_sop_skip("002731.SZ", row, 20261120, None)
    assert skipped["status"] == "SOP_SKIPPED"
    assert skipped["provider_invoked"] is False
    assert skipped["original_sync_row"] == row
    assert original == bound["002731.SZ"]


def test_existing_delisting_keeps_its_original_application_date(tmp_path):
    bound = facts()
    fact = bound["301139.SZ"]
    assert "apply_from_date" not in fact
    assert sync._lifecycle_fact_for_target(bound, "301139", 0, 20261027) is None
    assert sync._lifecycle_fact_for_target(bound, "301139", 0, 20261028) == fact
    row = source_row(tmp_path, "301139.SZ", fact)
    assert cache._verified_sop_skip("301139.SZ", row, 20261120, None)["provider_invoked"] is False


@pytest.mark.parametrize("change", ["future_gate", "notice_sha", "source_url", "last_trade", "new_code"])
def test_unreviewed_or_altered_lifecycle_fact_is_rejected(monkeypatch, change):
    policy = deepcopy(sync._daily_source_policy_additions())
    row = policy["verified_delisting_additions"][-1]
    if change == "future_gate":
        row["apply_from_date"] = "20261119"
    elif change == "notice_sha":
        row["official_notice"]["sha256"] = "0" * 64
    elif change == "source_url":
        row["official_notice"]["url"] = "https://example.invalid/unverified.pdf"
    elif change == "last_trade":
        row["last_trading_date"] = "20261111"
    else:
        row["ts_code"] = "002732.SZ"
    monkeypatch.setattr(sync, "_daily_source_policy_additions", lambda: policy)
    with pytest.raises(RuntimeError, match="SOURCE_POLICY_DELISTING_IDENTITY"):
        facts()


def test_cache_rejects_unbound_fact_and_changed_native_bars(tmp_path):
    fact = facts()["002731.SZ"]
    row = source_row(tmp_path, "002731.SZ", fact)
    altered = deepcopy(row)
    altered["lifecycle_fact"]["apply_from_date"] = "20261119"
    assert cache._verified_sop_skip("002731.SZ", altered, 20261120, None) is None
    Path(row["path"]).write_bytes(b"different historical bars")
    assert cache._verified_sop_skip("002731.SZ", row, 20261120, None) is None


def test_original_notice_and_frozen_policy_fields_are_bound():
    policy = sync._daily_source_policy_additions()
    assert policy["RESEARCH_ONLY"] is True
    assert all(policy[key] is False for key in ("production_allowed", "buy_gate_updated", "orders_sent"))
    fact = facts()["002731.SZ"]
    notice = fact["official_notice"]
    data = Path(notice["path"]).read_bytes()
    assert data.startswith(b"%PDF-")
    assert len(data) == 117964
    assert hashlib.sha256(data).hexdigest() == notice["sha256"]
    assert fact["historical_PIT"] is False
