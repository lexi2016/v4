"""Synthetic contract checks. No model fit, market file, or sealed rows are opened."""

import numpy as np
import pytest

from ops.pft_act080_p2.contracts import claim, read_json, verify_payload
from ops.pft_act080_p2.fit import ledger_rows
from ops.pft_act080_p2.holdouts import _ordinal, screen
from ops.pft_act080_p2.model_io import normalizer, transform
from ops.pft_act080_p2.open_oot import OPEN_CLAIM, OPEN_STATUS, RELEASE_DIR, RELEASE_SEAL, open_once
from ops.pft_act080_p2.selection import choose, threshold_rows


def sample(cid, stock, session):
    return {"candidate_event_id": cid, "structure_episode_id": "W" + cid,
            "security_id": stock, "D": f"D{session}", "session_idx": session}


def test_exact_union_neighbor_pairs_and_partial_windows():
    events = [sample(str(i), "A", i) for i in (0, 10, 11, 19, 20, 21, 29, 30, 31)]
    events.append(sample("other", "B", 20))
    clean, proof = screen(events, {"A": [("one", "D20", 20), ("two", "D25", 25)]}, "test")
    assert [r["candidate_event_id"] for r in clean] == ["0", "other"]
    matches = {(r["event_session_idx"], r["sample_id"]): r for r in proof}
    assert matches[10, "one"]["signed_session_gap"] == -10 and not matches[10, "one"]["holding_overlap"]
    assert matches[11, "one"]["holding_overlap"] and matches[11, "one"]["overlap_start_session_idx"] == 21
    assert matches[11, "one"]["overlap_end_session_idx"] == 21
    assert matches[30, "one"]["signed_session_gap"] == 10 and not matches[30, "one"]["holding_overlap"]
    assert (31, "one") not in matches and (31, "two") in matches
    assert _ordinal({"A": (["a", "c"],)}, "A", "c") == 1
    with pytest.raises(ValueError, match="missing exact observed ordinal"):
        _ordinal({"A": (["a", "c"],)}, "A", "b")


def test_train_only_scaling_and_deterministic_val_objects():
    train = np.repeat(np.array([[1], [np.nan], [3]], dtype=float), 19, axis=1)
    scaler = normalizer(train, "FEAT_BASE_19")
    assert scaler["median"] == [2] * 19
    assert scaler["mean"] == [2] * 19
    assert (transform(np.zeros((1, 19)), scaler) < 0).all()
    mature = []
    for i in range(300):
        mature.append({**sample(str(i), "A", i), "T2": 0.01, "T5": 0.02, "T10": 0.03,
                       "MAE5": -0.01, "tail_std": i < 120, "tail_aux": False})
    scores = np.arange(len(mature)) / len(mature)
    points = []
    for family in ("HGB", "LOGISTIC"):
        for feature_set in ("FEAT_PLUS_ANCHOR_KB", "FEAT_BASE_19"):
            points.extend(threshold_rows(family, feature_set, scores, mature))
    choice = choose(points)
    assert choice["family"] == "LOGISTIC" and choice["feature_set"] == "FEAT_BASE_19"
    assert choice["VAL_quantile"] == 0.5 and choice["VAL_coverage"] == 0.5
    assert choice["tail_std_rate"] == 0
    assert choose(list(reversed(points))) == choice


def test_attempt_ledger_distinguishes_dispatch_from_fit(tmp_path):
    for identity in ("attempt0", "attempt1", "attempt2"):
        claim(tmp_path / f"{identity}_DISPATCH.json", fit_id=identity, family="TEST")
    claim(tmp_path / "attempt0_END.json", status="FAIL", error="pre-FIT gate")
    claim(tmp_path / "attempt1_START.json", invoked=True)
    claim(tmp_path / "attempt1_END.json", status="FAIL", error="in-FIT error")
    claim(tmp_path / "attempt2_START.json", invoked=True)
    rows = ledger_rows(tmp_path)
    assert [(r["fit_invoked"], r["status"]) for r in rows] == [(0, "FAIL"), (1, "FAIL"), (1, "STARTED")]


@pytest.mark.parametrize("will_fail", (False, True))
def test_open_claim_physically_precedes_issue_and_remains_on_failure(tmp_path, monkeypatch, will_fail):
    from ops.pft_act080_p2 import open_oot

    seals = tmp_path / "preflight"
    seals.touch()
    compare = []
    monkeypatch.setattr(open_oot, "verify", lambda *_: None)
    monkeypatch.setattr(open_oot, "_verify_gate", lambda *_: {"fit_id": "FROZEN"})

    def issue(root, scratch, *unused):
        assert read_json(root / OPEN_CLAIM)["OOT_OPEN_COUNT"] == 1
        compare.append("issued")
        (scratch / "projected.txt").write_text("synthetic only")
        if will_fail:
            raise ValueError("test release interrupted")
        return {"clean_exclusion": {"clean_non_Junda": 1}, "promotion_research_gate": {"status": "NOT_PROMOTED"}}

    monkeypatch.setattr(open_oot, "_issue", issue)
    args = (tmp_path, seals, seals, seals, "d" * 64)
    if will_fail:
        with pytest.raises(ValueError, match="release interrupted"):
            open_once(*args)
        assert read_json(tmp_path / OPEN_STATUS)["status"] == "PARTIAL_DO_NOT_REOPEN"
        assert (tmp_path / ".oot_pending" / "projected.txt").is_file()
    else:
        receipt = open_once(*args)
        assert receipt["OOT_OPEN_COUNT"] == 1
        assert verify_payload(tmp_path / RELEASE_SEAL, tmp_path / RELEASE_DIR, receipt["release_sha256"])["OOT_OPEN_COUNT"] == 1
    with pytest.raises(FileExistsError, match="already claimed"):
        open_once(*args)
    assert compare == ["issued"]
