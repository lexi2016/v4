"""Fill missing hit names with the active selector's latest nonempty name through D."""
import csv
import json
from pathlib import Path

from project import DATE, OUT, configure, hfile, require, save_json


def main():
    result = json.loads((OUT / "RESULT.json").read_text())
    candidates = OUT / "CANDIDATES.csv"
    require(result["files"][candidates.name]["sha256"] == hfile(candidates), "CANDIDATE_INPUT_DRIFT")
    with candidates.open(encoding="utf-8-sig", newline="") as stream:
        table = csv.DictReader(stream)
        fields = table.fieldnames
        rows = list(table)
    missing = [row["symbol"] for row in rows if not row["name"]]
    data = configure()
    from ops.research_panel_daily_product import module, reference
    from ops.research_storage_pair import bind_shared_reader, request_binding

    names = {}
    with request_binding(data) as pair:
        require(pair.manifest == result["generation_pair"], "CURRENT_PAIR_CHANGED")
        ref = reference(data / "data_layer_interface_current/DATA_LAYER_INTERFACE.py")
        require(ref == result["identity"]["reader_provenance"]["actual_reader"], "READER_BYTES_CHANGED")
        reader = module(ref, "two_formula_name_reader")
        bind_shared_reader(reader, pair)
        if missing:
            history = reader.load_selector_ready(columns=["name"], ts_codes=missing,
                       end_date=str(DATE), panel_path=pair.paths["selector"])
            history = history.sort_values(["ts_code","trade_date"], kind="stable")
            for row in history.itertuples(index=False):
                if isinstance(row.name, str) and row.name.strip():
                    names[row.ts_code] = row.name.strip(), row.trade_date
        pair.assert_open()
        for row in rows:
            symbol = row["symbol"]
            if row["name"]:
                row["name_source_date"] = str(DATE)
                row["name_source_kind"] = "SELECTOR_D_NAME"
            elif symbol in names:
                row["name"], row["name_source_date"] = names[symbol]
                row["name_source_kind"] = "SELECTOR_LAST_NONEMPTY_NAME"
            else:
                row["name_source_date"] = ""
                row["name_source_kind"] = "CANNOT_CONFIRM"

    output = OUT / "CANDIDATES_NAMED.csv"
    with output.open("x", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=[*fields, "name_source_date", "name_source_kind"])
        writer.writeheader()
        writer.writerows(rows)
    save_json(OUT / "NAME_BINDING.json", {
        "source_candidates_sha256": hfile(candidates), "candidates_named_sha256": hfile(output),
        "source_selector_sha256": result["identity"]["selector_artifact_sha256"], "reader": ref,
        "initial_missing_count": len(missing), "same_reader_filled_count": len(names),
        "unresolved_symbols": [r["symbol"] for r in rows if not r["name"]],
        "naming_rule": "latest nonempty full-symbol name through D from the same Selector generation",
    })
    print(f"{len(rows)} rows, {len(names)} names filled from same-generation Reader, "
          f"{sum(not row['name'] for row in rows)} unresolved", flush=True)


if __name__ == "__main__":
    main()
