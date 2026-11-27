from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest

from ops.pft_act080_p2.contracts import FEATURE_SETS, claim, seal, verify_payload
from ops.pft_act080_p2.outcomes import nonoverlap, pricing_outcomes
from ops.pft_act080_p2.prep import mlp_train_partition
from ops.pft_act080_p2.sources import load_features


def test_labels_pricing_and_independent_maturity():
    dates = [f"2024-01-{i:02}" for i in range(1, 12)]
    series = dates, [12, 10] + [100] * 9, [12, 10, 9.5] + [10] * 8, [8, 9, 9.4, 9.2] + [10] * 7
    outcome = pricing_outcomes(series, 0)
    assert outcome["T2"] == pytest.approx(-0.053)
    assert outcome["T5"] == pytest.approx(-0.003)
    assert outcome["T10"] == pytest.approx(-0.003)
    assert outcome["MAE5"] == pytest.approx(-0.103)
    assert outcome["tail_std"] and not outcome["tail_aux"]
    short = pricing_outcomes(series, 0, "2024-01-05")
    assert short["T2"] == outcome["T2"]
    assert all(short[k] is None for k in ("T5", "T10", "MAE5", "tail_std", "tail_aux"))
    windows = [{"security_id": "A", "session_idx": i, "candidate_event_id": str(i)} for i in (9, 10, 0)]
    assert [r["session_idx"] for r in nonoverlap(windows)] == [0, 10]


def test_projection_never_parses_holdout_feature_bytes():
    feature_names = FEATURE_SETS["FEAT_PLUS_ANCHOR_KB"]
    keys = ["candidate_event_id", "security_id", "trade_date", "structure_episode_id", "accepted_role", "accepted_flag"]
    allowed = ["k", "000058.SZ", "2024-01-01", "episode", "FIRST", "True"]
    excluded = ["j", "002865.SZ", "2024-01-01", "other", "FIRST", "True"]
    values = [b"1.25"] * 19 + [b"3", b"True", b"False", b"False", b"True"]
    records = [(",".join(keys + list(feature_names))).encode(), b",".join([",".join(allowed).encode(), *values]),
               b",".join([",".join(excluded).encode(), *([b"POISON"] * 24)])]
    data = BytesIO()
    with ZipFile(data, "w") as archive:
        archive.writestr("data/D_ONLY_FEATURES_001.csv", b"\n".join(records) + b"\n")
    with ZipFile(data) as archive:
        matrix = load_features(archive, [{"candidate_event_id": "k", "security_id": "000058.SZ",
                                          "D": "2024-01-01", "structure_episode_id": "episode"}])
    assert matrix == [[1.25] * 19 + [3, 1, 0, 0, 1]]


def test_inner_split_purge_embargo_and_seal(tmp_path):
    dates = [f"{i:03}" for i in range(80)]
    rows = [{"D": d, "security_id": "A", "session_idx": i, "fold": "TRAIN"} for i, d in enumerate(dates)]
    boundary, groups = mlp_train_partition(rows, {"A": (dates,)})
    assert boundary == "064"
    assert groups[53:55] == ["GRADIENT", "INNER_PURGE"]
    assert groups[63:65] == ["INNER_PURGE", "INNER_EMBARGO"]
    assert groups[73:75] == ["INNER_EMBARGO", "EARLY_STOP"]
    one = tmp_path / "ONCE"
    claim(one, stage="synthetic")
    with pytest.raises(FileExistsError):
        claim(one, stage="synthetic")
    payload = tmp_path / "payload"
    payload.mkdir()
    sample = payload / "x"
    sample.write_bytes(b"initial")
    lock = tmp_path / "seal"
    expected = seal(lock, payload, stage="synthetic")
    assert verify_payload(lock, payload, expected)["stage"] == "synthetic"
    sample.write_bytes(b"altered")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        verify_payload(lock, payload, expected)
