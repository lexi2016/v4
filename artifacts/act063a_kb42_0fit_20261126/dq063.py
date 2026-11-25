"""Read-only correction of the ACT-062A wick count binding and line-state encoding."""
from __future__ import annotations

from collections import Counter
from fractions import Fraction
from io import BytesIO
from zipfile import ZipFile

import numpy as np
import pandas as pd

from inputs063 import (
    ACT057, ACT060_CODE, ACT061_CODE, ACT062_CODE, BASE, CSTATE, LOW_WICK, MSTATE, UPPER,
    checked_csv, module,
)
from common062 import ACT056

OLD_RATE = "full20__peak_D0_wick_ge_40_rate"
OLD_N = "full20__peak_D0_wick_ge_40_n"
OLD_WICK_N = "full20__peak_D0_upper_wick_range_ratio_n"
WICK = "peak_D0_upper_wick_range_ratio"
SOURCE_FIELDS = ["security_id", "D", "observed_sessions", WICK]
LOW_NAMES = {"安德利", "幸福蓝海", "宝丰能源", "福莱新材", "新风光", "华纳药厂"}


def load(usage):
    seal = usage.json(ACT057 / "ACT057_LOCAL_FINAL_DELIVERY_VERIFIED.json")
    profile = checked_csv(usage, ACT057 / "delivery/ACT057_LOCAL_KB42_STOCK_EXIT_PROFILES.csv", seal,
                          ["security_id", "name", "archetype", "complete_20_n", OLD_RATE, OLD_N, OLD_WICK_N])
    receipt = usage.json(ACT057 / "delivery/ACT057_LOCAL_0FIT_RECEIPT.json")
    compute_receipt = ACT057 / "evidence/compute_receipt.json"
    usage.pin(compute_receipt, receipt["compute_evidence"])
    bound = usage.json(compute_receipt)
    src = ACT056 / "delivery/ACT056A_KB41_EXIT_FINGERPRINTS.csv"
    main = usage.csv(src, SOURCE_FIELDS)
    identity = usage.sources[str(src)]
    assert all(identity[k] == bound["inputs"][src.name][k] for k in ("bytes", "sha256"))
    zip_path = ACT056 / "delivery/ACT056A_000547_HTFZ_FULLLIFE_PACK.zip"
    usage.pin(zip_path, bound["inputs"][zip_path.name])
    member = "000547_exit_fingerprints.csv"
    with ZipFile(zip_path) as package:
        payload = package.read(member)
        usage.direct_read_bytes += package.getinfo(member).compress_size
        usage.projected_decoded_bytes += len(payload)
    supplement = pd.read_csv(BytesIO(payload), usecols=SOURCE_FIELDS)
    tape = pd.concat([main, supplement], ignore_index=True)
    assert len(main) == 3175 and len(supplement) == 199 and len(tape) == 3374
    assert not tape.duplicated(["security_id", "D"]).any()
    for path in (ACT057 / "compute.py", ACT060_CODE, ACT061_CODE / "controls061.py", ACT062_CODE / "dictionary062.py"):
        usage.pin(path)
    return profile, tape


def wick_patch(dictionary, profile, tape):
    raw = tape.loc[tape.observed_sessions.eq(20)].copy()
    raw["hit"] = raw[WICK].ge(.4).where(raw[WICK].notna())
    totals = raw.groupby("security_id").agg(
        source_complete_20_n=("D","size"),
        observed_n=(WICK,"count"),
        true_hits=("hit","sum"),
    )
    assert set(totals.index) == set(dictionary.ts_code)
    assert not raw[WICK].dropna().lt(0).any()
    merged = (dictionary.set_index("ts_code", verify_integrity=True)
              .join(profile.set_index("security_id", verify_integrity=True), rsuffix="_act057")
              .join(totals)).sort_index()
    assert merged.stock_name.equals(merged.name)
    assert merged.archetype.equals(merged.archetype_act057)
    for field in ("complete_20_n", OLD_RATE, OLD_N, OLD_WICK_N):
        assert not merged[field].isna().any()
    assert merged.complete_20_n.equals(merged.source_complete_20_n)
    assert merged[OLD_N].equals(merged[OLD_WICK_N])
    assert merged[OLD_N].equals(merged.observed_n)
    assert merged[f"{UPPER}_hits"].equals(merged[f"{UPPER}_denominator"])
    assert merged[f"{UPPER}_hits"].equals(merged[OLD_N])
    exact = merged.true_hits / merged.observed_n
    published = exact.map(lambda v: float(f"{v:.10g}"))
    for field in (OLD_RATE, f"{UPPER}_rate"):
        assert np.allclose(published, merged[field], rtol=0, atol=2e-15)
    assert merged.observed_n.sum() == 3119
    assert set(merged.loc[merged[LOW_WICK], "stock_name"]) == LOW_NAMES
    results = []
    for code, row in merged.iterrows():
        hits, n = int(row.true_hits), int(row.observed_n)
        results.append(dict(
            patch="DQ-01", ts_code=code, stock_name=row.stock_name, archetype=row.archetype,
            status="AUTHORITATIVE_NUMERATOR_CORRECTED", old_act062a_hits=int(row[f"{UPPER}_hits"]),
            old_act062a_denominator=int(row[f"{UPPER}_denominator"]), old_act062a_rate=row[f"{UPPER}_rate"], published_rate_precision="%.10g",
            act057_valid_n=int(row[OLD_N]), act057_wick_nonnull_n=int(row[OLD_WICK_N]),
            act057_rate=row[OLD_RATE], act057_full20_event_n=int(row.complete_20_n),
            corrected_hits=hits, corrected_denominator=n, exact_rate_ratio=f"{hits}/{n}",
            reduced_exact_rate=str(Fraction(hits,n)), corrected_rate=hits/n,
            hits_delta=hits-int(row[f"{UPPER}_hits"]), low_wick_frozen_before=bool(row[LOW_WICK]),
            low_wick_frozen_after=bool(row[LOW_WICK]),
            definition="Full-20 ACT057 cohort, valid peak-day upper-wick/range >= 0.40",
            frozen_code="ACT057 compute.py:106-112,150-155; 3b8e496f:artifacts/act062a_kb42_0fit_20261125/dictionary062.py:179-181",
            reason="ACT062A mapped ACT057 valid sample count (_n) into hits; observed event flags supply true hits",
        ))
    stats = {"stocks":len(results), "old_hits":int(merged[f"{UPPER}_hits"].sum()),
             "corrected_hits":int(merged.true_hits.sum()), "denominator":int(merged.observed_n.sum()),
             "rates_unchanged_at_published_precision_n":len(results),
             "max_exact_to_published_rate_abs_error":float((exact-merged[OLD_RATE]).abs().max()), "low_wick_stock_names":sorted(LOW_NAMES),
             "act057_complete_20_n":int(merged.complete_20_n.sum())}
    return results, stats


def state_patch(dictionary, controls, stores):
    frozen = module("act063_existing_line_state", ACT060_CODE)
    refs = dictionary.set_index("ts_code")
    counts = Counter()
    for row in controls.itertuples(index=False):
        expected_col = {"MAIN_REVERSE_EVENT": MSTATE, "SAME_STOCK_ORDINARY_CONTROL": CSTATE}[row.role]
        state = frozen.state_text(frozen.known_state(stores[row.security_id], int(row.D_ordinal)))
        assert state == row.D_minus_1_line_state
        numeric_existing = state if state == "UNKNOWN" else str(int(state))
        assert refs.loc[row.security_id, expected_col] == numeric_existing
        counts[state] += 1
    out = []
    for code, (white,yellow) in (("00",(0,0)), ("01",(0,1)), ("10",(1,0)), ("11",(1,1)), ("UNKNOWN",(None,None))):
        label = "UNKNOWN" if white is None else f"WHITE_{'GE' if white else 'LT'}|YELLOW_{'GE' if yellow else 'LT'}"
        out.append(dict(
            patch="DQ-03", status="AUTHORITATIVE_ENUM_CONFIRMED", canonical_state=code,
            numeric_import_display=code if white is None else str(int(code)),
            white_bit=white, yellow_bit=yellow, state_label=label,
            observed_84_rows=counts[code],
            definition="D−1 close >= white is first bit; close >= yellow is second bit; missing/invalid bar or lines -> UNKNOWN",
            frozen_code=f"{BASE[:8]}:artifacts/act060a_kb35_20261125/compute060.py:183-194; artifacts/act061a_kb42_exit_20261125/controls061.py:270; artifacts/act062a_kb42_0fit_20261125/dictionary062.py:26-39,167-168; common062.py:99-101",
            reason="ACT062A numeric inference at ACT061A CSV load stripped leading zeros before output; source state is two-character text",
        ))
    assert sum(counts.values()) == 84
    return out, dict(counts)
