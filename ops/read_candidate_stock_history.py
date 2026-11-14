"""Read explicitly bound history views in a loopback preview only."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import re


SYMBOL = "000821.SZ"
SYMBOLS = {SYMBOL, "688729.SH", "301618.SZ", "301585.SZ"}
DATES = {"20261112", "20261113"}
GROUPS = {"original", "nav_smallk", "nav_pullback", "nav_breakout"}
HORIZONS = {"d2", "d5"}
PATCHABLE = {"statistics", "historical_coverage"}
CASE_FIELDS = {"event_date", "target_date", "status", "detail_status", "return_pct"}
RATE_FIELDS = {"valid", "positive", "positive_fraction", "not_matured", "total"}
SINGLE_SCHEMA = "V4_STOCK_HISTORY_CANDIDATE_OVERLAY_V1"
BATCH_SCHEMA = "V4_FOUR_STOCK_HISTORY_CANDIDATE_OVERLAY_V1"
RAW_FLAGS = dict(RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
RESPONSE_FLAGS = dict(research_only=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)


def _digest(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _require(test, reason):
    if not test:
        raise ValueError("STJINGJI_CANDIDATE_" + reason)


def _object(reference, root=None):
    _require(type(reference) is dict and set(reference) == {"path", "sha256"}
             and type(reference["path"]) is str and type(reference["sha256"]) is str
             and re.fullmatch(r"[0-9a-f]{64}", reference["sha256"]), "REFERENCE")
    path = Path(reference["path"])
    _require(path.is_absolute() and not path.is_symlink() and path.resolve(strict=True) == path
             and (root is None or path.is_relative_to(root)), "PATH")
    with path.open("rb") as stream:
        raw = stream.read(32 * 1024 * 1024 + 1)
    _require(len(raw) <= 32 * 1024 * 1024 and sha256(raw).hexdigest() == reference["sha256"], "SHA")
    value = json.loads(raw)
    _require(type(value) is dict and all(value.get(k) is v for k, v in RAW_FLAGS.items()), "SAFETY")
    return value


def _iso(day):
    day = str(day)
    return f"{day[:4]}-{day[4:6]}-{day[6:]}"


def _rates(row):
    return {item["group_id"]: {h: {k: values[k] for k in RATE_FIELDS}
            for h, values in item["horizons"].items()} for item in row["statistics"]["groups"]}


def _view(day, symbol, binding, root):
    original_manifest = _object(binding["numeric_manifest"])
    original_product = _object(original_manifest["artifact"])
    old_row = _object(original_product["row_refs"][symbol])
    row = _object(binding["detail_row"], root)
    cases = _object(binding["event_cases"], root)
    chart_manifest = _object(binding["chart_manifest"])
    chart = chart_manifest["samples"][symbol]
    stats = row["statistics"]
    cutoff = _iso(day)
    groups = {item["group_id"]: item for item in stats["groups"]}
    _require(original_manifest["data_date"] == original_product["data_date"] == day
             and original_manifest["source_generation"] == original_product["source_generation"] == binding["generation"]
             and original_manifest["input_sha256"] == original_product["source_identity"]["input_sha256"] == binding["input_sha256"], "SOURCE")
    _require({k: v for k, v in row.items() if k not in PATCHABLE} ==
             {k: v for k, v in old_row.items() if k not in PATCHABLE}, "ORIGINAL_DETAIL_CHANGED")
    old_groups = {item["group_id"]: item for item in old_row["statistics"]["groups"]}
    coverage = row["historical_coverage"]
    dates = coverage["evaluated_dates"]
    _require(coverage["known_full_history"] is True and coverage["historical_PIT"] is False
             and coverage["requested_end"] == int(day) and dates == sorted(set(dates))
             and dates[-1:] == [int(day)]
             and len(dates) == coverage["evaluated_count"] == coverage["available_prefix_dates"], "COVERAGE")
    _require(stats["asof"] == cutoff and set(groups) == set(cases["groups"]) == GROUPS
             and len(stats["groups"]) == len(GROUPS), "GROUPS")
    _require(cases["schema_version"] == "v4.a_share.event_cases.v1" and cases["symbol"] == symbol
             and cases["data_date"] == day and cases["numeric_manifest"] == binding["numeric_manifest"]
             and cases["source_generation"] == binding["generation"] and cases["input_sha256"] == binding["input_sha256"]
             and cases["statistics_sha256"] == _digest(stats), "CASE_IDENTITY")
    _require(chart["data_date"] == day and chart["source_generation"] == binding["generation"]
             and chart["source_input_sha256"] == binding["input_sha256"]
             and chart["product_row_ref"] == original_product["row_refs"][symbol]
             and chart["projection"] == cases["projection"], "PROJECTION_IDENTITY")
    for group, entry in groups.items():
        old = old_groups[group]
        _require(entry["source_identity"] == old["source_identity"]
                 and entry["rule_sha256"] == old["rule_sha256"]
                 and entry["identity_status"] == old["identity_status"] == "BOUND", "STATISTICS_IDENTITY")
        _require(set(entry["horizons"]) == set(cases["groups"][group]) == HORIZONS, "HORIZONS")
        for horizon in HORIZONS:
            summary, full = entry["horizons"][horizon], cases["groups"][group][horizon]
            records = full["cases"]
            _require(type(records) is list and len(records) == full["total"] == summary["total"] == entry["eligible_event_count"]
                     and all(summary[k] == full.get(k) for k in summary if k != "cases")
                     and all(CASE_FIELDS <= case.keys() and case["event_date"] <= cutoff
                             and (case["return_pct"] is None if case["status"] == "not_matured"
                                  else case["target_date"] is not None and case["target_date"] <= cutoff)
                             for case in records)
                     and [{k: case[k] for k in CASE_FIELDS} for case in records[:len(summary["cases"])]] == summary["cases"],
                     "CASE_COUNT_OR_CUTOFF")
    return row, cases


def _manifest(path, expected_sha256):
    manifest = _object(dict(path=str(path), sha256=expected_sha256))
    _require(set(manifest.get("dates", {})) == DATES, "MANIFEST_DATES")
    return manifest


def _batch_day(binding):
    _require(type(binding) is dict and set(binding) == {"numeric_manifest", "generation", "input_sha256",
             "chart_manifest", "views", "statistics_pointer", "previous_statistics_pointer"}
             and set(binding["views"]) == SYMBOLS, "BATCH_SCOPE")
    return {k: binding[k] for k in ("numeric_manifest", "generation", "input_sha256", "chart_manifest")}


def install(source_class, manifest_path, expected_sha256):
    """Wrap the preview class before create_app; all other reads delegate verbatim."""
    path = Path(manifest_path)
    manifest = _manifest(path, expected_sha256)
    _require(not getattr(source_class, "_stjingji_candidate_history_installed", False), "ALREADY_INSTALLED")
    batch = manifest.get("schema") == BATCH_SCHEMA
    _require(batch or (manifest.get("schema") == SINGLE_SCHEMA and manifest.get("symbol") == SYMBOL), "MANIFEST_SCOPE")
    views = {}
    for day, binding in manifest["dates"].items():
        if batch:
            common = _batch_day(binding)
            previous = _object(_object(binding["previous_statistics_pointer"])["artifact"])
            for symbol, local in binding["views"].items():
                _require(type(local) is dict and set(local) == {"detail_row", "event_cases"}, "VIEW_SCOPE")
                view = {**common, **local}
                row, cases = _view(day, symbol, view, path.parent)
                comparison = dict(before=previous["rows"][symbol], after=_rates(row),
                                  current_hit_groups=[g for g in (row.get("groups") or "").split("|") if g])
                views[day, symbol] = (view, row, cases, comparison)
        else:
            _require(type(binding) is dict and set(binding) == {"numeric_manifest", "generation", "input_sha256",
                     "detail_row", "event_cases", "chart_manifest"}, "VIEW_SCOPE")
            views[day, SYMBOL] = (binding, *_view(day, SYMBOL, binding, path.parent), None)
    read_detail = source_class.read_a_daily_product
    read_cases = source_class.read_a_daily_event_cases

    def read_a_daily_product(self, date=None, symbol=None, *, include_display_names=True):
        response = read_detail(self, date, symbol, include_display_names=include_display_names)
        if (date, symbol) not in views:
            return response
        binding, row, _, comparison = views[date, symbol]
        _require(response.get("status") == "READY" and response.get("data_date") == date
                 and response.get("manifest") == binding["numeric_manifest"]
                 and response.get("source_generation") == binding["generation"]
                 and response.get("source_identity", {}).get("input_sha256") == binding["input_sha256"], "DETAIL_MOVED")
        patched = {**response, "row": {**response["row"], **{k: deepcopy(row[k]) for k in PATCHABLE}}}
        if comparison is not None:
            patched["candidate_history_comparison"] = deepcopy(comparison)
        return patched

    def read_a_daily_event_cases(self, date, symbol, *, group="original", horizon="d2"):
        if (date, symbol) not in views or group not in GROUPS or horizon not in HORIZONS:
            return read_cases(self, date, symbol, group=group, horizon=horizon)
        detail = read_a_daily_product(self, date, symbol, include_display_names=False)
        binding, _, cases, _ = views[date, symbol]
        selected = deepcopy(cases["groups"][group][horizon])
        return {**selected, "status": "READY", "symbol": symbol, "data_date": date, "group": group,
                "horizon": horizon, "numeric_manifest": detail["manifest"], "source_generation": detail["source_generation"],
                "source_identity": detail["source_identity"], "projection": cases["projection"],
                "case_ref": binding["event_cases"], **RESPONSE_FLAGS}

    source_class.read_a_daily_product = read_a_daily_product
    source_class.read_a_daily_event_cases = read_a_daily_event_cases
    source_class._stjingji_candidate_history_installed = True


def install_statistics(host_class, statistics_root, *, manifest_path=None, expected_sha256=None):
    """Select committed candidate list statistics only on the two preview dates."""
    root = Path(statistics_root)
    _require(root.is_absolute() and not root.is_symlink() and root.resolve(strict=True) == root,
             "STATISTICS_ROOT")
    _require(not getattr(host_class, "_stjingji_candidate_statistics_installed", False), "STATISTICS_ALREADY_INSTALLED")
    batch = _manifest(Path(manifest_path), expected_sha256) if manifest_path is not None else None
    _require(batch is None or batch.get("schema") == BATCH_SCHEMA, "STATISTICS_BATCH_SCHEMA")
    views = {}
    for compact_day in sorted(DATES):
        day = _iso(compact_day)
        date_root = root / day
        path = date_root / "latest.json"
        _require(not path.is_symlink() and path.resolve(strict=True) == path, "STATISTICS_POINTER_PATH")
        with path.open("rb") as stream:
            raw = stream.read(64 * 1024 + 1)
        _require(len(raw) <= 64 * 1024, "STATISTICS_POINTER_SIZE")
        if batch is not None:
            binding = batch["dates"][compact_day]
            common = _batch_day(binding)
            _require(binding["statistics_pointer"] == dict(path=str(path), sha256=sha256(raw).hexdigest()),
                     "STATISTICS_POINTER_SHA")
        pointer = json.loads(raw)
        _require(type(pointer) is dict and pointer.get("schema") == "V4_WORKBENCH_MODULE_COMMIT_V1"
                 and pointer.get("module") == "statistics" and pointer.get("date") == day
                 and all(pointer.get(k) is v for k, v in RAW_FLAGS.items()), "STATISTICS_POINTER")
        artifact = _object(pointer["artifact"], date_root)
        receipt = _object(pointer["receipt"], date_root)
        _require(receipt["status"] == "COMMITTED" and receipt["artifact"] == pointer["artifact"]
                 and artifact["schema"] == "V4_WORKBENCH_STATISTICS_V1" and artifact["source_date"] == day
                 and set(artifact["rows"][SYMBOL]) == GROUPS, "STATISTICS_COMMIT")
        if batch is not None:
            old_pointer = _object(binding["previous_statistics_pointer"])
            old = _object(old_pointer["artifact"])
            old_rows, new_rows = old["rows"], artifact["rows"]
            _require(old_pointer["date"] == day and artifact["numeric_manifest"] == common["numeric_manifest"]
                     and artifact["generation"] == common["generation"] and artifact["input_sha256"] == common["input_sha256"]
                     and {k: v for k, v in old.items() if k != "rows"} == {k: v for k, v in artifact.items() if k != "rows"}
                     and set(new_rows) == set(old_rows) and SYMBOLS <= set(new_rows)
                     and all(new_rows[s] == old_rows[s] for s in set(new_rows) - SYMBOLS), "STATISTICS_SCOPE")
            for symbol in SYMBOLS:
                row = _object(binding["views"][symbol]["detail_row"], Path(manifest_path).parent)
                _require(new_rows[symbol] == _rates(row) and set(old_rows[symbol]) == GROUPS,
                         "STATISTICS_DETAIL_PARITY")
        views[day] = pointer["artifact"]

    original = host_class._module_reference

    def _module_reference(self, module, day):
        if module == "statistics" and day in views:
            return views[day].copy()
        return original(self, module, day)

    host_class._module_reference = _module_reference
    host_class._stjingji_candidate_statistics_installed = True
