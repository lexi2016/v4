"""Export frozen outcome Top100 and raw192/technical-L2/194 membership; zero fit."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path


def load(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def key(row):
    return row["target_date"], row["code"]


def export(manifest_path, expected_sha, run_dir, output_dir):
    assert sha(manifest_path) == expected_sha, "MANIFEST_DRIFT"
    manifest = load(manifest_path)
    tables = {}
    for field in ("truth", "candidates"):
        item = manifest["files"][field]
        path = Path(item["path"])
        if not path.is_absolute():
            path = Path(manifest_path).parent / path
        assert sha(path) == item["sha256"], "INPUT_DRIFT"
        with path.open(newline="") as stream:
            tables[field] = list(csv.DictReader(stream))
    run_dir, output_dir = Path(run_dir), Path(output_dir)
    metrics = load(run_dir / "OOF_METRICS.json")
    dates = [row["target_date"] for row in metrics["daily"]]
    assert len(dates) == len(set(dates))
    truth = {key(row): row for row in tables["truth"]}
    assert len(truth) == len(tables["truth"]), "DUPLICATE_TRUTH"
    candidate_keys = {key(row) for row in tables["candidates"]}
    assert len(candidate_keys) == len(tables["candidates"])
    raw192 = {key(row) for row in tables["candidates"]
              if row["target_date"] in dates and float(row["tech_192"]) == 1}
    picks = {"technical_l2": load(run_dir / "baseline_OOF_TOP50.json"),
             "v194": load(run_dir / "candidate_OOF_TOP50.json")}
    selected = {arm: {key(row) for row in rows} for arm, rows in picks.items()}
    assert all(len(selected[arm]) == len(picks[arm]) for arm in picks)
    assert all(k in truth for k in raw192 | selected["technical_l2"] | selected["v194"])
    membership, counts, ranked_truth = [], [], {}
    for old in metrics["daily"]:
        date = old["target_date"]
        positive = [row for row in tables["truth"]
                    if row["target_date"] == date and float(row["label"]) == 1]
        assert len(positive) == old["truth_positive_denominator"] == 100
        assert all(math.isfinite(float(row["return"])) for row in positive)
        # Rank only the already frozen positive set; do not reselect its members.
        positive.sort(key=lambda row: (-float(row["return"]), row["code"]))
        for rank, row in enumerate(positive, 1):
            k = key(row)
            b, c = k in selected["technical_l2"], k in selected["v194"]
            relation = ("COMMON_HIT" if b and c else "NEW_HIT" if c else
                        "LOST_HIT" if b else "COMMON_MISS")
            membership.append(dict(target_date=date, outcome_top100_rank=rank,
                                   code=row["code"], name=row.get("stock_name", row.get("name", "")),
                                   return_value=row["return"], raw192_selected=k in raw192,
                                   technical_l2_top50_selected=b, v194_top50_selected=c,
                                   technical_l2_vs_v194_relation=relation))
            ranked_truth[k] = rank
        positives = {key(row) for row in positive}
        b = {k for k in selected["technical_l2"] if k[0] == date}
        c = {k for k in selected["v194"] if k[0] == date}
        raw = {k for k in raw192 if k[0] == date}
        record = dict(target_date=date, outcome_top100_count=100,
                      raw192_selected=len(raw), raw192_top100_hits=len(raw & positives),
                      technical_l2_selected=len(b), technical_l2_hits=len(b & positives),
                      v194_selected=len(c), v194_hits=len(c & positives),
                      common_hits=len(b & c & positives), new_hits=len((c - b) & positives),
                      lost_hits=len((b - c) & positives), delta_hits=len(c & positives) - len(b & positives))
        mapping = {"technical_l2_selected": "baseline_selected", "technical_l2_hits": "baseline_hits",
                   "v194_selected": "candidate_selected", "v194_hits": "candidate_hits",
                   "common_hits": "common_hits", "new_hits": "new_hits",
                   "lost_hits": "lost_hits", "delta_hits": "delta_hits"}
        assert all(record[new] == old[prior] for new, prior in mapping.items()), "SAVED_METRIC_PARITY"
        counts.append(record)
    output_dir.mkdir(exist_ok=False)

    def write(name, rows):
        with (output_dir / name).open("x", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    write("DAILY_TOP100_MEMBERSHIP.csv", membership)
    write("DAILY_MODEL_COUNTS.csv", counts)
    for arm, rows in picks.items():
        records = []
        for row in rows:
            outcome = truth[key(row)]
            records.append(dict(target_date=row["target_date"], model_rank=row["rank"],
                                code=row["code"], name=outcome.get("stock_name", outcome.get("name", "")),
                                score=row["score"], return_value=outcome["return"],
                                outcome_top100_rank=ranked_truth.get(key(row), "")))
        write("DAILY_" + arm.upper() + "_TOP50.csv", records)
    raw_records = [dict(target_date=k[0], code=k[1], name=truth[k].get("stock_name", truth[k].get("name", "")),
                        return_value=truth[k]["return"], outcome_top100_rank=ranked_truth.get(k, ""))
                   for k in sorted(raw192)]
    assert raw_records, "NO_RAW192_RECORDS"
    write("DAILY_RAW192_NATURAL.csv", raw_records)
    receipt = dict(schema="V194_FROZEN_DAILY_TOP100_DISPLAY_RECEIPT_R1", dates=dates,
                   outcome_membership_rows=len(membership), raw192_rows=len(raw_records),
                   raw192_definition="Frozen candidate.tech_192==1; no TopN and no fill",
                   technical_l2_definition="Frozen technical11 L2 Top50; not raw192 natural list",
                   v194_definition="Frozen technical11+source L2 Top50",
                   bound_name_available=False, name_note="Frozen inputs contain no bound names; empty names, no lookup",
                   top100_labels_recomputed=False, new_fits=0, new_fetches=0,
                   files={q.name: {"sha256": sha(q), "bytes": q.stat().st_size}
                          for q in output_dir.iterdir() if q.is_file()},
                   research_only=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
    with (output_dir / "EXPORT_RECEIPT.json").open("x") as stream:
        json.dump(receipt, stream, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return counts


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("manifest", "manifest-sha256", "run-dir", "output-dir"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    print(json.dumps(export(args.manifest, args.manifest_sha256, args.run_dir, args.output_dir)))
