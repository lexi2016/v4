"""Isolated existing-producer history mode, entered by a_share_daily_sync.

This mode writes RAW-source staging and content-bound checkpoints only.
It imports the frozen formula producer's pure functions, never its main,
network loaders, maintenance entry points, promotion or pointer writers.
Conflict decisions must be supplied separately; there is no source preference
or unit/adjustment inference in this module.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import multiprocessing
import os
import resource
import shutil
import sys
import time
import uuid
import zipfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

FLAGS = dict(research_only=True, production_allowed=False,
             buy_gate_updated=False, orders_sent=False)
RAW = ("open", "high", "low", "close", "amount", "vol")
BOUND_PURE_FUNCTIONS = ("compute_formula_features", "build_table_for_schema",
                        "append_backtest_provenance_and_tradeability", "write_appended_parquet")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def sha(path: str | Path) -> str:
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def load(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def stat(path: str | Path) -> dict[str, int]:
    value = Path(path).stat()
    return dict(size=value.st_size, mtime_ns=value.st_mtime_ns, inode=value.st_ino)


def check_binding(binding: dict[str, Any], *, hash_bytes: bool = True) -> None:
    require(isinstance(binding.get("path"), str) and bool(binding["path"]), "BOUND_PATH_NOT_FROZEN")
    if binding.get("stat") is not None:
        require(stat(binding["path"]) == binding["stat"], "BOUND_STAT_DRIFT:" + binding["path"])
    if hash_bytes:
        require(isinstance(binding.get("sha256"), str) and len(binding["sha256"]) == 64,
                "BOUND_SHA_NOT_FROZEN:" + binding["path"])
        require(sha(binding["path"]) == binding["sha256"], "BOUND_SHA_DRIFT:" + binding["path"])


def write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        require(sha(path) == hashlib.sha256(payload).hexdigest(), "EXISTING_OUTPUT_DIFFERS:" + str(path))
        return
    temporary = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    with temporary.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    # One writer owns this checkpoint. Never replace an already published file.
    try:
        os.link(temporary, path)
    finally:
        temporary.unlink()


def save(path: Path, value: Any) -> None:
    write_bytes(path, (json.dumps(value, ensure_ascii=False, sort_keys=True,
                                 indent=2, allow_nan=False) + "\n").encode())


def source_module(binding: dict[str, Any], name: str) -> Any:
    check_binding(binding)
    spec = importlib.util.spec_from_file_location(name, binding["path"])
    require(spec is not None and spec.loader is not None, "SOURCE_IMPORT_SPEC_MISSING")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def runtime_adapter(config: dict[str, Any]) -> Any:
    adapter = source_module(config["runtime_adapter"], "history_bound_runtime_adapter")
    adapter.configure_native_thread_budget(processes=1, threads_per_process=1,
                                          total_thread_budget=config["runtime"]["total_thread_budget"])
    return adapter


def producer_module(config: dict[str, Any]) -> Any:
    # Called only after the existing trainer's native-thread initializer.
    producer = source_module(config["producer"], "history_bound_formula_producer")
    canonical = config["canonical"]
    check_binding(canonical)
    producer.CANONICAL_FORMULA_PATH = Path(canonical["path"])
    producer._CANONICAL_FORMULA_MODULE = None
    require(all(callable(getattr(producer, name, None)) for name in BOUND_PURE_FUNCTIONS),
            "BOUND_PRODUCER_PURE_FUNCTIONS_MISSING")
    return producer


class Logger:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def log(self, message: str) -> None:
        self.messages.append(str(message))


def validate_frozen_policy(config: dict[str, Any]) -> dict[str, Any]:
    binding = config["resolution_policy"]
    check_binding(binding)
    policy = load(binding["path"])
    require(policy.get("status") == "FROZEN_BY_ROOT", "SOURCE_RESOLUTION_POLICY_NOT_FROZEN")
    require(policy.get("price_or_volume_conversion") == "NONE", "SOURCE_CONVERSION_NOT_AUTHORIZED")
    require(policy.get("selection_unit") == "COMPLETE_SOURCE_BAR", "SOURCE_BAR_MIXING_FORBIDDEN")
    require(policy.get("conflict_action") == "KEEP_ALL_SOURCE_BYTES_AND_VALUES_SELECT_FROZEN_PRIORITY",
            "SOURCE_CONFLICT_ACTION_NOT_FROZEN")
    require(policy.get("name") in {"ARCHIVE_PRIMARY_NATIVE_TAIL_V1", "ARCHIVE_PRIMARY_NATIVE_MISSING_AND_TAIL_V2"},
            "SOURCE_RESOLUTION_NAME_NOT_FROZEN")
    return policy


def resolved_rows(source_rows: dict[str, list[dict[str, Any]]], policy: dict[str, Any], code: str,
                  last_date: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    indexed = {}
    for name, rows in source_rows.items():
        by_date = {row["trade_date"]: row for row in rows}
        require(len(by_date) == len(rows), "DUPLICATE_SOURCE_CODE_DATE:" + code + ":" + name)
        indexed[name] = by_date
    require(policy["name"] in {"ARCHIVE_PRIMARY_NATIVE_TAIL_V1", "ARCHIVE_PRIMARY_NATIVE_MISSING_AND_TAIL_V2"},
            "UNSUPPORTED_SOURCE_SELECTION_RULE")
    fill_native_gaps = policy["name"] == "ARCHIVE_PRIMARY_NATIVE_MISSING_AND_TAIL_V2"
    require(set(indexed) <= {"archive", "native"}, "PANEL_FALLBACK_NOT_AUTHORIZED")
    dates = sorted(set().union(*(rows.keys() for rows in indexed.values())))
    archive_last = max(indexed.get("archive", {}), default=None)
    selected, conflicts, provenance, gaps = [], [], [], []
    for day in dates:
        if day > last_date:
            continue
        available = {name: by_date[day] for name, by_date in indexed.items() if day in by_date}
        if "archive" in available:
            chosen = "archive"
            disposition = "ARCHIVE_PRIMARY"
        elif archive_last is not None and day > archive_last and "native" in available:
            chosen = "native"
            disposition = "NATIVE_TAIL_AFTER_ARCHIVE_LAST"
        elif fill_native_gaps and "native" in available:
            chosen = "native"
            disposition = "NATIVE_INTERNAL_ARCHIVE_GAP_FILL"
        else:
            gaps.append(dict(code=code, trade_date=day, available_sources=sorted(available),
                             reason="NO_ARCHIVE_ROW_AND_NATIVE_IS_NOT_POST_ARCHIVE_TAIL"))
            continue
        row = available[chosen]
        if fill_native_gaps:
            require(all(math.isfinite(float(row[field])) for field in RAW)
                    and min(row[field] for field in ("open", "high", "low", "close")) > 0
                    and row["low"] <= min(row["open"], row["close"]) <= max(row["open"], row["close"]) <= row["high"],
                    "SELECTED_SOURCE_BAR_INVALID:" + code + ":" + str(day))
        selected.append(dict(ts_code=code, trade_date=day, **{field: row[field] for field in RAW}))
        provenance.append(dict(code=code, trade_date=day, selected_source=chosen,
                               **({"disposition": disposition} if fill_native_gaps else {})))
        reference = {field: row[field] for field in RAW}
        if any({field: candidate[field] for field in RAW} != reference for candidate in available.values()):
            conflicts.append(dict(code=code, trade_date=day, selected_source=chosen,
                                  rule=policy["name"], source_values={name: {field: value[field] for field in RAW}
                                                              for name, value in available.items()}))
    if not selected and not gaps:
        gaps.append(dict(code=code, reason="RESOLVED_STOCK_HAS_NO_ROWS"))
    return selected, conflicts, provenance, gaps


def read_sources(stock: dict[str, Any], config: dict[str, Any], evidence: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    probe = source_module(config["source_probe"], "history_bound_day_codec")
    by_source = {}
    receipts = []
    for binding in stock["sources"]:
        name = binding["name"]
        require(name not in by_source, "DUPLICATE_STOCK_SOURCE_NAME")
        captured = config.get("source_payload_cache", {}).get(stock["code"], {}).get(name)
        if captured is not None:
            require(binding["kind"] in {"archive_member", "day_bytes"}, "SOURCE_CACHE_KIND_NOT_SUPPORTED")
            expected = binding["member_sha256"] if binding["kind"] == "archive_member" else binding["sha256"]
            require(captured["sha256"] == expected, "SOURCE_CACHE_ORIGINAL_BINDING_DRIFT")
            check_binding(binding, hash_bytes=False)
            check_binding(captured)
            payload = Path(captured["path"]).read_bytes()
            require(hashlib.sha256(payload).hexdigest() == expected, "SOURCE_CACHE_CHANGED_WHILE_READING")
            write_bytes(evidence / (name + ".day"), payload)
            rows = probe.decode_day(payload, stock["code"])
        elif binding["kind"] == "day_bytes":
            check_binding(binding)
            payload = Path(binding["path"]).read_bytes()
            require(hashlib.sha256(payload).hexdigest() == binding["sha256"], "SOURCE_CHANGED_WHILE_READING")
            write_bytes(evidence / (name + ".day"), payload)
            rows = probe.decode_day(payload, stock["code"])
        elif binding["kind"] == "archive_member":
            check_binding(binding, hash_bytes=False)
            with zipfile.ZipFile(binding["path"], "r") as archive:
                payload = archive.read(binding["member"])
            require(hashlib.sha256(payload).hexdigest() == binding["member_sha256"], "ARCHIVE_MEMBER_SHA_DRIFT")
            write_bytes(evidence / (name + ".day"), payload)
            rows = probe.decode_day(payload, stock["code"])
            check_binding(binding, hash_bytes=False)
        elif binding["kind"] == "panel_sample":
            rows_by_code, _ = probe.read_panel(binding, [stock["code"]])
            rows = rows_by_code[stock["code"]]
            save(evidence / (name + ".json"), rows)
        else:
            raise ValueError("UNSUPPORTED_FROZEN_SOURCE_KIND")
        by_source[name] = rows
        receipts.append(dict(name=name, binding=binding,
                             **({"payload_reuse_binding": captured} if captured is not None else {}), **probe.coverage(rows)))
    return by_source, receipts


def rebuild_table(rows: list[dict[str, Any]], config: dict[str, Any], producer: Any,
                  schema: Any, events: Any, logger: Logger) -> tuple[Any, dict[str, Any]]:
    import pandas as pd
    history = pd.DataFrame(rows)
    generated = producer.compute_formula_features(history, 0, {}, logger,
                                                   emit_all_rows=True, xdxr_events=events)
    generated = producer.append_backtest_provenance_and_tradeability(generated, Path(config["schema_source"]["path"]))
    # No inherited schema fallback may turn unavailable historical indicators
    # into zeros. A reviewed source-derived restoration hook must be frozen if
    # the current producer fails to emit a required existing-schema field.
    hook = config.get("schema_restoration")
    if hook is not None:
        restoration = source_module(hook, "history_bound_schema_restoration")
        generated = restoration.restore_backtest_fields(generated, history, config["schema_field_policy"])
    explicit_nulls = {}
    for name, reason in config.get("nullable_historical_fields", {}).items():
        require(name in schema.names and schema.field(name).nullable, "EXPLICIT_NULL_FIELD_NOT_NULLABLE:" + name)
        require(name not in ("ts_code", "trade_date", *RAW) and isinstance(reason, str) and bool(reason),
                "EXPLICIT_NULL_FIELD_NOT_AUTHORIZED:" + name)
        require(name not in generated.columns, "EXPLICIT_NULL_CANNOT_DISCARD_COMPUTED_FIELD:" + name)
        generated[name] = None
        explicit_nulls[name] = reason
    missing = sorted(set(schema.names) - set(generated.columns))
    require(not missing, "BACKTEST_FIELDS_NOT_COMPUTED:" + ",".join(missing))
    table, alignment = producer.build_table_for_schema(generated, schema, "backtest")
    require(alignment["default_filled_columns_count"] == 0, "BACKTEST_DEFAULT_FIELDS_FORBIDDEN")
    require(table.num_rows == len(rows), "BACKTEST_ROW_COUNT_CHANGED")
    if explicit_nulls:
        import pyarrow as pa
        for name in explicit_nulls:
            position = schema.get_field_index(name)
            table = table.set_column(position, schema.field(name), pa.nulls(table.num_rows, type=schema.field(name).type))
    alignment["explicit_null_reasons"] = explicit_nulls
    alignment["null_rows_by_column"] = {name: table.column(name).null_count for name in schema.names}
    return table, alignment


def stock_identity(stock: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    return dict(schema="V194_HISTORY_STOCK_CHECKPOINT_IDENTITY_V1", stock=stock,
                sources={key: config.get(key) for key in ("producer", "canonical", "source_probe", "runtime_adapter",
                        "schema_source", "resolution_policy", "event_input", "schema_restoration", "schema_field_policy",
                        "nullable_historical_fields")},
                helper_sha256=sha(__file__), last_date=config["last_panel_date"],
                stage=config.get("stage", "SCHEMA_CANARY"), native_threads=1, **FLAGS)


def raw_schema() -> Any:
    import pyarrow as pa
    return pa.schema([pa.field("ts_code", pa.string(), nullable=False),
                      pa.field("trade_date", pa.int32(), nullable=False),
                      *(pa.field(name, pa.float64(), nullable=False) for name in RAW if name != "vol"),
                      pa.field("vol", pa.uint64(), nullable=False)])


def materialize_rows(rows: list[dict[str, Any]], config: dict[str, Any], logger: Logger) -> tuple[Any, dict[str, Any]]:
    if config.get("stage") == "RAW_PROJECTION":
        import pyarrow as pa
        table = pa.Table.from_pylist(rows, schema=raw_schema())
        return table, dict(role="ISOLATED_RAW_SOURCE_PROJECTION", default_filled_columns_count=0,
                           raw_columns=table.schema.names, price_or_volume_conversion="NONE",
                           null_rows_by_column={name: table.column(name).null_count for name in table.schema.names})
    require(config.get("stage", "SCHEMA_CANARY") == "SCHEMA_CANARY", "UNSUPPORTED_BACKFILL_STAGE")
    import pandas as pd
    import pyarrow.parquet as pq
    producer = producer_module(config)
    check_binding(config["schema_source"], hash_bytes=False)
    schema = pq.read_schema(config["schema_source"]["path"])
    require(hashlib.sha256(schema.serialize().to_pybytes()).hexdigest() == config["schema_sha256"], "BACKTEST_SCHEMA_DRIFT")
    require(len(schema.names) == config["schema_column_count"], "BACKTEST_SCHEMA_COLUMN_COUNT_DRIFT")
    events = None
    if config["event_input"]["mode"] == "BOUND_CATEGORY1_PARQUET":
        event_binding = config["event_input"]["binding"]
        check_binding(event_binding)
        events = pd.read_parquet(event_binding["path"], filters=[("ts_code", "=", rows[0]["ts_code"])])
    elif config["event_input"]["mode"] == "NO_EXISTING_XDXR_CACHE_RAW_PRE_CLOSE_RECONSTRUCTION":
        event_policy = config["event_input"]
        check_binding(event_policy["metadata_trace"])
        require(event_policy.get("status") == "MISSING_IN_FROZEN_MAC_ROOT"
                and bool(event_policy.get("limitation")), "MISSING_EVENT_SOURCE_LIMITATION_REQUIRED")
    else:
        raise ValueError("EVENT_INPUT_NOT_BOUND_FOR_PRE_CLOSE_RECONSTRUCTION")
    table, alignment = rebuild_table(rows, config, producer, schema, events, logger)
    check_binding(config["schema_source"], hash_bytes=False)
    return table, alignment


def verify_checkpoint(directory: Path, identity: dict[str, Any]) -> dict[str, Any]:
    receipt = load(directory / "STOCK_CHECKPOINT.json")
    require(receipt["identity"] == identity, "STOCK_CHECKPOINT_IDENTITY_DRIFT")
    for name, value in receipt["files"].items():
        require(sha(directory / name) == value, "STOCK_CHECKPOINT_ARTIFACT_DRIFT:" + name)
    return receipt


def compatibility_reuse(stock: dict[str, Any], config: dict[str, Any], identity: dict[str, Any],
                        directory: Path) -> dict[str, Any] | None:
    """Reuse zero-gap RAW outputs with a new identity and explicit old hashes."""
    reference = config.get("compatibility_checkpoints", {}).get(stock["code"])
    if reference is None:
        return None
    started = time.monotonic()
    require(identity["stage"] == "RAW_PROJECTION", "COMPATIBILITY_ONLY_RAW_PROJECTION")
    previous_helper = config["compatibility_previous_helper"]
    previous_policy = config["compatibility_previous_policy"]
    check_binding(previous_helper)
    check_binding(previous_policy)
    require(load(previous_policy["path"])["name"] == "ARCHIVE_PRIMARY_NATIVE_TAIL_V1"
            and validate_frozen_policy(config)["name"] == "ARCHIVE_PRIMARY_NATIVE_MISSING_AND_TAIL_V2",
            "COMPATIBILITY_POLICY_TRANSITION_NOT_AUTHORIZED")
    previous_identity = {**identity, "helper_sha256": previous_helper["sha256"],
                         "sources": {**identity["sources"], "resolution_policy": previous_policy}}
    old = Path(reference["directory"]).resolve()
    expected = (Path(config["checkpoint_root"]) / stock["code"] / digest(previous_identity)).resolve()
    require(old == expected, "COMPATIBILITY_SOURCE_IDENTITY_DRIFT")
    old_receipt_path = old / "STOCK_CHECKPOINT.json"
    require(sha(old_receipt_path) == reference["receipt_sha256"], "COMPATIBILITY_RECEIPT_SHA_DRIFT")
    receipt = verify_checkpoint(old, previous_identity)
    require(load(old / "SOURCE_COVERAGE_GAPS.json") == [], "COMPATIBILITY_PREVIOUS_GAPS_NOT_EMPTY")
    require(all(item.get("invalid_ohlc_rows") == 0 for item in receipt["source_receipts"]),
            "COMPATIBILITY_PREVIOUS_BAR_VALIDITY_UNPROVEN")
    require({item["name"]: item["binding"] for item in receipt["source_receipts"]}
            == {item["name"]: item for item in stock["sources"]}, "COMPATIBILITY_SOURCE_BINDING_DRIFT")
    # The only selection extension fills previous gaps. An empty, hash-bound
    # previous gap set proves it cannot alter these stock rows.
    work = directory.with_name(directory.name + ".compatibility-" + uuid.uuid4().hex)
    work.mkdir(parents=True)
    files = {}
    for name, expected_sha in receipt["files"].items():
        source = (old / name).resolve()
        require(source.is_relative_to(old), "COMPATIBILITY_ARTIFACT_PATH_ESCAPE")
        target_name = "LEGACY_SELECTED_BAR_PROVENANCE.json" if name == "SELECTED_BAR_PROVENANCE.json" else name
        target = work / target_name
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(source, target)
        except OSError:
            shutil.copyfile(source, target)
        require(sha(target) == expected_sha, "COMPATIBILITY_COPY_SHA_DRIFT:" + name)
        files[target_name] = expected_sha
    provenance = load(old / "SELECTED_BAR_PROVENANCE.json")
    for row in provenance:
        require(row["selected_source"] in {"archive", "native"}, "COMPATIBILITY_PREVIOUS_SOURCE_UNKNOWN")
        row["disposition"] = "ARCHIVE_PRIMARY" if row["selected_source"] == "archive" else "NATIVE_TAIL_AFTER_ARCHIVE_LAST"
    save(work / "SELECTED_BAR_PROVENANCE.json", provenance)
    files["SELECTED_BAR_PROVENANCE.json"] = sha(work / "SELECTED_BAR_PROVENANCE.json")
    proof = dict(schema="V194_COMPATIBILITY_REUSE_RECEIPT_V1", status="REUSED_NOT_RECOMPUTED",
                 previous_checkpoint=str(old), previous_identity=previous_identity,
                 previous_receipt_sha256=reference["receipt_sha256"], previous_output_sha256=receipt["files"],
                 new_identity=identity, previous_gap_count=0, native_internal_gap_branch_triggered=False,
                 unchanged="stock sources, producer, schema, event input, cutoff, RAW table bytes and values",
                 derived_metadata_only="source disposition added to copied legacy row provenance",
                 raw_rows_recomputed=0, formula_evaluations=0, model_fits=0, labels_computed=0, **FLAGS)
    save(work / "COMPATIBILITY_REUSE.json", proof)
    files["COMPATIBILITY_REUSE.json"] = sha(work / "COMPATIBILITY_REUSE.json")
    current = {**receipt, "identity": identity, "files": files,
               "source_resolution_policy": load(config["resolution_policy"]["path"]),
               "compatibility_reuse": {"path": "COMPATIBILITY_REUSE.json", "sha256": files["COMPATIBILITY_REUSE.json"]},
               "materialization_status": "REUSED_NOT_RECOMPUTED",
               "worker_pid": os.getpid(), "elapsed_seconds": time.monotonic() - started,
               "worker_peak_rss_bytes": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
                    * (1 if sys.platform == "darwin" else 1024)}
    save(work / "STOCK_CHECKPOINT.json", current)
    require(not directory.exists(), "COMPATIBILITY_TARGET_APPEARED_DURING_REUSE")
    os.rename(work, directory)
    return dict(code=stock["code"], checkpoint=str(directory), reused=True,
                compatibility_reused=True, receipt=current)


def process_stock(stock: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    runtime_adapter(config)  # before importing producer/pandas/NumPy/Arrow
    import pyarrow.parquet as pq
    started = time.monotonic()
    identity = stock_identity(stock, config)
    for binding in stock["sources"]:
        check_binding(binding, hash_bytes=binding["kind"] == "day_bytes")
    directory = Path(config["checkpoint_root"]) / stock["code"] / digest(identity)
    if (directory / "STOCK_CHECKPOINT.json").is_file():
        receipt = verify_checkpoint(directory, identity)
        return dict(code=stock["code"], checkpoint=str(directory), reused=True, receipt=receipt)
    reused = compatibility_reuse(stock, config, identity, directory)
    if reused is not None:
        return reused
    policy = validate_frozen_policy(config)
    work = directory.with_name(directory.name + ".incomplete-" + uuid.uuid4().hex)
    work.mkdir(parents=True)
    by_source, source_receipts = read_sources(stock, config, work / "original_source_bytes")
    rows, conflicts, provenance, gaps = resolved_rows(by_source, policy, stock["code"], config["last_panel_date"])
    save(work / "SOURCE_CONFLICTS.json", conflicts)
    save(work / "SELECTED_BAR_PROVENANCE.json", provenance)
    save(work / "SOURCE_COVERAGE_GAPS.json", gaps)
    require(not gaps, "SOURCE_COVERAGE_GAPS_REQUIRE_ROOT_DECISION:" + str(work / "SOURCE_COVERAGE_GAPS.json"))
    logger = Logger()
    table, alignment = materialize_rows(rows, config, logger)
    pq.write_table(table, work / "backtest_stock.parquet", compression="snappy")
    save(work / "PURE_FUNCTION_LOG.json", logger.messages)
    names = [str(path.relative_to(work)) for path in sorted(work.rglob("*")) if path.is_file()]
    rss = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    rss_bytes = rss if sys.platform == "darwin" else rss * 1024
    receipt = dict(identity=identity, code=stock["code"], source_receipts=source_receipts,
                   files={name: sha(work / name) for name in names}, rows=table.num_rows,
                   first_date=rows[0]["trade_date"], last_date=rows[-1]["trade_date"],
                   conflict_dates=len(conflicts), schema_alignment=alignment,
                   event_input_policy=config.get("event_input"), source_resolution_policy=policy,
                   worker_pid=os.getpid(), worker_peak_rss_bytes=rss_bytes,
                   elapsed_seconds=time.monotonic()-started,
                   formula_evaluations=0 if config.get("stage") == "RAW_PROJECTION" else 1,
                   model_fits=0, labels_computed=0, pointer_writes=0, **FLAGS)
    save(work / "STOCK_CHECKPOINT.json", receipt)
    require(not directory.exists(), "STOCK_CHECKPOINT_APPEARED_DURING_EXECUTION")
    os.rename(work, directory)
    return dict(code=stock["code"], checkpoint=str(directory), reused=False, receipt=receipt)


def run_config(path: str | Path, expected_sha: str) -> dict[str, Any]:
    require(sha(path) == expected_sha, "BACKFILL_CONFIG_SHA_DRIFT")
    config = load(path)
    require(config["schema"] == "V194_EXISTING_PRODUCER_HISTORY_BACKFILL_V1", "BACKFILL_CONFIG_SCHEMA_DRIFT")
    require(config.get("safety_flags") == FLAGS, "UNSAFE_BACKFILL_FLAGS")
    require(config.get("status") == "FROZEN_READY_FOR_REGISTERED_CANARY", "BACKFILL_CONFIG_STILL_DRAFT")
    for binding in config["code_bindings"]:
        check_binding(binding)
    for binding in config.get("metadata_bindings", []):
        check_binding(binding)
    require(config["mode"] in {"canary", "full"}, "BACKFILL_MODE_INVALID")
    require(config["mode"] == "canary" or config.get("stage") == "RAW_PROJECTION",
            "FULL_HISTORY_REQUIRES_SEPARATELY_VERIFIED_SHARED_QFQ_TRANSFORM_BINDING")
    require(config["last_panel_date"] <= 20261023, "PANEL_DATE_BOUND_EXCEEDED")
    require(config["latest_training_target_date"] == 20261022, "TRAINING_TARGET_BOUND_DRIFT")
    validate_frozen_policy(config)  # unresolved decisions stop before raw reads
    stocks = config["stocks"]
    require(stocks and len({stock["code"] for stock in stocks}) == len(stocks), "STOCK_KEYSET_NOT_UNIQUE")
    require(config["mode"] != "canary" or len(stocks) <= 5, "BACKFILL_CANARY_SCOPE_EXCEEDED")
    for binding in config["protected_pointers"]:
        check_binding(binding)
    adapter = runtime_adapter(config)
    requested = config["runtime"]["requested_workers"]
    require(type(requested) is int and 1 <= requested <= 12, "BACKFILL_WORKERS_INVALID")
    if config["mode"] == "canary":
        require(requested == 1, "FIRST_REAL_DATA_CANARY_MUST_USE_ONE_WORKER")
        workers = 1
        selection = dict(requested_workers=1, actual_workers=1, reason="FIRST_REAL_PRODUCER_STOCK_CANARY")
    else:
        profile = config["worker_resource_profile"]
        check_binding(profile)
        profile_result = load(profile["path"])
        require(profile_result["status"] == "ISOLATED_RAW_HISTORY_STAGING_READY_FOR_REVIEW", "DATA_CANARY_RESOURCE_PROFILE_NOT_PASS")
        selection = adapter.select_safe_fit_workers(
            requested_workers=requested, threads_per_worker=1,
            total_thread_budget=config["runtime"]["total_thread_budget"],
            canary_peak_rss_bytes=profile_result["maximum_worker_peak_rss_bytes"],
            available_memory_bytes=adapter.runtime_snapshot()["available_memory_bytes"],
            memory_safety_fraction=config["runtime"]["memory_safety_fraction"])
        workers = selection["actual_workers"]
    output = Path(config["output_dir"])
    require(not output.exists(), "BACKFILL_EXECUTION_OUTPUT_EXISTS")
    output.mkdir(parents=True)
    save(output / "LAUNCH_RESOURCE_HEADER.json", dict(
        schema="V194_RAW_LAUNCH_RESOURCE_HEADER_V1", config_sha256=expected_sha,
        parent_pid=os.getpid(), worker_selection=selection, actual_workers=workers,
        native_threads_per_worker=1, effective_native_thread_budget=workers,
        runtime_snapshot=adapter.runtime_snapshot(), worker_resource_profile=config.get("worker_resource_profile"),
        **FLAGS))
    started = time.monotonic()
    results = []
    with ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context("spawn"),
                             max_tasks_per_child=1) as pool:
        futures = {pool.submit(process_stock, stock, config): stock["code"] for stock in stocks}
        try:
            for future in as_completed(futures):
                results.append(future.result())
                if len(results) % 250 == 0:
                    save(output / ("PROGRESS_" + f"{len(results):05d}" + ".json"), dict(
                        completed_stocks=len(results), reused_stocks=sum(item["reused"] for item in results),
                        latest_code=results[-1]["code"], actual_workers=workers,
                        elapsed_seconds=time.monotonic() - started, **FLAGS))
        except BaseException:
            for future in futures:
                future.cancel()  # running stocks finish; no process is killed
            raise
    results.sort(key=lambda result: result["code"])
    import pyarrow.parquet as pq
    schema = raw_schema() if config.get("stage") == "RAW_PROJECTION" else pq.read_schema(config["schema_source"]["path"])
    candidate = output / ("raw_source_projection.parquet" if config.get("stage") == "RAW_PROJECTION" else "backtest_raw_history_staging.parquet")
    with pq.ParquetWriter(candidate, schema, compression="snappy") as writer:
        for result in results:
            parquet = pq.ParquetFile(Path(result["checkpoint"]) / "backtest_stock.parquet")
            for batch in parquet.iter_batches(batch_size=65536):
                import pyarrow as pa
                writer.write_table(pa.Table.from_batches([batch], schema=schema))
            parquet.close()
    for binding in config["protected_pointers"]:
        check_binding(binding)
    result = dict(schema="V194_EXISTING_PRODUCER_HISTORY_BACKFILL_RESULT_V1",
                  status="ISOLATED_RAW_HISTORY_STAGING_READY_FOR_REVIEW", config_sha256=expected_sha,
                  candidate_path=str(candidate), candidate_sha256=sha(candidate),
                  stocks=results, rows=sum(item["receipt"]["rows"] for item in results),
                  reused_codes=[item["code"] for item in results if item["reused"]],
                  recomputed_codes=[item["code"] for item in results if not item["reused"]],
                  maximum_worker_peak_rss_bytes=max(item["receipt"]["worker_peak_rss_bytes"] for item in results),
                  worker_selection=selection, elapsed_seconds=time.monotonic()-started,
                  stage=config.get("stage", "SCHEMA_CANARY"),
                  formula_evaluations=sum(item["receipt"]["formula_evaluations"] for item in results if not item["reused"]),
                  price_basis="SOURCE_BYTES_UNCHANGED_NO_QFQ_TRANSFORM_APPLIED",
                  training_input_status="NOT_FIT_INPUT_WAITING_FOR_SHARED_QFQ_TRANSFORM_CACHE_AND_ASOF_BINDING",
                  shared_qfq_owner="/root/qfq_daily_writer",
                  labels_computed=0, model_fits=0, predictions=0, pointer_writes=0, **FLAGS)
    save(output / "RESULT.json", result)
    return {key: result[key] for key in ("status", "candidate_path", "candidate_sha256", "rows", "reused_codes", "recomputed_codes")}
