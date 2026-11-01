"""stage_center.runner: slot_idempotency (review candidate, not deployment)."""
from __future__ import annotations
from stage_center.raw_store import RawStore
from stage_center.raw_store import RawStoreError
from stage_center.selection import SelectionError
from stage_center.selection import SelectionStore
from stage_center.runner import RunnerError, _existing_binding_matches, _latest_entry


def _StageCenterRunner__existing_slot_body(self, trade_date, stage_id, markets, candidate_sha_by_market):
    """Read reusable slot lanes against their own authority bindings.

        The old slot identity carried one candidate SHA for the whole stage.
        That made a missing A current turn the HK D-1 SHA into a global
        mismatch (and made a good HK lane unreusable).  Keep malformed store
        trios fail-closed, while treating a candidate mismatch as a lane-local
        cache miss so the other market can be reused safely.
        """
    if isinstance(candidate_sha_by_market, str):
        expected_sha = {market: candidate_sha_by_market for market in markets}
    else:
        expected_sha = {market: candidate_sha_by_market.get(market) for market in markets}
    raw_bundle_entry = _latest_entry(self.config.raw_root, "bundle_latest.json", f"{trade_date}/{stage_id}")
    selection_entries: dict[str, Mapping[str, Any] | None] = {
        market: _latest_entry(self.config.selection_root, "selection_latest.json", f"{trade_date}/{stage_id}/{market}")
        for market in markets
    }
    raw_market_present = any(_latest_entry(self.config.raw_root, "latest.json", f"{trade_date}/{stage_id}/{market}") is not None for market in markets)
    present = raw_bundle_entry is not None or raw_market_present or any(value is not None for value in selection_entries.values())
    if not present:
        return "ABSENT", None
    raw_store = RawStore(self.config.raw_root)
    selection_store = SelectionStore(self.config.selection_root)
    raw_verified: dict[str, Mapping[str, Any]] = {}
    selections: dict[str, Mapping[str, Any]] = {}
    candidate_binding_errors: dict[str, str] = {}
    for market in markets:
        raw_entry = _latest_entry(self.config.raw_root, "latest.json", f"{trade_date}/{stage_id}/{market}")
        if raw_entry is not None:
            try:
                verified = raw_store.verify_run(trade_date, stage_id, market, str(raw_entry.get("run_id")))
            except (RawStoreError, ValueError) as error:
                raise RunnerError(f"existing raw market integrity failure: {market}") from error
            expected = expected_sha.get(market)
            if expected is None:
                candidate_binding_errors[market] = "existing raw candidate SHA cannot be verified: market binding unavailable"
            elif _existing_binding_matches(
                verified.get("source_evidence", ()),
                market=market,
                expected_sha=expected,
            ):
                raw_verified[market] = verified
            else:
                candidate_binding_errors[market] = f"existing raw candidate SHA mismatch: {market}"
        selection_entry = selection_entries.get(market)
        if selection_entry is not None:
            try:
                envelope = selection_store.read_verified(trade_date, stage_id, market)
            except (SelectionError, ValueError) as error:
                raise RunnerError(f"existing selection integrity failure: {market}") from error
            expected = expected_sha.get(market)
            if expected is None:
                candidate_binding_errors[market] = "existing selection candidate SHA cannot be verified: market binding unavailable"
            elif _existing_binding_matches(
                envelope.get("source_evidence", ()),
                market=market,
                expected_sha=expected,
            ):
                selections[market] = envelope
            else:
                candidate_binding_errors[market] = f"existing selection candidate SHA mismatch: {market}"
    if raw_bundle_entry is not None and len(raw_verified) == len(markets):
        try:
            raw = raw_store.read_verified_bundle(trade_date, stage_id)
        except (RawStoreError, ValueError) as error:
            raise RunnerError("existing raw bundle integrity failure") from error
    else:
        raw = {"receipt": {"markets": {market: dict(entry) for market, entry in raw_verified.items()}}}
    if len(raw_verified) == len(markets) and len(selections) == len(markets):
        return "VERIFIED", {"raw": raw, "selections": selections, "raw_verified": raw_verified, "candidate_binding_errors": candidate_binding_errors}
    if not raw_verified and not selections:
        return "ABSENT", None
    return "PARTIAL", {"raw": raw, "selections": selections, "raw_verified": raw_verified, "candidate_binding_errors": candidate_binding_errors}
