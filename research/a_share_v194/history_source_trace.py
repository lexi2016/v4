"""Bounded 22-key provenance trace; no formula, repair, labels or fitting.

Reuse the already captured .day bytes and pairwise comparison. Read only the
two bound panel footers plus exact case/preceding source dates and existing
corporate-action metadata. Never fetch events or invoke producer entrypoints.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import time
from pathlib import Path
from typing import Any

FIELDS = ("open", "high", "low", "close", "amount", "vol")
FLAGS = dict(research_only=True, production_allowed=False,
             buy_gate_updated=False, orders_sent=False)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stat(path: str | Path) -> dict[str, int]:
    value = Path(path).stat()
    return dict(size=value.st_size, mtime_ns=value.st_mtime_ns, inode=value.st_ino)


def check(binding: dict[str, Any], *, hash_bytes: bool = True) -> None:
    if "stat" in binding:
        require(stat(binding["path"]) == binding["stat"], "TRACE_INPUT_STAT_DRIFT:" + binding["path"])
    if hash_bytes:
        require(sha(binding["path"]) == binding["sha256"], "TRACE_INPUT_SHA_DRIFT:" + binding["path"])


def save(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def reused_comparisons(rows: list[dict[str, str]], cases: set[tuple[str, int]]) -> dict[tuple[str, int], dict[str, Any]]:
    result = {key: {} for key in cases}
    for row in rows:
        key = (row["code"], int(row["trade_date"]))
        if key not in result:
            continue
        for side in ("left", "right"):
            source = row[side]
            values = {field: row[side + "_" + field] for field in FIELDS}
            previous = result[key].get(source)
            require(previous is None or previous == values, "REUSED_PAIR_VALUES_DISAGREE:" + repr(key) + ":" + source)
            result[key][source] = values
    require(all(result[key] for key in cases), "TRACE_KEY_NOT_IN_REVIEWED_CONFLICT_ARTIFACT")
    return result


def read_panel_exact(dataset: Any, schema: Any, code: str, dates: set[int],
                     columns: list[str], string_date_format: str) -> Any:
    import pyarrow as pa
    import pyarrow.dataset as ds
    dtype = schema.field("trade_date").type
    if pa.types.is_string(dtype) or pa.types.is_large_string(dtype):
        require(string_date_format == "YYYYMMDD", "TRACE_STRING_DATE_FORMAT_NOT_FROZEN")
        values = pa.array([str(day) for day in sorted(dates)], type=dtype)
    elif pa.types.is_int32(dtype) or pa.types.is_int64(dtype):
        values = pa.array(sorted(dates), type=dtype)
    else:
        raise ValueError("TRACE_UNSUPPORTED_DATE_TYPE:" + str(dtype))
    return dataset.to_table(columns=columns,
                           filter=(ds.field("ts_code") == code) & ds.field("trade_date").isin(values),
                           use_threads=False)


def execute(config: dict[str, Any], config_sha: str) -> dict[str, Any]:
    require(config["schema"] == "V194_SOURCE_ROW_TRACE_CONFIG_V1", "TRACE_CONFIG_SCHEMA")
    require(config["safety_flags"] == FLAGS, "TRACE_UNSAFE_FLAGS")
    cases = config["cases"]
    keys = {(row["code"], row["trade_date"]) for row in cases}
    require(len(cases) == len(keys) == 22, "TRACE_EXPECTS_EXACT_22_UNIQUE_KEYS")
    require(len({key[0] for key in keys}) == 5, "TRACE_EXPECTS_FIVE_FROZEN_CODES")
    output = Path(config["output_dir"])
    require(not output.exists(), "TRACE_OUTPUT_EXISTS_NO_RETRY")
    for binding in config["metadata_bindings"]:
        check(binding)
    for binding in config["protected_pointers"]:
        check(binding)
    for binding in config["source_stat_guards"]:
        check(binding, hash_bytes=False)
    check(config["source_probe"])
    spec = importlib.util.spec_from_file_location("trace_bound_day_codec", config["source_probe"]["path"])
    require(spec is not None and spec.loader is not None, "TRACE_CODEC_IMPORT_SPEC")
    codec = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(codec)
    check(config["conflicts"])
    with Path(config["conflicts"]["path"]).open(newline="", encoding="utf-8") as stream:
        comparisons = reused_comparisons(list(csv.DictReader(stream)), keys)
    captured = {}
    exact_dates = {code: set() for code, _ in keys}
    for code, sources in config["captured_sample_bytes"].items():
        captured[code] = {}
        for source, binding in sources.items():
            check(binding)
            rows = codec.decode_day(Path(binding["path"]).read_bytes(), code)
            captured[code][source] = rows
            for _, day in (key for key in keys if key[0] == code):
                prior = [int(row["trade_date"]) for row in rows if int(row["trade_date"]) < day]
                exact_dates[code].add(day)
                if prior:
                    exact_dates[code].add(max(prior))
    output.mkdir(parents=True)
    started = time.monotonic()
    save(output / "START_OBSERVATION.json", dict(pid=os.getpid(), config_sha256=config_sha,
                                                code_sha256=sha(__file__), **FLAGS))
    import pyarrow.dataset as ds
    import pyarrow.parquet as pq
    footers, panel_rows, panel_specs = {}, {}, {}
    for role, binding in config["panels"].items():
        check(binding, hash_bytes=False)
        schema = pq.read_schema(binding["path"])
        require(str(schema.field("trade_date").type) == binding["trade_date_arrow_type"], "TRACE_DATE_TYPE_BINDING_DRIFT")
        footers[role] = dict(path=binding["path"], fields=[dict(position=i, name=field.name,
                                  type=str(field.type), nullable=field.nullable) for i, field in enumerate(schema)],
                            serialized_schema_sha256=hashlib.sha256(schema.serialize().to_pybytes()).hexdigest())
        volume = binding["volume_field"]
        required = ["ts_code", "trade_date", "open", "high", "low", "close", "amount", volume]
        require(all(name in schema.names for name in required), "TRACE_PANEL_SCHEMA_DRIFT")
        provenance = [name for name in config["panel_provenance_fields"] if name in schema.names]
        footers[role]["missing_provenance_fields"] = sorted(set(config["panel_provenance_fields"]) - set(provenance))
        panel_specs[role] = (schema, required + provenance)
        check(binding, hash_bytes=False)
    # Persist complete schema evidence before any row-filter operation.
    save(output / "PANEL_FOOTERS.json", footers)
    for role, binding in config["panels"].items():
        schema, columns = panel_specs[role]
        volume = binding["volume_field"]
        selected = {}
        dataset = ds.dataset(binding["path"], format="parquet")
        for code, dates in exact_dates.items():
            table = read_panel_exact(dataset, schema, code, dates, columns, binding.get("string_date_format", ""))
            for row in table.to_pylist():
                key = (str(row["ts_code"]), int(row["trade_date"]))
                require(key not in selected, "TRACE_PANEL_DUPLICATE_EXACT_KEY")
                row["vol"] = row.pop(volume) if volume != "vol" else row["vol"]
                selected[key] = row
        for key in keys:
            require(role not in comparisons[key] or key in selected,
                    "TRACE_REVIEWED_PANEL_KEY_NOT_RETURNED:" + role + ":" + repr(key))
        panel_rows[role] = selected
        check(binding, hash_bytes=False)
        save(output / ("PANEL_" + role.upper() + "_ROWS.json"),
             [row for _, row in sorted(selected.items())])
    # Metadata-only stat/hash for original XDXR files. A cache is inspected only
    # when present; no cache generation, gbbq decoder, fetch or producer call.
    xdxr = []
    for item in config["xdxr_metadata"]:
        path = Path(item["path"])
        exists = path.is_file()
        require(exists == item["exists_at_freeze"], "TRACE_XDXR_PRESENCE_DRIFT")
        record = dict(path=str(path), exists=exists, kind=item["kind"], status="MISSING_AT_FREEZE")
        if exists:
            check(item, hash_bytes=False)
            record.update(stat=stat(path), sha256=sha(path), status="EXISTING_BYTES_OBSERVED_NOT_PIT_CERTIFIED")
            if item["kind"] == "cache_manifest_json":
                record["metadata"] = json.loads(path.read_text(encoding="utf-8-sig"))
            elif item["kind"] == "category1_cache_parquet":
                event_schema = pq.read_schema(path)
                record["fields"] = [dict(name=field.name, type=str(field.type), nullable=field.nullable) for field in event_schema]
                if "ts_code" in event_schema.names:
                    record["five_code_events"] = ds.dataset(path, format="parquet").to_table(
                        filter=ds.field("ts_code").isin(sorted(captured)), use_threads=False).to_pylist()
            check(item, hash_bytes=False)
        xdxr.append(record)
    traced = []
    for case in cases:
        code, day = case["code"], case["trade_date"]
        sources = {}
        for source, rows in captured[code].items():
            hit = [row for row in rows if row["trade_date"] == day]
            previous = [row for row in rows if row["trade_date"] < day]
            sources[source] = dict(exact_row=hit[0] if hit else None,
                                   previous_observed_source_row=previous[-1] if previous else None,
                                   binding=config["captured_sample_bytes"][code][source])
        for role, indexed in panel_rows.items():
            candidates = sorted((date, row) for (symbol, date), row in indexed.items() if symbol == code and date < day)
            sources[role] = dict(exact_row=indexed.get((code, day)),
                                 preceding_row_from_frozen_source_date_set=candidates[-1][1] if candidates else None,
                                 previous_panel_session_certified=False,
                                 source_binding=config["panels"][role])
        traced.append(dict(case=case, sources=sources,
                           reused_pair_values_as_csv_strings=comparisons[(code, day)],
                           lineage_status="OBSERVED_VALUES_AND_AVAILABLE_METADATA; EXACT_HISTORICAL_PRODUCER_TRANSFORM_UNPROVEN"))
    for binding in config["protected_pointers"]:
        check(binding)
    for binding in config["source_stat_guards"]:
        check(binding, hash_bytes=False)
    result = dict(schema="V194_SOURCE_ROW_TRACE_RESULT_V1", status="SOURCE_ROW_TRACE_READY_FOR_INDEPENDENT_REVIEW",
                  config_sha256=config_sha, code_sha256=sha(__file__), footers=footers,
                  cases=traced, xdxr_metadata=xdxr, captured_sample_files_reused=10,
                  source_archive_members_reopened=0, pairwise_probe_repeated=False,
                  elapsed_seconds=time.monotonic()-started, labels_computed=0, formula_evaluations=0,
                  model_fits=0, pointer_writes=0, **FLAGS)
    save(output / "RESULT.json", result)
    print(json.dumps(dict(status=result["status"], traced_keys=len(traced), model_fits=0)), flush=True)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--config-sha256", required=True)
    args = parser.parse_args()
    require(sha(args.config) == args.config_sha256, "TRACE_CONFIG_SHA_DRIFT")
    execute(json.loads(args.config.read_text()), args.config_sha256)


if __name__ == "__main__":
    main()
