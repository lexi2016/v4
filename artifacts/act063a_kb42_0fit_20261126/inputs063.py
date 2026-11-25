"""Bind the frozen ACT-061A/062A inputs and narrowly load the stock Reader."""
from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parent
ACT062_CODE = ROOT.parent / "act062a_kb42_0fit_20261125"
sys.path.insert(0, str(ACT062_CODE))

from common062 import ACT057, ACT061, BATCHES, WORKSPACE, Usage, module
from run062 import bind_reader

BASE = "3b8e496f33eca3578c3ce859340ce283c192c513"
ACT062_LOCAL = Path.home() / ".codex/worktrees/act062a-kb42-0fit-20261125/artifacts/act062a_kb42_0fit_20261125"
ACT030 = BATCHES / "ACT030_CODEX_PHASE2_E1_E2_20261123"
ACT020 = BATCHES / "ACT020_CODEX_V16_LIQUIDITY_MULTIMODEL_20261123"
ACT060_CODE = ROOT.parent / "act060a_kb35_20261125/compute060.py"
ACT061_CODE = ROOT.parent / "act061a_kb42_exit_20261125"
UPPER = "post_d_exit_monitor_only_long_upper_wick_peak_ge40"
MSTATE = "strict_d0_causal_main_d1_line_state"
CSTATE = "strict_d0_causal_control_d1_line_state"
LOW_WICK = "boundary_low_upper_wick_act061b"
RELAPSE = "POSITIVE_PEAK_NEGATIVE_D20"
HOLD = "COMPLEMENT_411"


def expected_file(receipt, name):
    return next(row for row in receipt["files"] if row["name"] == name)


def checked_csv(usage, path, receipt, fields, **kwargs):
    data = usage.csv(path, fields, **kwargs)
    expected = expected_file(receipt, path.name)
    actual = usage.sources[str(path)]
    assert all(actual[key] == expected[key] for key in ("bytes", "sha256")), path
    return data


def verified_sources(usage):
    seal = usage.json(ACT062_LOCAL / "evidence/ACT062A_POST_UPLOAD_VERIFICATION.json")
    assert seal["action"] == "ACT-062A"
    assert seal["git"]["commit"] == BASE
    assert seal["drive"]["all_six_actual_raw_byte_and_sha256_matches"]
    delivery = ACT062_LOCAL / "results/primary"
    usage.pin(delivery / "ACT062A_0FIT_RECEIPT.json", expected_file(seal["drive"], "ACT062A_0FIT_RECEIPT.json"))
    dictionary = checked_csv(usage, delivery / "ACT062A_KB42_TAG_DICTIONARY_V1.csv",
                             seal["drive"], ["ts_code", "stock_name", "frozen_archetype", MSTATE, CSTATE,
                                              LOW_WICK, *[f"{UPPER}_{key}" for key in ("rate", "hits", "denominator")]],
                             dtype={MSTATE: str, CSTATE: str}).rename(columns={"frozen_archetype":"archetype"})
    assert dictionary.ts_code.is_unique and len(dictionary) == 42
    recon = checked_csv(usage, delivery / "ACT062A_KB42_VS_FLAGSHIP_120D_RECON.csv",
                        seal["drive"], None)
    recon = recon.loc[recon.row_type.eq("EVENT")].copy()
    assert len(recon) == 162 and not recon.duplicated(["ts_code", "D"]).any()
    old_061 = usage.json(ACT061 / "ACT061A_FINAL_DELIVERY_VERIFIED.json")
    waves = checked_csv(usage, ACT061 / "delivery/ACT061A_KB42_562_EXIT_PATHS.csv", old_061,
                        ["security_id", "name", "archetype", "event_id", "D", "D_ordinal",
                         "cohort", "event_group", "full20", "warning_first_offset",
                         "close_ret_D20_pct", "close_ret_D20_close_d_basis", "D_basis_close_verified"])
    assert len(waves) == 583 and waves.event_id.is_unique
    complete = waves.loc[waves.full20]
    assert complete.cohort.value_counts().to_dict() == {HOLD: 411, RELAPSE: 151}
    assert set(waves.security_id) == set(dictionary.ts_code) - {"600016.SH"}
    controls = checked_csv(usage, ACT061 / "delivery/ACT061A_KB42_CLEAN_CONTROLS_84.csv", old_061,
                           ["security_id", "D_ordinal", "role", "D_minus_1_line_state"],
                           dtype={"D_minus_1_line_state": str})
    assert len(controls) == 84 and not controls.duplicated(["security_id", "role"]).any()
    assert set(controls.security_id) == set(dictionary.ts_code)
    ingress = ROOT / "input_ingress"
    md = {
        "ACT062B_KB42_TAG_DICTIONARY_AND_MODELING_READINESS_V1.md": (
            55468, "6f666cae564d9ff2c2d79d843f9fc168e0f94abd6dba7df916d5ec1d479291d7"),
        "ACT062B_BLIND_WINDOW_AUDIT_AND_MANUAL_V14_DELTA.md": (
            52720, "1903d1a9bacb2878122a0c97d34c491b53d80efc4a49d7088256bf10ef8f80c8"),
    }
    for name, (size, checksum) in md.items():
        usage.pin(ingress / name, {"bytes": size, "sha256": checksum})
    return dictionary, recon, waves, controls


def csv_payload(frame):
    return frame.to_csv(index=False, lineterminator="\n", float_format="%.14g").encode("utf-8")
