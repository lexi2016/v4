"""Bounded ACT-078A archive inputs and causal feature/label definitions."""

import csv
import hashlib
import io
from pathlib import Path
from zipfile import ZipFile

import numpy as np
import pandas as pd

FROZEN = "PFT_V4_ACT077A_V2_1_FROZEN_SPEC_PACK.zip"
FROZEN_CSV = "PFT_V4_ACT077A_UNIFIED_RADAR_V2_1_FROZEN_2020_2026.csv"
RAW = "PFT_V4_ACT074_VOL2_RAW_42_CHAINS.zip"
FROZEN_SHA = "2cda12c17c02abdfbff5555a53250510e28a8ef3de0e90f916d0adfc72f20d06"
FROZEN_CSV_SHA = "222e92f99dd02899027d1e2909ef19acd9943ca0842e038e1746550b8f926132"
VOLUME1_SHA = "975c2fcc29df298d004ce9f1cc8bf04e63760e01e9820c2fcac437d2d3160780"
ROSTER_SHA = "12fa517772635d5a6f4c8b677cd010f51d168986a288678ba578092cb64448f7"
MANIFEST = "RAW_42_CHAINS_VERIFIED_MANIFEST.csv"
BREADTH = "DAILY_41STOCKS_BREADTH_AND_SSE.csv"
RAW_START = "2020-01-02"
FROZEN_END = "2026-11-20"
RAW_ASOF = "2026-11-26"
VAL_START = "2024-01-01"
OOT_START = "2025-01-01"
PRE_OOT_END = "2024-12-31"
FEE = 0.003
EPS = 1e-10
BASE_AXIS = (
    "kdj_j", "ret_1d", "ret_5d", "vol_ratio_5d", "close_pos", "dist_w_atr", "wy_atr"
)
FEATURES = BASE_AXIS + tuple(f"{k}_rank252" for k in BASE_AXIS) + (
    "w_slope_5d", "w_slope_10d", "y_slope_10d", "y_slope_20d", "w_y_spread_atr",
    "pullback_volume_ratio", "anchor_dist_atr", "anchor_holds_low", "low60_gain",
    "distribution_10d", "distribution_14d", "support_stability_10d", "breadth_41_above_w",
)
OUTCOMES = ("t2_net", "t5_net", "t10_net", "mae5_net", "tail_std")
DATES = ("entry_D", "maturity_2_D", "maturity_5_D", "maturity_10_D")
ANCHOR_KEYS = (
    "D", "security_id", "name", "structure_episode_id", "kb_anchor_date", "kb_anchor_type",
    "kb_anchor_low", "hit_v21", "hit_v21_cd5", "visual_tier",
)
BRIDGE = {
    "open": "open", "high": "high", "low": "low", "close": "close", "volume": "volume",
    "W": "W", "Y": "Y", "atr14": "atr14", "Y_slope_10d": "y_slope_10d",
    "KDJ_J": "kdj_j", "r_D": "ret_1d", "close_location": "close_pos",
    "relV5": "vol_ratio_5d", "wy_atr": "wy_atr", "LOW60_GAIN": "low60_gain",
    "active_41_n": "active_41_n", "breadth_41_above_W": "breadth_41_above_w",
}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha_bytes(content):
    return hashlib.sha256(content).hexdigest()


def sha_file(path):
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def checked_archive(path, expected_sha=None, expected_bytes=None):
    size = path.stat().st_size
    digest = sha_file(path)
    require(expected_sha is None or digest == expected_sha, f"Wrong outer SHA for {path.name}")
    require(expected_bytes is None or size == expected_bytes, f"Wrong outer size for {path.name}")
    receipt = {"bytes": size, "sha256": digest, "members": {}}
    with ZipFile(path) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)), f"Duplicate member in {path.name}")
        expected = {}
        for line in archive.read("SHA256SUMS.txt").decode("utf-8-sig").splitlines():
            digest, name = line.split(maxsplit=1)
            require(name not in expected and len(digest) == 64, f"Invalid SHA member {name}")
            expected[name] = digest
        require(set(expected) == set(names) - {"SHA256SUMS.txt"}, f"SHA coverage {path.name}")
        for name, digest in expected.items():
            content = archive.read(name)
            require(sha_bytes(content) == digest, f"Member SHA mismatch {name}")
            receipt["members"][name] = {"bytes": len(content), "sha256": digest}
    return receipt


def volume1_path(sources):
    paths = sorted(sources.glob("PFT_V4_ACT074_VOL1*.zip"))
    require(len(paths) == 1, "ACT074 volume1 expected exactly once")
    return paths[0]


def verify_sources(sources):
    raw = checked_archive(sources / RAW, expected_bytes=3959949)
    frozen = checked_archive(sources / FROZEN, FROZEN_SHA, 897988)
    volume1 = checked_archive(volume1_path(sources), VOLUME1_SHA)
    require(frozen["members"][FROZEN_CSV]["sha256"] == FROZEN_CSV_SHA, "Frozen CSV SHA")
    require(volume1["members"][MANIFEST] == raw["members"][MANIFEST], "Raw manifests differ")
    return {RAW: raw, FROZEN: frozen, volume1_path(sources).name: volume1}


def read_chain_d_only(blob, until):
    header, *lines = blob.splitlines()
    # Raw archive rows are ISO date first and sorted. Cut bytes before parsing OHLC.
    lines = [line for line in lines if line[:10] <= until.encode("ascii")]
    return pd.read_csv(io.BytesIO(b"\n".join([header, *lines])), index_col="D")


def raw_chains(sources, until, receipts=None):
    chains = {}
    with ZipFile(sources / RAW) as archive:
        manifest = pd.read_csv(io.BytesIO(archive.read(MANIFEST)), dtype={"security_id": str})
        require(len(manifest) == manifest.security_id.nunique() == 42, "Raw manifest chain count")
        raw_members = {f"raw_42_chains/{key}.csv" for key in manifest.security_id}
        require(set(archive.namelist()) == raw_members | {MANIFEST, "SHA256SUMS.txt"}, "Raw chain membership")
        for row in manifest.itertuples(index=False):
            name = f"raw_42_chains/{row.security_id}.csv"
            blob = archive.read(name)
            if receipts is not None:
                metadata = receipts[RAW]["members"][name]
                require(metadata == {"bytes": row.csv_bytes, "sha256": row.csv_sha256}, f"Manifest {name}")
            header, *lines = blob.splitlines()
            dates = [line[:10] for line in lines]
            require(
                len(dates) == row.rows_full and dates[0].decode() == row.first_D
                and dates[-1].decode() == row.last_D == RAW_ASOF
                and sum(day <= FROZEN_END.encode() for day in dates) == row.rows_le_20261120
                and all(a < b for a, b in zip(dates, dates[1:])),
                f"Raw date/key manifest {name}",
            )
            chains[row.security_id] = read_chain_d_only(blob, until)
    roster = sorted(set(chains) - {"000001.SH"})
    require(len(roster) == 41 and sha_bytes(("\n".join(roster) + "\n").encode()) == ROSTER_SHA, "41-stock roster identity")
    return chains, manifest


def read_frozen(sources, open_outcomes):
    with ZipFile(sources / FROZEN) as archive:
        header, *lines = archive.read(FROZEN_CSV).splitlines()
    if open_outcomes:
        frozen = pd.read_csv(io.BytesIO(b"\n".join([header, *lines])))
        detailed = frozen
    else:
        frozen = pd.read_csv(io.BytesIO(b"\n".join([header, *lines])), usecols=ANCHOR_KEYS)
        train_val = [line for line in lines if line[:10] < OOT_START.encode()]
        detailed = pd.read_csv(io.BytesIO(b"\n".join([header, *train_val])))
    frozen = frozen.sort_values(["security_id", "D"]).reset_index(drop=True)
    require(
        len(frozen) == 3856 and frozen.security_id.nunique() == 41
        and frozen.D.min() == RAW_START and frozen.D.max() == FROZEN_END
        and not frozen.duplicated(["security_id", "D"]).any()
        and frozen.hit_v21.eq(True).all() and frozen.hit_v21_cd5.eq(True).all(),
        "Frozen V2.1 cohort identity",
    )
    require(frozen.kb_anchor_date.le(frozen.D).all() and frozen.kb_anchor_low.notna().all(), "Causal anchor")
    require(
        frozen.structure_episode_id.str.split("|", regex=False).str[0].eq(frozen.security_id).all(),
        "Episode ownership",
    )
    episode = frozen.groupby(["security_id", "structure_episode_id"], sort=False)
    require(episode.ngroups == 2361, "Episode count")
    frozen["episode_trigger_no"] = episode.cumcount() + 1
    frozen["first_D"] = episode.D.transform("first")
    # All frozen input triggers passed the source cooldown. The second is the
    # causal first re-confirmation; subsequent encounters are repeat signals.
    frozen["trigger_role"] = np.select(
        [frozen.episode_trigger_no.eq(1), frozen.episode_trigger_no.eq(2)],
        ["FIRST", "CONFIRM"], default="REPEAT",
    )
    frozen["period"] = np.select(
        [frozen.D.lt(VAL_START), frozen.D.lt(OOT_START)], ["TRAIN", "VAL"], default="OOT"
    )
    frozen["episode_period"] = np.select(
        [frozen.first_D.lt(VAL_START), frozen.first_D.lt(OOT_START)], ["TRAIN", "VAL"], default="OOT"
    )
    return frozen[list(ANCHOR_KEYS) + ["episode_trigger_no", "first_D", "trigger_role", "period", "episode_period"]], detailed


def white_yellow(close):
    white = close.ewm(span=10, adjust=False).mean().ewm(span=10, adjust=False).mean()
    yellow = sum(close.rolling(n).mean() for n in (14, 28, 57, 114)) / 4
    return white, yellow


def breadth_frame(chains):
    # Daily denominator uses only traded, SMA114-ready stocks.
    candidates = []
    for key, chain in chains.items():
        if key == "000001.SH":
            continue
        white, yellow = white_yellow(chain.close)
        candidates.append((chain.close > white).loc[yellow.notna()])
    day = pd.concat(candidates).groupby(level="D").agg(["size", "mean"])
    return day.rename(columns={"size": "active_41_n", "mean": "breadth_41_above_w"})


def divide(a, b):
    return a.div(b.where(b.ne(0)))


def price_features(chain):
    close, low, high, opening, volume = (chain[k] for k in ("close", "low", "high", "open", "volume"))
    frame = chain[["open", "high", "low", "close", "volume"]].copy()
    white, yellow = white_yellow(close)
    frame["W"], frame["Y"] = white, yellow
    prior = close.shift()
    atr = pd.concat([high-low, (high-prior).abs(), (low-prior).abs()], axis=1).max(axis=1).rolling(14).mean()
    frame["atr14"] = atr
    lowest = low.rolling(9).min()
    rsv = 100 * divide(close-lowest, high.rolling(9).max()-lowest)
    # A zero-width 9-day KDJ window is recorded as neutral per frozen parity.
    rsv = rsv.where(~(high.rolling(9).max()-lowest).eq(0), 50.0)
    k = rsv.ewm(alpha=1/3, adjust=False).mean()
    frame["kdj_j"] = 3*k - 2*k.ewm(alpha=1/3, adjust=False).mean()
    frame["ret_1d"] = close.pct_change()
    frame["ret_5d"] = close.pct_change(5)
    frame["vol_ratio_5d"] = divide(volume, volume.shift().rolling(5).mean())
    frame["close_pos"] = divide(close-low, high-low).fillna(0)
    frame["dist_w_atr"] = divide(close-white, atr)
    frame["w_y_spread_atr"] = divide(white-yellow, atr)
    frame["wy_atr"] = frame["w_y_spread_atr"].abs()
    for name in BASE_AXIS:
        frame[f"{name}_rank252"] = frame[name].rolling(252, min_periods=60).rank(pct=True)
    for name, line, windows in (("w", white, (5, 10)), ("y", yellow, (10, 20))):
        for days in windows:
            frame[f"{name}_slope_{days}d"] = line.pct_change(days)
    down = frame["ret_1d"].lt(0)
    frame["pullback_volume_ratio"] = divide(
        volume.where(down, 0).rolling(5).sum(), down.rolling(5).sum()*volume.shift().rolling(20).mean()
    )
    frame["low60_gain"] = close / low.rolling(60).min() - 1
    # Continuous joint selling intensity: prior volume surprise times downside
    # body or upper shadow, with causal rolling maxima for 10/14 traded days.
    body_down = divide((opening-close).clip(lower=0), atr)
    wick_up = divide(high-pd.concat([opening, close], axis=1).max(axis=1), atr)
    distribution = divide(volume, volume.shift().rolling(20).mean()) * (body_down + wick_up)
    frame["distribution_10d"] = distribution.rolling(10).max()
    frame["distribution_14d"] = distribution.rolling(14).max()
    frame["support_stability_10d"] = divide(close-white, atr).clip(-5, 5).rolling(10).mean()
    return frame.replace([np.inf, -np.inf], np.nan)


def feature_join(cohort, chains, breadth):
    chunks = []
    for key, subset in cohort.groupby("security_id", sort=True):
        chain = chains[key]
        feature = price_features(chain)
        day = subset.merge(feature, left_on="D", right_index=True, validate="one_to_one", how="left")
        require(day.close.notna().all(), f"Frozen D missing in raw chain {key}")
        anchor_low = chain.low.reindex(day.kb_anchor_date).to_numpy()
        require(np.allclose(anchor_low, day.kb_anchor_low, rtol=0, atol=EPS), f"Anchor raw parity {key}")
        day["anchor_dist_atr"] = divide(day.close-day.kb_anchor_low, day.atr14)
        day["anchor_holds_low"] = (day.close >= day.kb_anchor_low).astype(float)
        chunks.append(day)
    result = pd.concat(chunks).merge(breadth, left_on="D", right_index=True, how="left", validate="many_to_one")
    return result.sort_values(["security_id", "D"]).reset_index(drop=True)


def outcome_labels(chain):
    close = chain.close
    enter = chain.open.shift(-1).where(lambda value: value.gt(0))
    date = pd.Series(chain.index, index=chain.index, dtype="string")
    outcome = pd.DataFrame(index=chain.index)
    outcome["entry_D"] = date.shift(-1)
    for horizon in (2, 5, 10):
        outcome[f"maturity_{horizon}_D"] = date.shift(-horizon)
        outcome[f"t{horizon}_net"] = close.shift(-horizon)/enter-1-FEE
    low5 = chain.low.rolling(5).min().shift(-5)
    outcome["mae5_net"] = low5/enter-1-FEE
    tail = outcome.t2_net.le(-0.05) | outcome.mae5_net.le(-0.07)
    outcome["tail_std"] = tail.astype(float).where(outcome.t2_net.notna() & outcome.mae5_net.notna())
    return outcome


def outcome_join(features, chains):
    parts = []
    for key, subset in features.groupby("security_id", sort=True):
        source = outcome_labels(chains[key])
        parts.append(subset.merge(source, left_on="D", right_index=True, how="left", validate="one_to_one"))
    return pd.concat(parts).sort_values(["security_id", "D"]).reset_index(drop=True)


def frozen_parity(data, detailed, source_cutoff):
    checked = detailed[["security_id", "D", *BRIDGE, *OUTCOMES]].merge(
        data, on=["security_id", "D"], suffixes=("_frozen", ""), validate="one_to_one"
    )
    require(len(checked) == len(detailed) == len(data), "Frozen parity row alignment")
    audit = {}
    for expected, actual in BRIDGE.items():
        left = checked[expected + ("_frozen" if expected in data else "")]
        right = checked[actual]
        difference = (left-right).abs()
        require(left.isna().equals(right.isna()) and difference.dropna().le(EPS).all(), f"D-only parity {expected}: {difference.max()}")
        audit[expected] = {"n": int(left.notna().sum()), "max_abs_diff": float(difference.max())}
    horizons = dict(zip(OUTCOMES, (2, 5, 10, 5, 5)))
    for key, horizon in horizons.items():
        left = checked[key+"_frozen"]
        right = checked[key]
        date = checked[f"maturity_{horizon}_D"]
        common = date.le(source_cutoff).fillna(False)
        difference = (left[common]-right[common]).abs()
        require(
            left[common].isna().equals(right[common].isna()) and difference.dropna().le(EPS).all(),
            f"Outcome parity {key}: {difference.max()} within cutoff {source_cutoff}",
        )
        # Additional raw bars can mature a label that was unknown at the frozen cutoff.
        extended = date.gt(source_cutoff).fillna(False) & right.notna()
        require(not (left.notna() & right.isna() & ~common).any() or source_cutoff == PRE_OOT_END,
                f"Frozen positive coverage outside raw {key}")
        audit[key] = {"n": int(difference.notna().sum()), "max_abs_diff": float(difference.max()),
                      "new_raw_mature": int(extended.sum()), "null_at_active_cutoff": int(right.isna().sum())}
    return audit


def source_breadth_parity(sources, breadth, until):
    with ZipFile(volume1_path(sources)) as archive:
        source = read_chain_d_only(archive.read(BREADTH), until)
    source = source.loc[RAW_START:until]
    require(len(source) > 0 and source.index.is_unique, "No unique breadth source days")
    # Source and reconstruction name only differs for the percentage column.
    reference = source["active_41_n"].to_numpy()
    computed = breadth.reindex(source.index)
    require(np.array_equal(reference, computed.active_41_n.to_numpy()), "ACT074 active eligible breadth parity")
    diff = (source.breadth_41_above_W-computed.breadth_41_above_w).abs()
    require(diff.notna().all() and diff.le(EPS).all(), "ACT074 above-W daily breadth parity")
    return {"n": len(source), "max_abs_diff": float(diff.max())}


def prefix_check(cohort, chains, features):
    symbols = ("000058.SZ", "000776.SZ", "002594.SZ", "002865.SZ", "920748.BJ")
    evidence = []
    for key in symbols:
        unique = cohort.loc[cohort.security_id.eq(key), "D"].unique()
        require(len(unique) >= 3, f"Canary {key} has insufficient eligible dates")
        for cutoff in (unique[len(unique)//3], unique[2*len(unique)//3], unique[-1]):
            trimmed = {ticker: chain.loc[:cutoff] for ticker, chain in chains.items()}
            d_only = cohort[cohort.security_id.eq(key) & cohort.D.le(cutoff)]
            rebuilt = feature_join(d_only, trimmed, breadth_frame(trimmed))
            expected = features[features.security_id.eq(key) & features.D.le(cutoff)]
            left, right = rebuilt[list(FEATURES)].to_numpy(), expected[list(FEATURES)].to_numpy()
            require(np.array_equal(left, right, equal_nan=True), f"Non-zero prefix delta {key} @ {cutoff}")
            evidence.append({"security_id": key, "cutoff": str(cutoff), "rows": len(left), "max_abs_diff": 0.0})
    return evidence
