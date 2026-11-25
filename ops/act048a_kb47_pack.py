"""ACT-048A only: group, allocate and seal entirely D-only research review windows."""
import argparse
import csv
import io
import json
import math
import re
import secrets
import time
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

from ops import act047a_kb47_audit as audit
from ops import act048a_kb47_precompute as pre

SEED = 20261125
DEV_LAST = 20231229
EMBARGO = 5
MAX_FILE = 8_500_000
FOCUS = (5, 11, 14, 17, 21, 22, 25, 24)
HIGH = (16, 19, 20, 26, 29)
GROUPS = (*FOCUS, "HIGH_FREQ", "CROSS")
TIERS = ("strong", "gray", "hard")
RISKS = ("HIGH_POSITION", "PSEUDO_REPAIR", "OLD_ANCHOR_UNRECLAIMED")
WAVE1 = "ACT048A_BATCH2_WAVE1_60_BLIND_20261125.zip"
WAVE2 = "ACT048A_BATCH2_WAVE2_180_BLIND_20261125.zip"
MANIFEST = "ACT048A_BATCH2_240_ESCROW_MANIFEST_20261125.json"
RECORD = ("anon_id", "window_bar_count", "warmup_bar_count")
BARS = ("anon_id", "relative_bar", "relative_market_session", *pre.PRICE,
        "volume", "j", "k", "kdj")
CARD = ("anon_id", "white", "yellow", "white_minus_yellow", "white_distance_atr",
        "gap_pct", "body_pct", "range_pct", "upper_shadow_pct", "upper_range_fraction",
        "close_above_white_count20", "white_known_count20", "close_above_white_fraction20",
        "f08_long21", "f08_short3", "f05_high20", "f05_close_minus_high20", "f05_volume_ratio_prev",
        "f05_return_pct", "f05_recent_count8", "dif_D", "dea_D", "dif_prev", "dea_prev",
        "f09_spread_D", "f09_spread_prev", "fixed_anchor_low", "fixed_anchor_offset",
        "fixed_anchor_close_minus", "d_offset", "t_offset", "c_offset")
CARD_PRICE = frozenset(("white", "yellow", "white_minus_yellow", "f05_high20", "f05_close_minus_high20",
                        "dif_D", "dea_D", "dif_prev", "dea_prev", "f09_spread_D", "f09_spread_prev",
                        "fixed_anchor_low", "fixed_anchor_close_minus"))
SCHEMAS = {"records.csv": RECORD, "trailing_bars.csv": BARS, "review_cards.csv": CARD}
require = pre.require


def methods(row):
    return set(row["methods"]) | set(row["old_methods"])


def security_day(row):
    return row["ts_code"], row["trade_date"]


class Episodes:
    def __init__(self):
        self.parent = {}

    def root(self, item):
        parent = self.parent.setdefault(item, item)
        if item != parent:
            self.parent[item] = self.root(parent)
        return self.parent[item]

    def union(self, one, two):
        a, b = sorted((self.root(one), self.root(two)))
        self.parent[b] = a


def episode_pool(rows, exposed):
    groups = Episodes()
    prior = {}
    anchors = {}
    previous_sessions = defaultdict(list)
    exposure_keys = {security_day(r) for r in exposed}
    require(len(exposure_keys) == len(exposed), "DUPLICATE_EXPOSURE")
    for row in exposed:
        previous_sessions[row["ts_code"]].append(row["session"])
    for row in sorted([*rows, *exposed], key=security_day):
        key = security_day(row)
        code, _ = key
        session = row["session"]
        groups.root(key)
        for method in sorted(methods(row)):
            tag = (code, method)
            if tag in prior and session - prior[tag][0] <= 5:
                groups.union(key, prior[tag][1])
            prior[tag] = (session, key)
        # Only anchors that were already present strictly before the signal D can group
        # dates. A newly created D anchor cannot retrospectively merge its own trigger.
        for anchor in row["wave"]:
            tag = (code, anchor)
            if tag in anchors:
                groups.union(key, anchors[tag])
            anchors[tag] = key
    exposed_episodes = {groups.root(key) for key in exposure_keys}
    result = []
    reasons = Counter()
    for row in rows:
        key = security_day(row)
        ep = groups.root(key)
        if ep in exposed_episodes:
            reasons["known_same_episode"] += 1
        elif any(abs(row["session"] - s) <= 5 for s in previous_sessions[row["ts_code"]]):
            # Across directly adjacent reviewed stock days, neither sparse flags nor absent
            # anchor metadata demonstrate a separate wave.
            reasons["stock_session_within_5_of_exposure"] += 1
        elif row["window_bars"] != 60:
            reasons["incomplete_60_bars"] += 1
        else:
            result.append(dict(row, episode=ep))
    reasons.update(remaining_rows=len(result), independent_episodes=len({r["episode"] for r in result}),
                   prior_reviewed_keys=len(exposure_keys))
    return result, dict(reasons)


def risk_buckets(row):
    allowed = []
    if row["high_refutation"] is True:
        allowed.append(RISKS[0])
    if 25 in methods(row) and (row["old_anchor_below"] is True or
            row["m25_repair_clock"] == "FALSE" and row["d_offset"] is not None and row["t_offset"] is None):
        allowed.append(RISKS[1])
    if row["old_anchor_below"] is True:
        allowed.append(RISKS[2])
    return tuple(allowed)


def quotas(group):
    return (12, 9, 3) if group == "CROSS" else (12, 7, 5)


def sample_options(rows, cutoff_session):
    import hashlib

    cells = defaultdict(list)
    for row in rows:
        fold = ("dev" if row["session"] <= cutoff_session else
                "holdout" if row["first_session"] > cutoff_session + EMBARGO else None)
        if fold is None:
            continue
        active = methods(row)
        candidates = [m for m in FOCUS if m in active]
        if active.intersection(HIGH):
            candidates.append("HIGH_FREQ")
        candidates.append("CROSS")
        risks = risk_buckets(row)
        # Each is a sampling fact. Isolated upper-wick/distance observations, close at
        # or below W, and W not supported by a majority of the last 20 known closes
        # identify gray comparators. None is a tactic gate or a gold/reject label.
        isolated_r3 = ((row["upper_range_fraction"] or 0) >= .45 or
                       (row["white_distance_atr"] or 0) >= 3.5)
        limited_white_support = (row["white_known_count20"] != 20 or
                                 row["close_above_white_count20"] * 2 <= 20 or
                                 row["white_distance_atr"] is None or row["white_distance_atr"] <= 0)
        tier = ("hard" if risks else "strong" if row["w_gt_y"] is True and
                row["old_anchor_below"] is False and not (isolated_r3 or limited_white_support)
                else "gray")
        for group in candidates:
            for risk in risks or ("",):
                key = (fold, group, tier, risk, row["ts_code"])
                rank = hashlib.sha256(f"{SEED}:{group}:{tier}:{risk}:{security_day(row)}".encode()).digest()
                cells[key].append((rank, row))
    options = []
    raw_counts = {}
    for (fold, group, tier, risk, _code), rank_rows in cells.items():
        raw_counts.setdefault((fold, group, tier), set()).update(
            r["episode"] for _, r in rank_rows)
        seen = set()
        # One representative per episode per cell. Preserve the full independent inventory
        # for the sign-off and let allocation decide the representative among other cells.
        for rank, row in sorted(rank_rows, key=lambda item: item[0]):
            if row["episode"] in seen:
                continue
            seen.add(row["episode"])
            options.append(dict(row=row, fold=fold, group=group, tier=tier, risk=risk, rank=rank))
    return options, {"|".join(map(str,k)): len(v) for k,v in raw_counts.items()}


def choose(options):
    """Solve a fixed quota allocation. Partial optima cannot exceed any requested bucket."""
    import numpy as np
    from scipy.optimize import Bounds, LinearConstraint, milp
    from scipy.sparse import coo_matrix

    if not options:
        return [], {"status": "EMPTY", "max_count_proven": True}
    rule_indices = {}
    capacities = []
    ii, jj = [], []

    def attach(rule, capacity, col):
        if rule not in rule_indices:
            rule_indices[rule] = len(capacities)
            capacities.append(capacity)
        ii.append(rule_indices[rule])
        jj.append(col)

    for col, item in enumerate(options):
        row, group, fold, tier, risk = (item[k] for k in ("row", "group", "fold", "tier", "risk"))
        tier_no = TIERS.index(tier)
        # Every family has total Dev/Holdout quota of 18/6. Tier counts are pooled over
        # both folds so date shifts of tier inventory do not create artificial shortages.
        attach(("fold", group, fold), 18 if fold == "dev" else 6, col)
        attach(("tier", group, tier), quotas(group)[tier_no], col)
        attach(("episode", row["episode"]), 1, col)
        attach(("stock_cap", group, row["ts_code"]), 6, col)
        if risk:
            attach(("risk", risk), 16, col)
    matrix = coo_matrix((np.ones(len(ii)), (ii, jj)), shape=(len(capacities), len(options))).tocsc()
    # Secondary seeded tie preference is bounded to <1 across 240 slots.
    weights = np.array([-1 + int.from_bytes(item["rank"][:3], "big") / (2**24 * 300)
                        for item in options])
    result = milp(weights, integrality=np.ones(len(options)), bounds=Bounds(0, 1),
                  constraints=LinearConstraint(matrix, -np.inf, np.asarray(capacities)),
                  options={"time_limit": 45, "mip_rel_gap": 0.004})
    picks = [] if result.x is None else [item for item, x in zip(options, result.x) if x > .5]
    status = int(result.status)
    bound = getattr(result, "mip_dual_bound", None)
    proven = len(picks) == 240 or (bound is not None and math.isfinite(bound) and
                                  math.floor(-bound + 0.81) <= len(picks))
    return picks, {"status": status, "max_count_proven": bool(proven), "options": len(options)}


def choose_wave1(picks):
    dev = [x for x in picks if x["fold"] == "dev"]
    first = []
    remaining = defaultdict(list)
    for x in sorted(dev, key=lambda x: x["rank"]):
        remaining[x["group"]].append(x)
    # Reserve one of each available hard risk before allocating the six seats per family.
    for risk in RISKS:
        opts = [x for x in dev if x["risk"] == risk]
        if opts:
            item = min(opts, key=lambda x: x["rank"])
            first.append(item)
            remaining[item["group"]].remove(item)
    for group in GROUPS:
        block = [x for x in first if x["group"] == group]
        for tier, target in zip(TIERS, (3, 2, 1)):
            need = max(0, min(6-len(block), target-sum(x["tier"] == tier for x in block)))
            add = [x for x in remaining[group] if x["tier"] == tier][:need]
            block.extend(add)
            first.extend(add)
            for x in add:
                remaining[group].remove(x)
        first.extend(remaining[group][:6-len(block)])
        del remaining[group][:6-len(block)]
    if len(first) < 60:
        fill = sorted((x for rest in remaining.values() for x in rest), key=lambda x: x["rank"])
        first.extend(fill[:60-len(first)])
    first_ids = {security_day(x["row"]) for x in first}
    return first, [x for x in picks if security_day(x["row"]) not in first_ids]


def cross_pairs(picks):
    from scipy.optimize import linear_sum_assignment

    block = [x for x in picks if x["group"] == "CROSS"]
    pos = [x for x in block if x["tier"] == "strong"]
    other = [x for x in block if x["tier"] != "strong"]
    if not pos or not other:
        return []
    priority = [[4*bool(methods(a["row"]) & methods(b["row"])) + (a["fold"] == b["fold"])
                 for b in other] for a in pos]
    lhs, rhs = linear_sum_assignment(priority, maximize=True)
    return [(pos[i], other[j], priority[i][j] >= 4) for i,j in zip(lhs,rhs)]


def f05_observation(window):
    """ACT-045B §1/L29–31, on the same-basis actual-bar chart projection."""
    if len(window) < 28:
        return None, None
    recent = []
    returns = []
    for i in range(len(window) - 8, len(window)):
        before, day = window[i-1:i+1]
        ret = 100 * (day["close"] / before["close"] - 1)
        high20 = max(bar["high"] for bar in window[i-20:i])
        recent.append(day["close"] > high20 and day["volume"] > .8 * before["volume"] and ret > 4)
        returns.append(ret)
    return returns[-1], sum(recent)


def projection(item, window, anonymous):
    row = item["row"]
    require(len(window) == pre.N and window[-1]["session"] == 0 and
            row["session"] + window[0]["session"] == row["first_session"], "CANONICAL_REPLAY_DRIFT")
    base_price, base_volume = window[-1]["close"], window[-1]["volume"]
    require(pre.positive(base_price) and pre.positive(base_volume), "NONPOSITIVE_ANONYMIZING_BASE")
    rec = dict(anon_id=anonymous, window_bar_count=len(window), warmup_bar_count=row["warmup"])
    bars = []
    for bar_index, bar in enumerate(window, 1-pre.N):
        bars.append(dict(anon_id=anonymous, relative_bar=bar_index, relative_market_session=bar["session"],
                         **{field: pre.divide(bar[field], base_price) for field in pre.PRICE},
                         volume=bar["volume"]/base_volume, j=bar["j"], k=bar["k"], kdj=bar["kdj"]))
    card = {field: (pre.divide(row[field], base_price) if field in CARD_PRICE else row[field])
            for field in CARD if field not in ("anon_id", "f05_recent_count8")}
    card["f05_return_pct"], card["f05_recent_count8"] = f05_observation(window)
    card["anon_id"] = anonymous
    return rec, bars, card


def csv_bytes(schema, rows):
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=schema, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({k: (format(v, ".12g") if isinstance(v, float) else v) for k,v in row.items()})
    return buffer.getvalue().encode("ascii")


def archive(cases):
    rec, bars, card = [], [], []
    for r, bb, c in sorted(cases, key=lambda item: item[0]["anon_id"]):
        rec.append(r)
        bars.extend(bb)
        card.append(c)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for (name, schema), table in zip(SCHEMAS.items(), (rec, bars, card)):
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            z.writestr(info, csv_bytes(schema, table), compress_type=zipfile.ZIP_DEFLATED, compresslevel=6)
    return buffer.getvalue()


def validate_archive(data, expected):
    tables = {}
    pattern = re.compile(r"Z[0-9A-F]{24}")
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        require(tuple(z.namelist()) == tuple(SCHEMAS) and z.testzip() is None, "ZIP_BOUNDARY")
        for name, schema in SCHEMAS.items():
            text = z.read(name).decode("ascii")
            reader = csv.reader(io.StringIO(text))
            require(tuple(next(reader)) == schema, "BLIND_SCHEMA")
            rows = []
            for values in reader:
                require(len(values) == len(schema) and pattern.fullmatch(values[0]), "BLIND_ID_OR_ROW")
                numbers = [float(v) if v != "" else None for v in values[1:]]
                require(all(v is None or math.isfinite(v) for v in numbers), "NONNUMERIC_BLIND_FIELD")
                rows.append(dict(zip(schema, [values[0], *numbers])))
            tables[name] = rows
    records = tables["records.csv"]
    keys = {r["anon_id"] for r in records}
    require(len(keys) == len(records) == expected, "BLIND_CASE_COUNT")
    require(all(r["window_bar_count"] == pre.N and r["warmup_bar_count"] >= 114 for r in records),
            "WINDOW_OR_WARMUP_DRIFT")
    bars = defaultdict(list)
    for row in tables["trailing_bars.csv"]:
        bars[row["anon_id"]].append(row)
    require(set(bars) == keys, "BLIND_BAR_KEYS")
    for day_bars in bars.values():
        offsets = [b["relative_market_session"] for b in day_bars]
        require([b["relative_bar"] for b in day_bars] == list(range(1-pre.N, 1)) and
                offsets == sorted(set(offsets)) and offsets[-1] == 0 and
                all(v.is_integer() and v <= 0 for v in offsets), "BAD_BAR_CLOCK")
        require(all(all(pre.positive(b[k]) for k in ("open", "high", "low", "close", "volume"))
                    for b in day_bars), "INVALID_BAR_FACT")
    cards = tables["review_cards.csv"]
    require({r["anon_id"] for r in cards} == keys and len(cards) == len(keys), "BLIND_CARD_KEYS")
    for c in cards:
        require(c["fixed_anchor_offset"] is None or c["fixed_anchor_offset"] < 0, "NON_PRIOR_FIXED_ANCHOR")
        indices = [c[key] for key in ("d_offset", "t_offset", "c_offset") if c[key] is not None]
        require(indices == sorted(set(indices)) and all(x <= 0 and x in
                    [b["relative_market_session"] for b in bars[c["anon_id"]]] for x in indices), "NONCAUSAL_CARD_CLOCK")
    return keys


def audit_picks(picks, wave1, exposed, cutoff_session):
    rows = [x["row"] for x in picks]
    keys = {security_day(r) for r in rows}
    require(len(keys) == len({r["episode"] for r in rows}) == len(rows), "BATCH2_EPISODE_DUPLICATE")
    require(not keys.intersection(map(security_day, exposed)), "PRIOR_SECURITY_DAY_LEAK")
    exposed_sessions = defaultdict(list)
    for row in exposed:
        exposed_sessions[row["ts_code"]].append(row["session"])
    require(not any(abs(r["session"]-s) <= EMBARGO for r in rows for s in exposed_sessions[r["ts_code"]]),
            "REVIEWED_SESSION_NEIGHBOR_LEAK")
    by_fold = {fold: [x["row"] for x in picks if x["fold"] == fold] for fold in ("dev", "holdout")}
    dev, holdout = by_fold["dev"], by_fold["holdout"]
    require(all(r["session"] <= cutoff_session for r in dev), "DEV_CUTOFF")
    require(all(r["first_session"] > cutoff_session + EMBARGO for r in holdout), "HOLDOUT_WINDOW_EMBARGO")
    nearest_signals = min((b["session"]-a["session"] for a in dev for b in holdout), default=None)
    nearest_windows = min((b["first_session"]-a["session"] for a in dev for b in holdout), default=None)
    require(all(x["fold"] == "dev" for x in wave1), "HOLDOUT_IN_WAVE1")
    risk = Counter(x["risk"] for x in picks if x["risk"])
    require(all(n <= 16 for n in risk.values()) and sum(risk.values()) == sum(x["tier"]=="hard" for x in picks),
            "BAD_HARD_RISK_QUOTAS")
    group_stats = {}
    for group in GROUPS:
        block = [x for x in picks if x["group"] == group]
        counts = Counter(x["tier"] for x in block)
        stock = Counter(x["row"]["ts_code"] for x in block)
        dev_n = sum(x["fold"] == "dev" for x in block)
        holdout_n = len(block)-dev_n
        targets = dict(zip(TIERS, quotas(group)))
        require(dev_n <= 18 and holdout_n <= 6 and max(stock.values(), default=0) <= 6 and
                all(counts[t] <= targets[t] for t in TIERS), "QUOTA_OVERFLOW")
        group_stats[str(group)] = dict(total=len(block), dev=dev_n, holdout=holdout_n, stocks=len(stock),
            maximum_one_stock=max(stock.values(), default=0), strong=counts["strong"],
            gray=counts["gray"], hard=counts["hard"], deficits={t: targets[t]-counts[t] for t in TIERS})
    return dict(total=len(rows), dev=len(dev), holdout=len(holdout), wave1=len(wave1),
                wave2=len(rows)-len(wave1), unresolved_target=240-len(rows),
                nearest_signal_gap_sessions=nearest_signals, nearest_window_gap_sessions=nearest_windows,
                fold_signal_dates={k: [min(r["trade_date"] for r in v), max(r["trade_date"] for r in v)]
                                   if v else [] for k,v in by_fold.items()},
                board_counts=dict(Counter(str(r["board"]) for r in rows)),
                board_epoch_counts=dict(Counter(str(r["board_epoch"]) for r in rows)),
                decade_counts=dict(Counter(str(r["trade_date"]//100000*10) for r in rows)),
                hard_risk_actual={k:risk[k] for k in RISKS},
                hard_risk_deficit={k:16-risk[k] for k in RISKS},
                wave1_groups=dict(Counter(str(x["group"]) for x in wave1)),
                wave1_risks=dict(Counter(x["risk"] for x in wave1 if x["risk"])),
                groups=group_stats)


def load_pool(paths, root):
    import pyarrow.parquet as pq

    receipt = json.loads((paths/"precompute_receipt.json").read_text())
    cache = paths/"skeleton_cache.parquet"
    exposure = paths/"prior_exposure.json"
    require(receipt["d_after_files"] == 0 and pre.file_sha(cache) == receipt["cache_sha256"] and
            pre.file_sha(exposure) == receipt["previous_exposure_sha256"], "PRECOMPUTE_SEAL_DRIFT")
    env = pre.setup(root)
    pre.init_worker(env)
    require(receipt["source_generation"] == env["generation"], "INPUT_GENERATION_DRIFT")
    rows = pq.read_table(cache).to_pylist()
    previous = json.loads(exposure.read_text())
    require(len(rows) == 33875 and len({security_day(r) for r in rows}) == len(rows) and
            {security_day(r) for r in previous} == env["excluded"], "INVENTORY_OR_CUSTODY_DRIFT")
    return receipt, env, rows, previous


def run(root, private, output, dry_run=False):
    import hashlib

    t0 = time.perf_counter()
    private = pre.private_dir(private.resolve())
    out = output.resolve()
    require(not (out == private or out.is_relative_to(private)), "PUBLIC_OUTPUT_UNDER_ESCROW")
    receipt, env, rows, exposed = load_pool(private, root)
    t_loaded = time.perf_counter()
    position = env["position"]
    pool, grouping = episode_pool(rows, exposed)
    options, inventory = sample_options(pool, position[DEV_LAST])
    picks, allocation = choose(options)
    wave1, wave2 = choose_wave1(picks)
    paired = cross_pairs(picks)
    blocks = audit_picks(picks, wave1, exposed, position[DEV_LAST])
    blocks.update(cross_pairs=len(paired), cross_shared_method_pairs=sum(same for _,_,same in paired),
                  cross_same_split_pairs=sum(a["fold"] == b["fold"] for a,b,_ in paired))
    data = dict(**audit.FLAGS, d_after_files=0, source_generation=env["generation"],
                seed=SEED, dev_last_signal=DEV_LAST, min_embargo_market_sessions=EMBARGO,
                cache_sha256=receipt["cache_sha256"], previous_exposure_sha256=receipt["previous_exposure_sha256"],
                source_cutoff=env["cutoff"], inventory=inventory, grouping=grouping, allocation=allocation,
                sample=blocks, window_policy="actual valid bars, unverified basis broken, session gaps retained",
                pack_load_s=t_loaded-t0, pack_sample_s=time.perf_counter()-t_loaded)
    if dry_run:
        return data
    require(picks and wave1 and wave2, "NO_REVIEWABLE_RELEASE")
    out.mkdir(parents=True, exist_ok=True)
    storage = defaultdict(list)
    for wave_no, block in enumerate((wave1,wave2), 1):
        for item in block:
            storage[item["row"]["ts_code"]].append((wave_no,item))
    t_render = time.perf_counter()
    by_wave = defaultdict(list)
    identifiers = {}
    mapping = []
    for code, block in sorted(storage.items()):
        _, _, bars, ordinal, links = pre.stock_state(code,env)
        for wave_no, item in block:
            row = item["row"]
            key = security_day(row)
            anon = "Z"+secrets.token_hex(12).upper()
            identifiers[key] = anon
            window = pre.crop(bars,links,ordinal[row["trade_date"]],position)
            by_wave[wave_no].append(projection(item,window,anon))
            mapping.append(dict(anon_id=anon, ts_code=code, trade_date=row["trade_date"], episode=row["episode"],
                                fold=item["fold"], wave=wave_no, bucket=item["group"], tier=item["tier"],
                                primary_risk=item["risk"], all_risks=risk_buckets(row), methods=sorted(methods(row))))
    second = archive(by_wave[2])
    trays = [(WAVE1, archive(by_wave[1]), len(wave1))]
    if len(second) <= MAX_FILE:
        trays.append((WAVE2, second, len(wave2)))
    else:
        midpoint = (len(wave2)+1)//2
        shuffled = sorted(by_wave[2], key=lambda c: c[0]["anon_id"])
        for i, cases in enumerate((shuffled[:midpoint], shuffled[midpoint:]),1):
            trays.append((WAVE2.removesuffix(".zip")+f"_PART{i}.zip",archive(cases),len(cases)))
    released = set()
    tray_receipts = {}
    for name, raw, count in trays:
        require(len(raw) <= MAX_FILE, "BLIND_FILE_TOO_LARGE")
        identities = validate_archive(raw,count)
        require(not released.intersection(identities), "BLIND_ID_CROSS_TRAY")
        released.update(identities)
        tray_receipts[name] = dict(sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw), cases=count,
                                  bars=count*pre.N)
    require(released == set(identifiers.values()) and len(released) == len(picks), "BLIND_MAPPING_RECONCILIATION")
    mapping_path = private/"escrow_mapping.json"
    planned = [mapping_path, *(out/name for name,_,_ in trays), out/MANIFEST]
    require(all(not p.exists() and not p.is_symlink() for p in planned), "REFUSING_TO_REPLACE_EXISTING_PACKAGE")
    escrow = dict(assignments=sorted(mapping,key=lambda x:x["anon_id"]), pairs=[
        dict(positive=identifiers[security_day(a["row"])], gray_or_hard=identifiers[security_day(b["row"])],
             same_method=same) for a,b,same in paired])
    pre.private_write(mapping_path,json.dumps(escrow,ensure_ascii=True,indent=2).encode())
    require(mapping_path.stat().st_mode & 0o077 == 0, "ESCROW_MAP_PERMISSIONS")
    for name,raw,_ in trays:
        with (out/name).open("xb") as f:
            f.write(raw)
        require(pre.file_sha(out/name)==tray_receipts[name]["sha256"], "WRITE_CHECKSUM_MISMATCH")
    data.update(pack_render_verify_s=time.perf_counter()-t_render, pack_wall_s=time.perf_counter()-t0,
                blind_trays=tray_receipts, private_mapping_sha256=pre.file_sha(mapping_path),
                leakage_checks={"exact_member_allowlist": True, "exact_csv_schema": True,
                    "opaque_identifiers_numeric_other_fields": True, "causal_clock": True,
                    "cross_tray_identity_uniqueness": True, "identity_split_and_buckets_in_private_only": True},
                chart_units="per-case D-close price units and D-volume volume units; percentage/relative facts unchanged",
                f05_chart_observation="F05 count8 uses same-basis reconstructed chart preceding actual-bar close, "
                    "preceding-bar volume and previous twenty highs (ACT-045B §1). Frozen F05 remains unchanged.",
                risk_windows="R3 high-open negative candle or combined .45 upper/3.5 ATR; "
                    "repair proxy plus confirmed old-anchor breach or known damage without independent t; "
                    "old fixed low breach. Strong requires W>Y, known unbroken prior fixed low, "
                    "D close above W, W supported by a majority of known last twenty closes, no isolated R3 cues. "
                    "All are pre-label sample strata only.")
    encoded = json.dumps(data, ensure_ascii=False,indent=2).encode()
    require(len(encoded) <= MAX_FILE, "MANIFEST_TOO_LARGE")
    with (out/MANIFEST).open("xb") as f:
        f.write(encoded)
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--private", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true", help="Verify inputs and allocation with zero output writes")
    args = parser.parse_args()
    results = run(args.artifacts,args.private,args.output,args.dry_run)
    print(json.dumps({k:results[k] for k in ("grouping","allocation","sample")},ensure_ascii=False))


if __name__ == "__main__":
    main()
