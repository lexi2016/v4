"""Evaluate the two attached TDX XG outputs against the active, leased A-share Reader."""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import csv
from hashlib import sha256
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import sys
import time
from urllib.request import urlopen

import numpy as np
import pandas as pd
from scipy.signal import lfilter, lfilter_zi

OUT = Path(__file__).resolve().parent
MAIN = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/v4-storage-release-20261114-r1/forward/main/app")
MAIN_MANIFEST = MAIN.parent / "release-manifest.json"
LAUNCH = Path("/Users/lexi/Library/LaunchAgents/com.lexi.v4.scheduler.plist")
DOWNLOADS = Path("/Users/lexi/Downloads")
DATE = 20261113
FORMULAS = {
    "pb2_confirm": (DOWNLOADS / "已粘贴的文本 (1).txt", "f7b5f5a543325c2e681671ca23c4039cb9cf6749931eb7c262b36e77d38a2307"),
    "b23_entry": (DOWNLOADS / "已粘贴的文本.txt", "7834657819023edfbe5c77628e478c0fca996e728689b7dcc609f3a8c3254581"),
}
FUNCS = {"ABS": 1, "BARSLAST": 1, "CODELIKE": 1, "COUNT": 2, "CROSS": 2,
         "EMA": 2, "EVERY": 2, "EXIST": 2, "HHV": 2, "HHVBARS": 2, "IF": 3,
         "LLV": 2, "MA": 2, "MAX": 2, "MIN": 2, "NOT": 1, "REF": 2,
         "SMA": 3, "STD": 2, "SUM": 2}
RAW = ["open", "high", "low", "close", "volume", "amount"]
VAR_NAMES = ("O", "H", "L", "C", "V", "AMOUNT")
INPUT_NAMES = set(VAR_NAMES) | {"VOL", "DRAWNULL"}
CODE = re.compile(r"[0-9]{6}\.(?:SH|SZ|BJ)\Z")
GROUPS = {
    "pb2_confirm": "关键K回调·PB2确认",
    "b23_entry": "B2/B3入场候选",
}
ORACLE = "https://help.tdx.com.cn/gspt/docs/markdown/redword/functionlist.html"


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def hfile(path):
    with Path(path).open("rb") as handle:
        return __import__("hashlib").file_digest(handle, "sha256").hexdigest()


def checked_json(ref):
    raw = Path(ref["path"]).read_bytes()
    require(sha256(raw).hexdigest() == ref["sha256"], f"SOURCE_SHA_MISMATCH:{ref['path']}")
    return json.loads(raw)


def configure():
    cfg = plistlib.loads(LAUNCH.read_bytes())
    args = cfg["ProgramArguments"]
    env = cfg["EnvironmentVariables"]
    require(cfg.get("WorkingDirectory") == str(MAIN) or str(MAIN) in args, "MAIN_RELEASE_PATH_CHANGED")
    for key in ("V4_STORAGE_PAIR_ROOT", "V4_STORAGE_PAIR_DATA_ROOT", "V4_RESEARCH_DAILY_PRODUCT_CONFIG"):
        os.environ[key] = env[key]
    sys.path.insert(0, str(MAIN))
    return Path(env["V4_STORAGE_PAIR_DATA_ROOT"])


def parse_formula(engine, raw):
    engine.FUNCTIONS = set(FUNCS)
    nodes = {}
    formula_text = re.sub(r"\{[^}]*\}", "", raw.decode("utf-8-sig"))
    for statement in formula_text.split(";"):
        if not statement.strip():
            continue
        match = re.fullmatch(r"\s*([A-Z][A-Z0-9_]*)\s*(:=|:)\s*(.+?)\s*", statement, re.S)
        require(match is not None, f"INVALID_ASSIGNMENT:{statement[:50]}")
        name, assignment, expression = match.groups()
        require(name not in nodes and name not in INPUT_NAMES, f"DUPLICATE_ASSIGNMENT:{name}")
        require((assignment == ":") == (name == "XG"), f"UNEXPECTED_OUTPUT:{name}")
        node = engine.Parser(expression).parse()
        validate_ast(node, set(nodes) | INPUT_NAMES)
        nodes[name] = node
    require(list(nodes)[-1:] == ["XG"], "EXPECTED_ONE_FINAL_XG")
    return nodes


def validate_ast(node, known):
    kind = node[0]
    if kind == "var":
        require(node[1] in known, f"UNBOUND_VARIABLE:{node[1]}")
    if kind == "call":
        function, args = node[1:]
        require(len(args) == FUNCS[function], f"FUNCTION_ARITY:{function}")
        for arg in args:
            validate_ast(arg, known)
    if kind in ("binary", "unary"):
        for arg in node[2:]:
            validate_ast(arg, known)


def load_programs(context):
    engine = context.engine()
    programs, refs = {}, {}
    for slug, (path, expected) in FORMULAS.items():
        source = path.read_bytes()
        require(sha256(source).hexdigest() == expected, f"FORMULA_SHA_CHANGED:{path}")
        programs[slug] = parse_formula(engine, source)
        refs[slug] = {"path": str(path), "sha256": expected, "assignments": len(programs[slug]),
                      "label": GROUPS[slug], "output": "XG"}
    require(programs["pb2_confirm"]["MODE"] == ("number", "8"), "UNEXPECTED_MODE")
    return programs, refs


def logical_and(a, b):
    return np.where((a == 0) | (b == 0), 0.0, np.where(np.isnan(a) | np.isnan(b), np.nan, 1.0))


def logical_or(a, b):
    return np.where((np.isfinite(a) & (a != 0)) | (np.isfinite(b) & (b != 0)), 1.0,
                    np.where(np.isnan(a) | np.isnan(b), np.nan, 0.0))


def compare(op, a, b):
    # Guard equality comparisons such as LLV(X,20)=X against floating rounding
    # from different evaluation paths for the same value.
    eq = np.isclose(a, b, atol=1e-12, rtol=1e-13)
    values = {"=": lambda: eq, "<": lambda: (a < b) & ~eq, ">": lambda: (a > b) & ~eq,
              "<=": lambda: (a < b) | eq, ">=": lambda: (a > b) | eq}
    return np.where(np.isnan(a) | np.isnan(b), np.nan, values[op]().astype(float))


def binary(op, a, b):
    if op == "AND":
        return logical_and(a, b)
    if op == "OR":
        return logical_or(a, b)
    if op in ("=", "<", ">", "<=", ">="):
        return compare(op, a, b)
    if op == "/":
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.where(b != 0, a / b, np.nan)
    return {"+": np.add, "-": np.subtract, "*": np.multiply}[op](a, b)


class Evaluation:
    def __init__(self, program, symbol, series):
        self.program = program
        self.symbol = symbol
        self.env = dict(zip(VAR_NAMES, series.T))
        self.env["VOL"] = self.env["V"]
        self.env["DRAWNULL"] = np.nan
        self.n = len(series)
        self.index = np.arange(self.n)
        self.operations = {}

    def array(self, value):
        return np.broadcast_to(value, (self.n,))

    def last(self, name):
        return float(self.array(self.eval(("var", name)))[-1])

    def eval(self, node):
        kind, *expr = node
        if kind == "var":
            name = expr[0]
            if name not in self.env:
                self.env[name] = self.eval(self.program[name])
            return self.env[name]
        if kind == "number":
            return np.float64(expr[0])
        if kind == "text":
            return expr[0]
        if node in self.operations:
            return self.operations[node]
        if kind == "unary":
            sign, inner = expr
            result = (-1 if sign == "-" else 1) * self.eval(inner)
        elif kind == "binary":
            op, left, right = expr
            result = binary(op, self.eval(left), self.eval(right))
        else:
            function, args = expr
            result = self.call(function, [self.eval(arg) for arg in args])
        self.operations[node] = result
        return result

    def ref(self, value, offset):
        value, offset = self.array(value), self.array(offset)
        known = np.isfinite(offset)
        covered = np.where(known, offset, self.n + 1).astype(np.int64)
        require(np.all(~known | (offset == covered)), "REF_NONINTEGER")
        require(np.all(~known | (covered >= 0)), "REF_FUTURE_OFFSET")
        index = self.index - covered
        return np.where(index >= 0, value[index.clip(0)], np.nan)

    def barlast(self, flags):
        flags = self.array(flags)
        known = np.isfinite(flags)
        last = np.maximum.accumulate(np.where(known & (flags != 0), self.index, -1))
        doubt = np.maximum.accumulate(np.where(~known, self.index, -1))
        return np.where((last >= 0) & (last > doubt), self.index - last, np.nan)

    def call(self, function, args):
        if function == "CODELIKE":
            return np.float64(self.symbol.split(".")[0].startswith(args[0]))
        if function == "IF":
            condition, yes, no = args
            return np.where(np.isnan(condition), np.where(yes == no, yes, np.nan),
                            np.where(condition != 0, yes, no))
        if function == "NOT":
            return np.where(np.isnan(args[0]), np.nan, (args[0] == 0).astype(float))
        if function == "ABS":
            return np.abs(args[0])
        if function in ("MAX", "MIN"):
            return (np.maximum if function == "MAX" else np.minimum)(*args)
        if function == "REF":
            return self.ref(*args)
        if function == "BARSLAST":
            return self.barlast(args[0])
        if function == "CROSS":
            a, b = args
            return logical_and(compare(">", a, b), compare("<=", self.ref(a, 1), self.ref(b, 1)))
        values = self.array(args[0])
        period = int(args[1])
        require(period == args[1] and period > 0, f"INVALID_FIXED_PERIOD:{function}")
        if function in ("EMA", "SMA"):
            alpha = 2 / (period + 1) if function == "EMA" else args[2] / period
            known = np.isfinite(values)
            out = np.full(self.n, np.nan)
            known_values = values[known]
            if len(known_values):
                numer, denom = [alpha], [1.0, alpha - 1]
                out[known] = lfilter(numer, denom, known_values, zi=lfilter_zi(numer, denom) * known_values[0])[0]
            return out
        if function == "HHVBARS":
            result = np.full(self.n, np.nan)
            if self.n >= period:
                windows = np.lib.stride_tricks.sliding_window_view(values, period)
                result[period - 1:] = np.where(np.isfinite(windows).all(axis=1), np.argmax(windows[:, ::-1], axis=1), np.nan)
            return result
        if function in ("COUNT", "EXIST", "EVERY"):
            flags = np.where(np.isnan(values), np.nan, (values != 0).astype(float))
            window = pd.Series(flags).rolling(period, min_periods=period)
            if function == "COUNT":
                return window.sum().to_numpy()
            # Full windows only. A known witness resolves EXIST/EVERY within a
            # full window even if one intermediate calculation is unavailable.
            trues = pd.Series(flags == 1).rolling(period).sum().to_numpy()
            falses = pd.Series(flags == 0).rolling(period).sum().to_numpy()
            if function == "EXIST":
                return np.where(trues > 0, 1.0, np.where(falses == period, 0.0, np.nan))
            return np.where(falses > 0, 0.0, np.where(trues == period, 1.0, np.nan))
        window = pd.Series(values).rolling(period, min_periods=period)
        if function == "STD":
            return window.std(ddof=1).to_numpy()
        operation = {"MA": "mean", "HHV": "max", "LLV": "min", "SUM": "sum"}[function]
        return getattr(window, operation)().to_numpy()


PROGRAMS = {}


def setup_worker(programs):
    global PROGRAMS
    PROGRAMS = programs


def bool_value(value):
    return "UNKNOWN" if not np.isfinite(value) else "HIT" if value != 0 else "MISS"


def evaluate(task):
    symbol, name, exchange, days, values = task
    response = {"symbol": symbol, "name": name, "exchange": exchange, "source_date": DATE,
                "bars": len(values), "first_trade_date": int(days[0]), "status": "EVALUATED"}
    o, h, l, close, volume, amount = values[-1]
    # Affine QFQ yields legitimate negative historical prices for some long-
    # listed securities. Preserve the official numerical history for EMA/SMA.
    response["nonpositive_qfq_history_rows"] = int((values[:-1, :4] <= 0).any(axis=1).sum())
    if (not np.isfinite(values[:, :5]).all() or np.any(values[-1, :4] <= 0)
            or (values[:, 1] < values[:, 2]).any() or (values[:, 4] < 0).any()):
        response.update(status="INVALID_BOUND_HISTORY", pb2_confirm="UNKNOWN", b23_entry="UNKNOWN")
        return response, None
    first = Evaluation(PROGRAMS["pb2_confirm"], symbol, values)
    second = Evaluation(PROGRAMS["b23_entry"], symbol, values)
    pb = bool_value(first.last("XG"))
    b23 = bool_value(second.last("XG"))
    response.update(pb2_confirm=pb, b23_entry=b23)
    if "HIT" not in (pb, b23):
        return response, None
    prev = values[-2, 3] if len(values) > 1 else np.nan
    history = values[:-1, :]
    prev5 = history[-5:, 4].mean() if len(history) >= 5 else np.nan
    prior20 = history[-20:, 4].mean() if len(history) >= 20 else np.nan
    close250 = history[-250:, 3]
    raw_bars_from_anchor = first.last("N_ANC") if pb == "HIT" else np.nan
    anchor_date = int(days[-1-int(raw_bars_from_anchor)]) if np.isfinite(raw_bars_from_anchor) else None
    result = dict(response, open=o, high=h, low=l, close=close, prev_close=prev,
                  pct_chg=(close / prev - 1) * 100, volume=volume, amount=amount,
                  volume_vs_prior5=volume / prev5 if prev5 > 0 else np.nan,
                  volume_vs_prior20=volume / prior20 if prior20 > 0 else np.nan,
                  prior_250_close_percentile_pct=(close250 <= close).mean() * 100 if len(close250) else np.nan,
                  prior_250_close_n=len(close250), pb2_anchor_date=anchor_date,
                  pb2_anchor_low=first.last("K_LOW") if pb == "HIT" else np.nan,
                  pb2_j=first.last("J_VAL") if pb == "HIT" else np.nan,
                  pb2_j_threshold=first.last("J_Q20") if pb == "HIT" else np.nan,
                  b2_b3_subrole="B2" if b23 == "HIT" and second.last("B2ROLE") == 1 else "B3" if b23 == "HIT" else "",
                  b2_b3_fresh_score=second.last("FRESH") if b23 == "HIT" else np.nan,
                  b2_b3_continuation_score=second.last("CONT0") if b23 == "HIT" else np.nan,
                  b2_b3_risk_score=second.last("RISK0") if b23 == "HIT" else np.nan)
    return response, result


def make_tasks(frame, accepted):
    for symbol, block in frame.groupby("ts_code", sort=False):
        if symbol not in accepted:
            continue
        block = block.sort_values("trade_date", kind="stable")
        days = block.trade_date.to_numpy(dtype=np.int64)
        require(days[-1] == DATE and (np.diff(days) > 0).all(), f"BAD_SYMBOL_DATES:{symbol}")
        name, exchange = accepted[symbol]
        yield symbol, name, exchange, days, block[RAW].to_numpy(dtype=np.float64, na_value=np.nan)


def primitive_canary(context, programs, tasks):
    setup_worker(programs)
    cases = []
    require(len(tasks) == 3 and {task[2] for task in tasks} == {"SH", "SZ", "BJ"}, "CANARY_MARKETS")
    for task in tasks:
        code, _, _, days, series = task
        require(len(days) > 300 and days[-1] == DATE, f"CANARY_WINDOW:{code}")
        result, _ = evaluate(task)
        require(result["status"] == "EVALUATED", f"CANARY_NOT_EVALUATED:{code}")
        first = Evaluation(programs["pb2_confirm"], code, series)
        second = Evaluation(programs["b23_entry"], code, series)
        require(first.last("MODE") == 8 and first.last("XG") == first.last("G8_PB2_BUY"), "MODE_8_ORACLE")
        anchor_flags = first.array(first.eval(("var", "IS_ANCHOR")))
        prior_hits = np.flatnonzero(anchor_flags[:-1] == 1)
        require(len(prior_hits) > 0, f"CANARY_NO_ANCHOR:{code}")
        anchor = prior_hits[-1]
        require(first.last("N_ANC") == len(days) - 1 - anchor, "BARSLAST_ANCHOR_ORACLE")
        require(first.last("K_LOW") == series[anchor, 2] and first.last("K_VOL") == series[anchor, 4],
                "DYNAMIC_NESTED_REF_ORACLE")
        volume40 = series[-40:, 4]
        require(second.last("BKVOL") == 39 - np.flatnonzero(volume40 == volume40.max())[-1], "HHVBARS_ORACLE")
        j = first.array(first.eval(("var", "J_VAL")))
        expected_j_std = np.std(j[-251:-1], ddof=1)
        require(np.isclose(first.last("J_S250"), expected_j_std, rtol=1e-11), "LAGGED_SAMPLE_STD_ORACLE")
        require(second.last("XG") == float(bool(second.last("ENTRYPOOL")) and
                (bool(second.last("B2ROLE")) or (bool(second.last("B3ROLE")) and second.last("RISK0") < 45))),
                "B23_OUTPUT_ORACLE")
        for program in programs.values():
            eval1 = Evaluation(program, code, series)
            used = eval1.array(eval1.eval(("var", "XG")))
            earlier = Evaluation(program, code, series[:-1]).last("XG")
            require(np.isclose(used[-2], earlier, equal_nan=True), "D_PREFIX_CAUSALITY")
        cases.append(result)
    edge = Evaluation(programs["pb2_confirm"], "000000.SZ", np.ones((5, 6)))
    require(np.allclose(edge.barlast([0,0,1,0,0]), [np.nan,np.nan,0,1,2], equal_nan=True), "BARSLAST_NO_HIT_ORACLE")
    require(np.allclose(edge.call("HHVBARS", [np.array([1,2,2,1,2]), 3]),
                        [np.nan,np.nan,0,1,0], equal_nan=True), "HHVBARS_LATEST_TIE_ORACLE")
    require(np.isnan(edge.ref(np.arange(5.0), 1)[0]), "PREHISTORY_REF_ORACLE")
    return cases


def save_csv(path, rows):
    pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8-sig", float_format="%.12g")


def save_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def workbench_identity(context):
    url = "http://127.0.0.1:8873/api/v4/research/workbench/days/2026-11-13"
    with urlopen(url, timeout=8) as response:
        day = json.load(response)
    require(day["source_date"] == "2026-11-13" and day["observation_date"] == "2026-11-16",
            "WORKBENCH_D_O_CONFLICT")
    require((day["generation"], day["input_sha256"], day["source_selector_sha256"])
            == (context.generation, context.identity["input_sha256"],
                context.identity["selector_artifact_sha256"]), "WORKBENCH_SOURCE_CONFLICT")
    manifest = checked_json(day["numeric_manifest"])
    require(manifest["source_generation"] == context.generation and
            manifest["input_sha256"] == context.identity["input_sha256"], "WORKBENCH_MANIFEST_CONFLICT")
    return day["numeric_manifest"]


def main():
    arg = argparse.ArgumentParser(description=__doc__)
    arg.add_argument("--canary", action="store_true")
    arg.add_argument("--workers", type=int, default=12)
    options = arg.parse_args()
    require(1 <= options.workers <= 14, "BOUNDED_WORKERS_REQUIRED")
    require(shutil.disk_usage(OUT).free >= 100 * 1024 ** 2, "DISK_SPACE_TOO_LOW")
    started = time.monotonic()
    data = configure()
    from ops.research_storage_pair import request_binding
    from ops.research_panel_daily_product import SourceContext
    with request_binding(data) as pair:
        require(pair is not None, "AUTHORIZED_PAIR_LEASE_REQUIRED")
        context = SourceContext(data, DATE)
        board_manifest = workbench_identity(context)
        programs, refs = load_programs(context)
        print(f"Source generation {context.generation}, universe {len(context.scope)}", flush=True)
        require(all(CODE.fullmatch(c) for c in context.scope), "ORIGINAL_A_SCOPE_NOT_EXACT")
        require(hfile(context.panel) == pair.manifest["roles"]["selector"]["sha256"], "SELECTOR_ANCHOR_SHA")
        require(hfile(pair.paths["backtest"]) == pair.manifest["roles"]["backtest"]["sha256"], "BACKTEST_ANCHOR_SHA")
        require(hfile(context.receipt_ref["path"]) == pair.manifest["roles"]["selector"]["producer_receipt"]["sha256"],
                "PRODUCER_RECEIPT_SHA")
        quarantine = context.quarantine.get("reasons", {})
        scope = sorted(set(context.scope) - set(quarantine))
        canary_scope = ["600000.SH", "000001.SZ", "920239.BJ"]
        columns = ["market_type", "exchange", "name", *RAW]
        if options.canary:
            scope = canary_scope
        # Name/market are needed, but only once per D row. Read D keys first,
        # then project numeric history for the authorized D-bar securities.
        reader = context.reader.load_selector_ready
        dated = reader(columns=columns[:3], ts_codes=scope, start_date=str(DATE),
                       end_date=str(DATE), panel_path=context.panel)
        require(not dated.ts_code.duplicated().any(), "D_KEY_DUPLICATED")
        accepted = {r.ts_code: (r.name.strip() if isinstance(r.name, str) and r.name.strip() else None, r.exchange)
                    for r in dated.itertuples(index=False)
                    if r.market_type in {"A_SHARE","BJ"} and r.exchange == r.ts_code[-2:]}
        require(len(accepted) == len(dated), "D_MARKET_IDENTITY_MISMATCH")
        target_count = context.receipt["counts"]["selector"]["target_date_symbols"]
        if not options.canary:
            require(len(accepted) == target_count, f"DATED_COVERAGE_MISMATCH:{len(accepted)}!={target_count}")
        frame = reader(columns=RAW, ts_codes=sorted(accepted), end_date=str(DATE), panel_path=context.panel)
        print(f"Reader returned {len(frame)} rows for {len(accepted)} D securities", flush=True)
        if options.canary:
            cases = primitive_canary(context, programs, list(make_tasks(frame, accepted)))
            save_json(OUT / "CANARY.json", {"status": "PASS", "cases": cases, "identity": context.identity,
                      "validation": ["MODE8", "BARSLAST", "NESTED_DYNAMIC_REF", "LAGGED_STD", "HHVBARS",
                                     "HHVBARS_LATEST_TIE", "PREHISTORY", "B2_B3_FINAL_GATE", "PREFIX_CAUSALITY"],
                      "elapsed_seconds": round(time.monotonic() - started, 3)})
            context.unchanged()
            print("Canary PASS", flush=True)
            return
        require(json.loads((OUT/"CANARY.json").read_text())["identity"] == context.identity, "CANARY_BINDING_DRIFT")
        batches, hit_rows = [], []
        with ProcessPoolExecutor(max_workers=options.workers, initializer=setup_worker, initargs=(programs,)) as pool:
            for status, hit in pool.map(evaluate, make_tasks(frame, accepted), buffersize=28):
                batches.append(status)
                if hit is not None:
                    hit_rows.append(hit)
                if len(batches) % 500 == 0:
                    print(f"{len(batches)}/{len(accepted)} evaluated, {len(hit_rows)} union hits", flush=True)
        require({r["symbol"] for r in batches} == set(accepted) and len(batches) == len(accepted),
                "PROJECTION_COVERAGE_MISMATCH")
        for symbol in sorted(set(context.scope) - set(accepted)):
            batches.append({"symbol": symbol, "exchange": symbol[-2:], "source_date": DATE,
                "status": "SOURCE_QUARANTINED" if symbol in quarantine else "D_BAR_NOT_AVAILABLE",
                "source_reason": quarantine.get(symbol, {}).get("reason"),
                "pb2_confirm": "UNKNOWN", "b23_entry": "UNKNOWN"})
        context.unchanged()
        group_counts = {slug: sum(r[slug] == "HIT" for r in hit_rows) for slug in GROUPS}
        for hit in hit_rows:
            hit["groups"] = "|".join(slug for slug in GROUPS if hit[slug] == "HIT")
            hit["group_names"] = "|".join(GROUPS[slug] for slug in GROUPS if hit[slug] == "HIT")
            hit["source_observation_date"] = "2026-11-16"
            hit["generation"] = context.generation
            hit["input_sha256"] = context.identity["input_sha256"]
            hit["numeric_manifest_sha256"] = board_manifest["sha256"]
            hit["producer_receipt_sha256"] = context.receipt_ref["sha256"]
            hit["source_selector_sha256"] = context.identity["selector_artifact_sha256"]
            hit["price_basis"] = context.identity["basis"]["price_basis"]
            hit["volume_basis"] = context.identity["basis"]["volume_basis"]
            hit["amount_basis"] = context.identity["basis"]["amount_basis"]
        for row in (hit_rows, batches):
            row.sort(key=lambda entry: entry["symbol"])
        save_csv(OUT/"CANDIDATES.csv", hit_rows)
        save_csv(OUT/"UNIVERSE_AUDIT.csv", batches)
        for slug in GROUPS:
            save_csv(OUT/f"{slug}.csv", [r for r in hit_rows if r[slug] == "HIT"])
        meta = dict(status="RESEARCH_PROJECTION_COMPLETE", source_date=DATE, observation_date="2026-11-16",
                    formula_native_TDX_parity="CANNOT_CONFIRM", groups=GROUPS, group_counts=group_counts,
                    universe=len(batches), d_bars=len(accepted), accepted_target_count=target_count,
                    union=len(hit_rows), overlap=sum(all(r[slug] == "HIT" for slug in GROUPS) for r in hit_rows),
                    statuses=dict(Counter(r["status"] for r in batches)),
                    formula_statuses={slug:dict(Counter(r[slug] for r in batches)) for slug in GROUPS},
                    identity=context.identity, generation_pair=pair.manifest, numeric_manifest=board_manifest,
                    producer_receipt=context.receipt_ref,
                    source_config=context.config_ref, formula_refs=refs, parser=context.config["engine"],
                    release_manifest=str(MAIN_MANIFEST), release_manifest_sha256=hfile(MAIN_MANIFEST),
                    projection_code_sha256=hfile(Path(__file__)), python=sys.executable,
                    elapsed_seconds=round(time.monotonic()-started,3), workers=options.workers,
                    evaluation_semantics={"reference": ORACLE, "history": "full retained D-truncated history",
                      "rows": "actual observed trading bars; historical nonpositive affine QFQ rows preserved",
                      "STD": "sample ddof=1",
                      "EMA_SMA_seed": "first valid observation",
                      "REF": "explicit in-bounds backward indexing; unavailable prehistory is UNKNOWN",
                      "HHVBARS": "nearest equal high", "BARSLAST": "UNKNOWN before first known match",
                      "windows": "full windows required, unavailable terms are UNKNOWN",
                      "numeric_comparison": "float64 atol=1e-12 rtol=1e-13 for equality/strict boundary comparisons"},
                    RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
        meta["files"] = {p.name: {"size":p.stat().st_size,"sha256":hfile(p)} for p in
                         [OUT/"CANARY.json", OUT/"CANDIDATES.csv", OUT/"UNIVERSE_AUDIT.csv",
                          *(OUT/f"{slug}.csv" for slug in GROUPS)]}
        save_json(OUT/"RESULT.json", meta)
        print(json.dumps({k:meta[k] for k in ("group_counts","universe","d_bars","union","overlap","statuses",
                                               "formula_statuses","elapsed_seconds")}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
