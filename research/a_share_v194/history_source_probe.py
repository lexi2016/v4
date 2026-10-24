"""Registered, bounded source comparison; no labels, formula, fit or promotion.

The .day codec matches the active formula producer's read_day_tail: native
integer OHLC / 100, float amount, integer volume unchanged. Ratios below are
observations only; this probe never converts volume or adjusts price history.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import struct
import time
import zipfile
from contextlib import nullcontext
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

DAY = struct.Struct("<IIIIIfII")
FIELDS = ("open", "high", "low", "close", "amount", "vol")
COLUMNS = ("ts_code", "trade_date", *FIELDS)
FLAGS = dict(research_only=True, production_allowed=False,
             buy_gate_updated=False, orders_sent=False)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_stat(path: str | Path) -> dict[str, int]:
    st = Path(path).stat()
    return dict(size=st.st_size, mtime_ns=st.st_mtime_ns, inode=st.st_ino)


def check_stat(binding: dict[str, Any]) -> None:
    require(file_stat(binding["path"]) == binding["stat"], "SOURCE_STAT_DRIFT:" + binding["path"])


def write_new(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def save_new(path: Path, obj: Any) -> None:
    write_new(path, (json.dumps(obj, ensure_ascii=False, sort_keys=True,
                               indent=2, allow_nan=False) + "\n").encode("utf-8"))


def decode_day(data: bytes, code: str) -> list[dict[str, Any]]:
    require(len(data) % DAY.size == 0, "DAY_TRAILING_BYTES:" + code)
    result = []
    previous = 0
    for day, op, hi, lo, close, amount, volume, _reserved in DAY.iter_unpack(data):
        require(day > previous, "DAY_DATE_NOT_SORTED_UNIQUE:" + code)
        text = str(day)
        require(len(text) == 8, "DAY_DATE_INVALID:" + code)
        date(int(text[:4]), int(text[4:6]), int(text[6:]))
        previous = day
        values = dict(open=op / 100.0, high=hi / 100.0, low=lo / 100.0,
                      close=close / 100.0, amount=float(amount), vol=int(volume))
        require(all(math.isfinite(float(value)) for value in values.values()), "DAY_NONFINITE:" + code)
        result.append(dict(ts_code=code, trade_date=day, **values))
    return result


def coverage(rows: list[dict[str, Any]]) -> dict[str, Any]:
    dates = [int(row["trade_date"]) for row in rows]
    require(dates == sorted(set(dates)), "SOURCE_DATE_NOT_SORTED_UNIQUE")
    invalid_ohlc = sum(not (min(row[field] for field in ("open", "high", "low", "close")) > 0
                           and row["low"] <= min(row["open"], row["close"])
                           <= max(row["open"], row["close"]) <= row["high"]) for row in rows)
    return dict(rows=len(rows), first_date=min(dates) if dates else None,
                last_date=max(dates) if dates else None, invalid_ohlc_rows=invalid_ohlc)


def float32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", value))[0]


def compare_rows(left: list[dict[str, Any]], right: list[dict[str, Any]], *,
                 code: str, left_name: str, right_name: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    a = {int(row["trade_date"]): row for row in left}
    b = {int(row["trade_date"]): row for row in right}
    require(len(a) == len(left) and len(b) == len(right), "OVERLAP_DUPLICATE_DATE")
    common = sorted(a.keys() & b.keys())
    counts = {field: dict(exact_equal=0, equal_after_both_float32=0,
                         different_after_both_float32=0) for field in FIELDS}
    ratios = []
    volume = dict(equal=0, right_equals_left_times_100=0, right_equals_left_div_100=0)
    differences = []
    for day in common:
        changed = []
        for field in FIELDS:
            x, y = float(a[day][field]), float(b[day][field])
            require(math.isfinite(x) and math.isfinite(y), "OVERLAP_NONFINITE")
            counts[field]["exact_equal"] += int(x == y)
            same32 = float32(x) == float32(y)
            counts[field]["equal_after_both_float32"] += int(same32)
            counts[field]["different_after_both_float32"] += int(not same32)
            if not same32:
                changed.append(field)
        x, y = float(a[day]["vol"]), float(b[day]["vol"])
        volume["equal"] += int(float32(x) == float32(y))
        volume["right_equals_left_times_100"] += int(x != 0 and float32(x * 100) == float32(y))
        volume["right_equals_left_div_100"] += int(x != 0 and float32(x / 100) == float32(y))
        if a[day]["close"] > 0:
            ratios.append(float(b[day]["close"]) / float(a[day]["close"]))
        if changed:
            differences.append(dict(code=code, trade_date=day, left=left_name, right=right_name,
                                    different_fields="|".join(changed),
                                    **{"left_" + field: a[day][field] for field in FIELDS},
                                    **{"right_" + field: b[day][field] for field in FIELDS}))
    ratios.sort()
    return dict(code=code, left=left_name, right=right_name,
                overlap_rows=len(common), overlap_first=min(common) if common else None,
                overlap_last=max(common) if common else None,
                left_only_rows=len(a.keys() - b.keys()), right_only_rows=len(b.keys() - a.keys()),
                field_counts=counts, volume_ratio_observations=volume,
                close_right_over_left=dict(min=min(ratios), median=ratios[len(ratios)//2], max=max(ratios)) if ratios else None,
                conflict_rows=len(differences),
                adjustment_verdict="CANNOT_CONFIRM_FROM_PAIRWISE_PARITY_ALONE"), differences


def read_panel(binding: dict[str, Any], codes: list[str]) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    import pyarrow.dataset as ds
    import pyarrow.parquet as pq
    check_stat(binding)
    parquet = pq.ParquetFile(binding["path"])
    schema = parquet.schema_arrow
    volume_field = binding["volume_field"]
    require(volume_field in {"vol", "volume"}, "PANEL_VOLUME_FIELD_NOT_EXPLICIT_SUPPORTED_ALIAS")
    columns = [volume_field if field == "vol" else field for field in COLUMNS]
    require(all(schema.names.count(field) == 1 for field in columns), "PANEL_REQUIRED_COLUMNS_MISSING")
    metadata = dict(rows=parquet.metadata.num_rows, row_groups=parquet.metadata.num_row_groups,
                    required_column_types={field: str(schema.field(field).type) for field in columns},
                    volume_field=volume_field, volume_conversion="COLUMN_RENAME_ONLY_VALUE_UNCHANGED")
    parquet.close()
    table = ds.dataset(binding["path"], format="parquet").to_table(
        columns=columns, filter=ds.field("ts_code").isin(codes), use_threads=False)
    table = table.rename_columns(list(COLUMNS))
    by_code = {code: [] for code in codes}
    for row in table.to_pylist():
        code = str(row["ts_code"])
        require(code in by_code, "PANEL_FILTER_DRIFT")
        require(all(row[field] is not None and math.isfinite(float(row[field])) for field in FIELDS),
                "PANEL_NONFINITE_SAMPLE:" + code)
        row["trade_date"] = int(str(row["trade_date"]).replace("-", ""))
        by_code[code].append(row)
    for rows in by_code.values():
        rows.sort(key=lambda row: row["trade_date"])
        coverage(rows)
    metadata["filtered_sample_rows"] = table.num_rows
    check_stat(binding)
    return by_code, metadata


def validate_pointers(config: dict[str, Any]) -> None:
    for binding in config["panels"].values():
        pointer = Path(binding["pointer_path"])
        raw = pointer.read_bytes()
        require(sha_bytes(raw) == binding["pointer_sha256"], "PANEL_POINTER_SHA_DRIFT")
        require(raw.decode("utf-8-sig").strip() == binding["path"], "PANEL_POINTER_TARGET_DRIFT")
        check_stat(binding)


def execute(config: dict[str, Any], config_sha: str) -> dict[str, Any]:
    require(config["schema"] == "V194_HISTORY_SOURCE_PROBE_CONFIG_V1", "CONFIG_SCHEMA_DRIFT")
    require(config.get("safety_flags") == FLAGS, "UNSAFE_FLAGS")
    samples = config["samples"]
    codes = [sample["code"] for sample in samples]
    require(1 <= len(samples) <= 6 and len(codes) == len(set(codes)), "SAMPLE_SCOPE_INVALID")
    output = Path(config["output_dir"])
    require(not output.exists(), "PROBE_OUTPUT_EXISTS_NO_RETRY")
    for binding in config["metadata_bindings"]:
        require(sha_file(binding["path"]) == binding["sha256"], "METADATA_SHA_DRIFT:" + binding["path"])
    require(sha_file(config["producer"]["path"]) == config["producer"]["sha256"], "PRODUCER_SOURCE_SHA_DRIFT")
    validate_pointers(config)
    check_stat(config["archive"])
    for sample in samples:
        if sample["native"] is not None:
            check_stat(sample["native"])
    output.mkdir(parents=True)
    save_new(output / "START_OBSERVATION.json", dict(pid=os.getpid(), started_at=datetime.now(timezone.utc).isoformat(),
             config_sha256=config_sha, code_sha256=sha_file(__file__), input_snapshot=config, **FLAGS))
    started = time.monotonic()
    sources: dict[str, dict[str, list[dict[str, Any]]]] = {code: {} for code in codes}
    source_receipts = []
    reused_bytes = config.get("sample_bytes_reuse")
    # R2 reuses the captured R1 bytes. Original archive/native inputs receive
    # their frozen stat guards but are not reopened or numerically reread.
    archive_context = nullcontext(None) if reused_bytes is not None else zipfile.ZipFile(config["archive"]["path"], "r")
    with archive_context as archive:
        for sample in samples:
            code = sample["code"]
            archive_reuse = reused_bytes[code]["archive"] if reused_bytes is not None else None
            if archive_reuse is None:
                payload = archive.read(sample["archive_member"])
            else:
                payload = Path(archive_reuse["path"]).read_bytes()
                require(sha_bytes(payload) == archive_reuse["sha256"], "REUSED_SAMPLE_SHA_DRIFT:" + code + ":archive")
            digest = sha_bytes(payload)
            require(digest == sample["archive_member_sha256"], "ARCHIVE_MEMBER_SHA_DRIFT:" + code)
            sources[code]["archive"] = decode_day(payload, code)
            write_new(output / "original_sample_bytes" / (code + ".archive.day"), payload)
            source_receipts.append(dict(code=code, source="archive", member=sample["archive_member"],
                                       reused_sample_bytes=archive_reuse,
                                       sha256=digest, bytes=len(payload), **coverage(sources[code]["archive"])))
            if sample["native"] is not None:
                path = Path(sample["native"]["path"])
                native_reuse = reused_bytes[code]["native"] if reused_bytes is not None else None
                if native_reuse is None:
                    payload = path.read_bytes()
                else:
                    payload = Path(native_reuse["path"]).read_bytes()
                    require(sha_bytes(payload) == native_reuse["sha256"], "REUSED_SAMPLE_SHA_DRIFT:" + code + ":native")
                check_stat(sample["native"])
                sources[code]["native"] = decode_day(payload, code)
                write_new(output / "original_sample_bytes" / (code + ".native.day"), payload)
                source_receipts.append(dict(code=code, source="native", path=str(path),
                                           reused_sample_bytes=native_reuse,
                                           sha256=sha_bytes(payload), bytes=len(payload), **coverage(sources[code]["native"])))
            else:
                source_receipts.append(dict(code=code, source="native", status="MISSING_AT_CONFIG_FREEZE"))
    panel_metadata = {}
    for role, binding in config["panels"].items():
        rows, metadata = read_panel(binding, codes)
        panel_metadata[role] = metadata
        for code in codes:
            sources[code][role] = rows[code]
            encoded = json.dumps(rows[code], sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
            source_receipts.append(dict(code=code, source=role, sample_rows_sha256=sha_bytes(encoded), **coverage(rows[code])))
    comparisons = []
    differences = []
    for code, source in sources.items():
        names = list(source)
        for i, left in enumerate(names):
            for right in names[i + 1:]:
                summary, rows = compare_rows(source[left], source[right], code=code, left_name=left, right_name=right)
                comparisons.append(summary)
                differences.extend(rows)
    buffer = io.StringIO(newline="")
    columns = ["code", "trade_date", "left", "right", "different_fields",
               *("left_" + field for field in FIELDS), *("right_" + field for field in FIELDS)]
    writer = csv.DictWriter(buffer, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(differences)
    write_new(output / "OVERLAP_CONFLICTS.csv", buffer.getvalue().encode("utf-8"))
    validate_pointers(config)
    check_stat(config["archive"])
    for sample in samples:
        if sample["native"] is not None:
            check_stat(sample["native"])
    result = dict(schema="V194_HISTORY_SOURCE_PROBE_RESULT_V1", status="SOURCE_OBSERVATIONS_READY_FOR_INDEPENDENT_REVIEW",
                  config_sha256=config_sha, code_sha256=sha_file(__file__), elapsed_seconds=time.monotonic()-started,
                  pid=os.getpid(), archive_full_sha256=config["archive"]["prior_receipt_sha256"],
                  archive_full_sha256_basis="REUSED_TRANSFER_RECEIPT_NOT_REHASHED; EACH_READ_MEMBER_SHA_VERIFIED",
                  source_receipts=source_receipts, panel_metadata=panel_metadata, comparisons=comparisons,
                  conflicts=dict(path=str(output / "OVERLAP_CONFLICTS.csv"), rows=len(differences),
                                 sha256=sha_file(output / "OVERLAP_CONFLICTS.csv")),
                  producer_codec="<IIIIIfII; OHLC/100; AMOUNT_FLOAT_UNCHANGED; VOL_UINT_UNCHANGED",
                  original_sample_sources_numerically_reread=0 if reused_bytes is not None else len(source_receipts),
                  captured_sample_bytes_reused=2 * len(samples) if reused_bytes is not None else 0,
                  panel_read_policy=config.get("panel_read_policy", "FIRST_REQUIRED_COLUMN_SAMPLE_READ"),
                  adjustment_status="CANNOT_CONFIRM_PENDING_INDEPENDENT_SOURCE_SEMANTICS_REVIEW",
                  source_mutations=0, pointers_updated=0, formula_evaluations=0, labels_computed=0,
                  model_objects_created=0, model_fits=0, predictions=0, **FLAGS)
    save_new(output / "RESULT.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--config-sha256", required=True)
    args = parser.parse_args()
    raw = args.config.read_bytes()
    require(sha_bytes(raw) == args.config_sha256, "CONFIG_SHA_DRIFT")
    result = execute(json.loads(raw), args.config_sha256)
    print(json.dumps(dict(status=result["status"], comparisons=len(result["comparisons"]),
                          model_fits=0, labels_computed=0), sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
