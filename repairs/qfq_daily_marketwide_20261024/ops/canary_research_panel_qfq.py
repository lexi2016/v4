"""Isolated two-symbol original-formula canary. Never writes panel CURRENT."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import zipfile

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from ops.research_panel_factor_cache import _event_rows
from ops import research_panel_qfq as qfq


def run(binding_path: Path, output_dir: Path) -> dict:
    binding = json.loads(binding_path.read_text())
    if binding.get("schema") != "original_daily_qfq_two_symbol_canary_v1" or set(binding["symbols"]) != {"002612.SZ", "001283.SZ"}:
        raise qfq.QfqGateError("CANARY_FROZEN_SCOPE_INVALID")
    if binding.get("overlap_policy") != "ARCHIVE_AUTHORITATIVE_CURRENT_POSTFIX_V1":
        raise qfq.QfqGateError("CANARY_RAW_OVERLAP_POLICY_UNBOUND")
    root = Path(__file__).resolve().parent / "vendor"
    driver, _ = qfq.authorities(root / "data_layer_daily_formula_increment_update_v1.py", root / "build_canonical_formula_research_panel.py")
    output_dir.mkdir(parents=True, exist_ok=True)
    results, checked_archives = {}, set()
    for code, item in binding["symbols"].items():
        archive_ref = item["archive"]
        archive_path = Path(archive_ref["path"])
        if archive_path not in checked_archives:
            qfq._source(archive_ref, owner="native TDX archive")
            checked_archives.add(archive_path)
        with zipfile.ZipFile(archive_path) as archive:
            data = archive.read(archive_ref["member"])
        native = output_dir / "native_source_bytes" / (code + ".day")
        qfq._write(native, data)
        if qfq.sha(native) != archive_ref["member_sha256"]:
            raise qfq.QfqGateError(f"CANARY_NATIVE_MEMBER_HASH_MISMATCH:{code}")
        archived = driver.read_day_tail(code, native, tail_records=len(data) // driver.DAY_STRUCT.size)
        archive_max = int(archived.trade_date.max())
        live = {**item["live"], "from_date_exclusive": archive_max}
        factor_path = qfq._source(item["factor_csv"], owner=code)
        factor_rows = json.loads(pd.read_csv(factor_path).to_json(orient="records", double_precision=15))
        start = int(archived.trade_date.min())
        symbol = dict(raw_files=[dict(path=str(native), sha256=qfq.sha(native)), live], history_start_date=start,
                      events=_event_rows(factor_rows, int(binding["asof_date"]), start))
        computed = qfq.rebuild_symbol(code, symbol, int(binding["asof_date"]), driver)
        columns = ["ts_code", "trade_date", "open", "high", "low", "close", "volume", "pre_close", "BBI", "zge_white_line", "zge_yellow_line", "ma60", "J", "B1", "B2", "B3"]
        target = output_dir / (code + "_original_producer_canary.csv")
        computed[columns].to_csv(target, index=False)
        dates = binding["verification_dates"][code]
        selected = computed.loc[computed.trade_date.isin(dates), columns]
        if set(selected.trade_date.astype(int)) != set(dates):
            raise qfq.QfqGateError(f"CANARY_REQUIRED_SIGNAL_DATES_MISSING:{code}")
        results[code] = dict(path=str(target), sha256=qfq.sha(target), archive_prefix_end=archive_max,
                             rows=len(computed), samples=json.loads(selected.to_json(orient="records", double_precision=15)))
    receipt = dict(status="CANARY_COMPUTED_NOT_ACCEPTED", scope="ORIGINAL_PRODUCER_TWO_SYMBOL_SOFTWARE_CANARY_NOT_MARKET_COVERAGE",
                   binding_path=str(binding_path), binding_sha256=qfq.sha(binding_path), asof_date=binding["asof_date"],
                   driver_sha256=qfq.DRIVER_SHA, formula_sha256=qfq.FORMULA_SHA, symbols=results, **qfq.FLAGS)
    qfq._json(output_dir / "canary_receipt.json", receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.binding, args.output_dir)
    print(json.dumps(dict(status=result["status"], output_dir=str(args.output_dir)), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
