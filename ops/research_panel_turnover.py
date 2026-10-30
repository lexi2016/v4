"""Ordinary A-share turnover from the existing TDX daily and GBBQ inputs.

GBBQ is a later capture of dated events, not historical PIT certification.
Only observed native shares are divided by the dated *ordinary* circulating
share count. Unknown event semantics and conflicting snapshots remain null.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from collections import OrderedDict
from pathlib import Path
import json
import math
import struct
import zipfile

import numpy as np
import pandas as pd

from ops.research_panel_factor_cache import QfqGateError, _source, canonical_sha, sha

SNAPSHOTS = frozenset({2, 3, 5, 7, 8, 9, 10})
MARKETS = {0: "SZ", 1: "SH", 2: "BJ"}
POLICY = "TDX_GBBQ_ORDINARY_FLOAT_ASOF_EVENT_RESEARCH_V1"


@dataclass
class CapitalIndex:
    groups: dict[str, pd.DataFrame]
    ambiguous: set[str]
    coverage_end: int
    timelines: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]] = field(default_factory=dict)

    @classmethod
    def from_frame(cls, frame: pd.DataFrame, coverage_end: int) -> "CapitalIndex":
        required = {"market", "code", "datetime", "category", "hongli_panqianliutong",
                    "peigujia_qianzongguben", "songgu_qianzongguben", "peigu_houzongguben"}
        if set(frame.columns) != required:
            raise ValueError("GBBQ_SCHEMA_UNBOUND")
        work = frame.copy()
        work["code"] = work.code.astype(str).str.zfill(6)
        if not work.code.str.fullmatch(r"[0-9]{6}").all():
            raise ValueError("GBBQ_CODE_INVALID")
        ambiguous = set(work.loc[work.market.eq(99), "code"])
        work = work.loc[work.market.isin(MARKETS) & work.datetime.le(coverage_end)].copy()
        work["symbol"] = work.code + "." + work.market.map(MARKETS)
        groups = {code: group.sort_values("datetime", kind="stable")
                  for code, group in work.groupby("symbol", sort=False)}
        return cls(groups, ambiguous, coverage_end)

    def _timeline(self, code: str) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        if code in self.timelines:
            return self.timelines[code]
        changes: dict[int, tuple[float, str, int]] = {}
        if code[:6] in self.ambiguous:
            changes[19000101] = (np.nan, "GBBQ_UNKNOWN_MARKET_CODE_COLLISION", 0)
        else:
            group = self.groups.get(code)
            prior_value = None
            prior_date = None
            if group is not None:
                for date, day in group.groupby("datetime", sort=True):
                    date = int(date)
                    snapshots = day.loc[day.category.isin(SNAPSHOTS)]
                    other = day.loc[~day.category.isin(SNAPSHOTS | {1})]
                    actions = day.loc[day.category.eq(1)]
                    share_action = any(not math.isfinite(float(row.songgu_qianzongguben))
                        or not math.isfinite(float(row.peigu_houzongguben))
                        or float(row.songgu_qianzongguben) != 0 or float(row.peigu_houzongguben) != 0
                        for row in actions.itertuples())
                    if not other.empty or share_action:
                        reason = "UNRESOLVED_CAPITAL_EVENT" if not other.empty else "STOCK_DISTRIBUTION_WITHOUT_RESOLVED_SNAPSHOT"
                        changes[date] = (np.nan, reason, date)
                        prior_value, prior_date = None, None
                        continue
                    if snapshots.empty:
                        continue
                    candidates = set()
                    for row in snapshots.itertuples():
                        before, value, total = (float(row.hongli_panqianliutong),
                                                float(row.songgu_qianzongguben),
                                                float(row.peigu_houzongguben))
                        candidates.add((before, value, total))
                    if len(candidates) != 1:
                        changes[date] = (np.nan, "SAME_DAY_CAPITAL_CONFLICT", date)
                        prior_value, prior_date = None, None
                        continue
                    before, value, total = next(iter(candidates))
                    if not all(math.isfinite(v) for v in (before, value, total)) or value <= 0 or total <= 0 or value > total * 1.000002:
                        changes[date] = (np.nan, "INVALID_CAPITAL_SNAPSHOT", date)
                        prior_value, prior_date = None, None
                        continue
                    if (prior_value is not None and prior_date is not None and before > 0
                            and not math.isclose(before, prior_value, rel_tol=0.000002, abs_tol=0.0001)):
                        # Both snapshots disagree about the intervening level.
                        # Do not guess when the unrecorded change happened.
                        changes[prior_date + 1] = (np.nan, "CAPITAL_CONTINUITY_CONFLICT", prior_date)
                    changes[date] = (value, "GBBQ_DATED_SNAPSHOT", date)
                    prior_value, prior_date = value, date
        ordered = sorted(changes.items())
        result = (np.array([x[0] for x in ordered], dtype=np.int64),
                  np.array([x[1][0] for x in ordered], dtype=np.float64),
                  np.array([x[1][1] for x in ordered], dtype=object),
                  np.array([x[1][2] for x in ordered], dtype=np.int64))
        self.timelines[code] = result
        return result

    def resolve(self, code: str, dates) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        dates = np.asarray(dates, dtype=np.int64)
        values = np.full(len(dates), np.nan)
        reasons = np.full(len(dates), "NO_PRIOR_CAPITAL_SNAPSHOT", dtype=object)
        event_dates = np.zeros(len(dates), dtype=np.int64)
        keys, vals, why, events = self._timeline(code)
        if len(keys):
            pos = np.searchsorted(keys, dates, side="right") - 1
            hit = pos >= 0
            values[hit], reasons[hit], event_dates[hit] = vals[pos[hit]], why[pos[hit]], events[pos[hit]]
        beyond = dates > self.coverage_end
        values[beyond], reasons[beyond], event_dates[beyond] = np.nan, "GBBQ_CAPTURE_DATE_UNCOVERED", 0
        return values, reasons, event_dates


def calculate(code: str, dates, native_shares, capital: CapitalIndex) -> pd.DataFrame:
    """One row per supplied date; no QFQ volume or latest-share backfill."""
    dates = np.asarray(dates, dtype=np.int64)
    shares = np.asarray(native_shares, dtype=np.float64)
    if len(dates) != len(shares):
        raise ValueError("TURNOVER_INPUT_LENGTH_MISMATCH")
    floats, reasons, event_dates = capital.resolve(code, dates)
    invalid_volume = ~np.isfinite(shares) | (shares < 0)
    reasons[invalid_volume] = "NATIVE_SHARE_VOLUME_MISSING"
    valid = np.isfinite(floats) & (floats > 0) & ~invalid_volume
    rates = np.full(len(dates), np.nan)
    rates[valid] = shares[valid] / (floats[valid] * 10000.0) * 100.0
    return pd.DataFrame(dict(trade_date=dates, turnover_rate_pct=rates,
                             turnover_float_share_10k=floats, turnover_capital_event_date=event_dates,
                             turnover_status=reasons))


@dataclass
class DailyTurnover:
    target: int
    capital: CapitalIndex | None
    shares: dict[tuple[int, str], int]
    binding: dict
    failure: str | None = None

    @property
    def identity(self) -> str:
        return canonical_sha(dict(policy=POLICY, helper_sha256=sha(Path(__file__)),
                                  target=self.target, binding=self.binding, failure=self.failure))

    def verify_binding(self) -> None:
        """Reject an input changed during a candidate build."""
        if not self.binding:
            return
        refs = [self.binding["sync"], self.binding["package"], self.binding["input_ref"]]
        descriptor = self.binding["gbbq"]
        refs.extend(descriptor[key] for key in ("capture", "raw", "archive", "parser",
                                                "category_policy", "derived_parquet", "derived_receipt"))
        for ref in refs:
            if sha(Path(ref["path"])) != ref["sha256"]:
                raise QfqGateError("TURNOVER_INPUT_CHANGED_DURING_BUILD:" + ref["path"])

    def apply_target(self, code: str, frame: pd.DataFrame) -> pd.DataFrame:
        out = frame.copy()
        for col in ("turnover_rate_status", "turnover_rate_volume_source", "turnover_rate_denominator_10k"):
            if col not in out:
                out[col] = None
        mask = pd.to_numeric(out.trade_date).eq(self.target)
        if not mask.any():
            return out
        if "turnover_rate_pct" not in out:
            out["turnover_rate_pct"] = np.nan
        if "float_share_10k" not in out:
            out["float_share_10k"] = np.nan
        needs = mask & pd.to_numeric(out.turnover_rate_pct, errors="coerce").isna()
        if not needs.any():
            return out
        market = {"SZ": 0, "SH": 1, "BJ": 2}.get(code[-2:])
        shares = self.shares.get((market, code[:6]))
        if self.failure or self.capital is None:
            out.loc[needs, "turnover_rate_status"] = self.failure or "GBBQ_INPUT_MISSING"
        elif shares is None:
            out.loc[needs, "turnover_rate_status"] = "G4_UNPRICED_OR_MISSING"
        else:
            result = calculate(code, [self.target], [shares], self.capital).iloc[0]
            out.loc[needs, "turnover_rate_status"] = result.turnover_status
            out.loc[needs, "turnover_rate_volume_source"] = "TDX_OFFICIAL_G4DAY_NATIVE_SHARES"
            if pd.notna(result.turnover_rate_pct):
                out.loc[needs, "turnover_rate_pct"] = result.turnover_rate_pct
                out.loc[needs, "turnover_rate_denominator_10k"] = result.turnover_float_share_10k
                missing_float = needs & pd.to_numeric(out.float_share_10k, errors="coerce").isna()
                out.loc[missing_float, "float_share_10k"] = result.turnover_float_share_10k
        return out


def load_daily(data_root: Path, tdx_root: Path, target: int) -> DailyTurnover:
    """Use only the same-date, already-produced inputs; never fetch or write."""
    root = data_root / "runtime/cache/data_layer_daily_formula_increment_update_v1"
    sync = tdx_root.parent / "receipts/a_sync_authority" / str(target) / "summary.json"
    if not sync.is_file():
        return DailyTurnover(target, None, {}, {}, "DAILY_SYNC_RECEIPT_MISSING")
    try:
        from ops.research_panel_daily_source import _detector
        from ops.research_panel_tdx_adjustment_inputs import load_event_detector
        from ops._a_share_daily_sync_parts.official_daily_package import OfficialDailyPackage
        summary = json.loads(sync.read_text())
        source = summary["official_daily_source"]
        if int(summary["target_date"]) != target or source["source_kind"] != "TDX_OFFICIAL_G4DAY":
            raise ValueError("DAILY_SYNC_SOURCE_IDENTITY_CONFLICT")
        package = OfficialDailyPackage(source["input_ref"], target)
        if source["package"] != package.package_ref:
            raise ValueError("DAILY_SYNC_PACKAGE_IDENTITY_CONFLICT")
        descriptor = _detector(root, target, current=False)
        load_event_detector(descriptor, target)
        capital = CapitalIndex.from_frame(pd.read_parquet(descriptor["derived_parquet"]["path"]), target)
        shares = {key: item[2] for key, item in package.rows.items()}
        return DailyTurnover(target, capital, shares,
            dict(sync=dict(path=str(sync), sha256=sha(sync)), package=package.package_ref,
                 input_ref=package.input_ref, gbbq=descriptor))
    except (OSError, KeyError, TypeError, ValueError, QfqGateError, zipfile.BadZipFile, struct.error) as exc:
        return DailyTurnover(target, None, {}, {}, "DAILY_TURNOVER_INPUT_UNAVAILABLE:" + type(exc).__name__ + ":" + str(exc))


class HistoricalOverlay:
    """Explicit, SHA-bound missing-value input for the original QFQ owner."""

    def __init__(self, ref: dict):
        self.ref = dict(ref)
        self.value = json.loads(_source(ref, owner="turnover overlay descriptor").read_text())
        v = self.value
        if (v.get("schema") != "a_share_turnover_overlay_v2" or v.get("policy") != POLICY
                or type(v.get("cutoff")) is not int or v.get("historical_PIT") is not False
                or v.get("RESEARCH_ONLY") is not True
                or any(v.get(k) is not False for k in ("production_allowed", "buy_gate_updated", "orders_sent"))
                or type(v.get("projection_generation_id")) is not str
                or type(v.get("projection_asof_date")) is not int
                or v.get("projection_asof_date") != v.get("cutoff")
                or type(v.get("baseline_generation_id")) is not str
                or type(v.get("baseline_asof_date")) is not int
                or v.get("cutoff") > v.get("baseline_asof_date")
                or set(v.get("projection_baseline_roles", {})) != {"selector", "backtest"}
                or set(v.get("baseline_roles", {})) != {"selector", "backtest"}):
            raise QfqGateError("TURNOVER_OVERLAY_CONTRACT_INVALID")
        self.cutoff = v["cutoff"]
        self.baseline_receipt_ref = v["baseline_generation_receipt"]
        self.baseline_receipt = json.loads(_source(self.baseline_receipt_ref,
            owner="turnover current baseline generation receipt").read_text())
        receipt = self.baseline_receipt
        if (receipt.get("schema") != "a_share_qfq_panel_v1"
                or receipt.get("status") != "CANDIDATE_READY"
                or receipt.get("generation_id") != v["baseline_generation_id"]
                or receipt.get("asof_date") != v["baseline_asof_date"]
                or receipt.get("target_date") != v["baseline_asof_date"]
                or not isinstance(receipt.get("candidates"), dict)
                or not isinstance(receipt.get("candidate_sha256"), dict)
                or not isinstance(receipt.get("counts"), dict)
                or set(receipt.get("candidates", {})) != {"selector", "backtest"}
                or set(receipt.get("candidate_sha256", {})) != {"selector", "backtest"}
                or set(receipt.get("counts", {})) != {"selector", "backtest"}
                or receipt.get("RESEARCH_ONLY") is not True
                or any(receipt.get(k) is not False for k in ("production_allowed", "buy_gate_updated", "orders_sent"))):
            raise QfqGateError("TURNOVER_CURRENT_BASELINE_RECEIPT_INVALID")
        for role in ("selector", "backtest"):
            bound = v["baseline_roles"][role]
            counts = receipt["counts"].get(role, {})
            if (receipt["candidates"].get(role) != bound.get("path")
                    or receipt["candidate_sha256"].get(role) != bound.get("sha256")
                    or type(counts.get("panel_rows")) is not int):
                raise QfqGateError("TURNOVER_CURRENT_BASELINE_RECEIPT_ROLE_CONFLICT:" + role)
        for key in ("projection_kernel", "projection_runner", "history_identity", "repair_runner",
                    "coverage", "d28", "d28_manifest", "repair"):
            _source(v[key], owner="turnover overlay " + key)
        for role in ("selector", "backtest"):
            _source(v["projection_baseline_roles"][role], owner="turnover projection baseline " + role)
        daily_receipt = json.loads(Path(v["d28_manifest"]["path"]).read_text())
        identity = daily_receipt.get("identity", {})
        if (canonical_sha(identity) != v.get("projection_identity_sha256")
                or identity.get("generation") != v["projection_generation_id"]
                or identity.get("panel") != v["projection_baseline_roles"]["selector"]["path"]
                or identity.get("panel_declared_sha256") != v["projection_baseline_roles"]["selector"]["sha256"]
                or identity.get("helper_sha256") != v["projection_kernel"]["sha256"]
                or identity.get("code_sha256") != v["projection_runner"]["sha256"]
                or daily_receipt.get("artifact") != v["d28"]):
            raise QfqGateError("TURNOVER_D28_PROJECTION_IDENTITY_CONFLICT")
        from ops.research_panel_qfq import panel_contract
        for role in ("selector", "backtest"):
            projection_contract = panel_contract(Path(v["projection_baseline_roles"][role]["path"]))
            if (projection_contract.get("generation_id") != v["projection_generation_id"]
                    or projection_contract.get("asof_date") != v["cutoff"]):
                raise QfqGateError("TURNOVER_PROJECTION_BASELINE_ROLE_CONFLICT:" + role)
        history_identity = json.loads(Path(v["history_identity"]["path"]).read_text())
        coverage = json.loads(Path(v["coverage"]["path"]).read_text())
        if (history_identity.get("identity_sha256") != v["projection_identity_sha256"]
                or coverage.get("identity_sha256") != v["projection_identity_sha256"]
                or coverage.get("repair_artifact") != {k: v["repair"][k] for k in ("path", "sha256")}
                or coverage.get("codes") != v["repair"]["codes"]):
            raise QfqGateError("TURNOVER_HISTORY_REPAIR_IDENTITY_CONFLICT")
        base_coverage = json.loads(_source(dict(path=coverage["base_coverage"], sha256=coverage["base_coverage_sha256"]),
                                           owner="turnover historical base coverage").read_text())
        if (base_coverage.get("identity_sha256") != v["projection_identity_sha256"] or base_coverage.get("complete") is not True
                or base_coverage.get("completed_batches") != len(v["historical_parts"])
                or base_coverage.get("total_batches") != len(v["historical_parts"])):
            raise QfqGateError("TURNOVER_HISTORY_NOT_COMPLETE")
        self.by_code = {}
        for part in v["historical_parts"]:
            _source(part, owner="turnover historical part")
            checkpoint = json.loads(_source(part["checkpoint"], owner="turnover historical checkpoint").read_text())
            if (checkpoint.get("identity_sha256") != v["projection_identity_sha256"]
                    or checkpoint.get("artifact") != {k: part[k] for k in ("path", "sha256")}
                    or checkpoint.get("symbols") != len(part["codes"])):
                raise QfqGateError("TURNOVER_HISTORY_CHECKPOINT_CONFLICT")
            for code in part["codes"]:
                if code in self.by_code or len(code) != 9 or code[-3:] not in {".SH", ".SZ", ".BJ"} or not code[:6].isdigit():
                    raise QfqGateError("TURNOVER_OVERLAY_CODE_INDEX_INVALID")
                self.by_code[code] = part
        self.cache: OrderedDict[str, dict[str, pd.DataFrame]] = OrderedDict()
        self.d28 = self._read(v["d28"], kind="d28").set_index("ts_code", drop=False)
        self.repair = self._read(v["repair"], kind="history")
        if (set(self.repair.ts_code) != set(v["repair"]["codes"]) or not set(v["repair"]["codes"]).issubset(self.by_code)
                or v["repair"].get("replacement_status") != "RAW_HISTORY_UNAVAILABLE"):
            raise QfqGateError("TURNOVER_REPAIR_SCOPE_INVALID")

    def _read(self, ref: dict, *, kind: str) -> pd.DataFrame:
        frame = pd.read_parquet(ref["path"])
        required = {"ts_code", "trade_date", "turnover_rate_pct", "turnover_float_share_10k",
                    "native_volume_shares", "volume_source", "capital_event_date", "turnover_status"}
        if not required.issubset(frame.columns) or frame.duplicated(["ts_code", "trade_date"]).any():
            raise QfqGateError("TURNOVER_OVERLAY_KEYS_OR_SCHEMA_INVALID")
        dates = pd.to_numeric(frame.trade_date, errors="coerce")
        if (not frame.ts_code.astype(str).str.fullmatch(r"[0-9]{6}\.(SH|SZ|BJ)").all()
                or dates.isna().any() or dates.lt(19000101).any() or (dates % 1 != 0).any()
                or dates.gt(self.cutoff).any() or (kind == "d28" and not dates.eq(self.cutoff).all())
                or (kind == "history" and dates.ge(self.cutoff).any())):
            raise QfqGateError("TURNOVER_OVERLAY_DATE_SCOPE_INVALID")
        rate = pd.to_numeric(frame.turnover_rate_pct, errors="coerce")
        shares = pd.to_numeric(frame.native_volume_shares, errors="coerce")
        denominator = pd.to_numeric(frame.turnover_float_share_10k, errors="coerce")
        event_date = pd.to_numeric(frame.capital_event_date, errors="coerce")
        present = rate.notna()
        expected_source = "TDX_OFFICIAL_G4DAY_NATIVE_SHARES" if kind == "d28" else "TDX_VIPDOC_ARCHIVE_FIRST_NATIVE_DAY_AS_RECORDED"
        bad = (present & (frame.turnover_status.ne("GBBQ_DATED_SNAPSHOT") | shares.isna() | shares.lt(0)
            | denominator.isna() | denominator.le(0) | event_date.isna() | event_date.lt(19000101) | event_date.gt(dates)
            | ~np.isfinite(shares) | ~np.isfinite(denominator) | ~np.isfinite(rate)
            | frame.volume_source.ne(expected_source)))
        if bad.any() or frame.turnover_status.isna().any() or (frame.turnover_status.eq("GBBQ_DATED_SNAPSHOT") & ~present).any():
            raise QfqGateError("TURNOVER_OVERLAY_VALUE_PROVENANCE_INVALID")
        if present.any() and not np.allclose(rate[present], shares[present] / (denominator[present] * 10000.0) * 100.0,
                                             rtol=1e-12, atol=1e-12):
            raise QfqGateError("TURNOVER_OVERLAY_VALUE_ARITHMETIC_INVALID")
        return frame

    def for_code(self, code: str) -> pd.DataFrame:
        frames = []
        part = self.by_code.get(code)
        if part:
            path = part["path"]
            if path not in self.cache:
                values = self._read(part, kind="history")
                if not set(values.ts_code).issubset(set(part["codes"])):
                    raise QfqGateError("TURNOVER_OVERLAY_PART_CODE_CONFLICT")
                self.cache[path] = {symbol: group.copy() for symbol, group in values.groupby("ts_code", sort=False)}
                if len(self.cache) > 8:
                    self.cache.popitem(last=False)
            self.cache.move_to_end(path)
            old = self.cache[path].get(code)
            if old is not None:
                old = old.copy()
                replacement = self.repair.loc[self.repair.ts_code.eq(code)]
                if len(replacement):
                    if (set(zip(old.ts_code, old.trade_date)) != set(zip(replacement.ts_code, replacement.trade_date))
                            or not old.turnover_status.eq("RAW_HISTORY_UNAVAILABLE").all()):
                        raise QfqGateError("TURNOVER_REPAIR_KEYS_OR_OLD_STATUS_CONFLICT:" + code)
                    old = replacement
                frames.append(old)
        if code in self.d28.index:
            frames.append(self.d28.loc[[code]])
        if not frames:
            return pd.DataFrame()
        result = pd.concat(frames, ignore_index=True)
        if result.duplicated(["ts_code", "trade_date"]).any():
            raise QfqGateError("TURNOVER_OVERLAY_DUPLICATE_COMBINED_KEY:" + code)
        return result

    def verify_sources(self) -> None:
        """No input changes between descriptor validation and output completion."""
        _source(self.ref, owner="turnover overlay descriptor after build")
        _source(self.baseline_receipt_ref, owner="turnover current baseline receipt after build")
        for role in ("selector", "backtest"):
            _source(self.value["projection_baseline_roles"][role], owner="turnover projection baseline after build " + role)
            _source(self.value["baseline_roles"][role], owner="turnover current baseline after build " + role)
        for key in ("projection_kernel", "projection_runner", "history_identity", "repair_runner",
                    "coverage", "d28", "d28_manifest", "repair"):
            _source(self.value[key], owner="turnover overlay " + key + " after build")
        for part in self.value["historical_parts"]:
            _source(part, owner="turnover historical part after build")
            _source(part["checkpoint"], owner="turnover historical checkpoint after build")
