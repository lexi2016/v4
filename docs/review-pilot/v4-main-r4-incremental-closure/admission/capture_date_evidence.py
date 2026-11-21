"""Capture exact, limited source ranges after checking the full source SHA."""
import hashlib
import json
from pathlib import Path
import re
import sys


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read_verified(aliases, alias_path, expected):
    alias, relative = alias_path.split("/", 1)
    path = Path(aliases[alias]) / relative
    raw = path.read_bytes()
    if sha(raw) != expected:
        raise ValueError(f"Date evidence changed: {alias_path}")
    return raw


def pick_fields(raw, fields):
    def unique_pairs(pairs):
        data = dict(pairs)
        if len(data) != len(pairs):
            raise ValueError("Duplicate JSON keys in date evidence")
        return data

    document = json.loads(raw, object_pairs_hook=unique_pairs)
    selected = {}
    for field in fields:
        for match in re.finditer(rb'(?m)^  "' + field.encode() + rb'": .+?(?=\r?$)', raw):
            line = match.group().strip()
            if json.loads(b"{" + line.removesuffix(b",") + b"}")[field] != document[field]:
                continue
            selected[field] = {"offset": match.start(), "length": len(match[0]),
                               "source_text": match[0].decode()}
    if set(selected) != set(fields):
        raise ValueError(f"Could not bind source ranges for {set(fields) - set(selected)}")
    return selected


def main():
    path, destination = map(Path, sys.argv[1:])
    scope = json.loads(path.read_bytes())
    aliases = scope["path_aliases"]
    dates = scope["date_semantics_and_row_validation"]
    fields = ("schema", "target_date", "asof_date", "generation_id", "input_sha256", "run_dir", "status")
    references = []
    for row in [*dates["D20"]["owner_receipts"], dates["D11"]["owner_receipt"]]:
        for key in ("candidate_receipt", "stage_status"):
            if key + "_ref" not in row:
                continue
            references.append((row[key + "_ref"], row[key + "_sha256"], fields))
    failed = dates["D11"]["contemporaneous_run_evidence"]
    references.append((failed["failed_run_ledger_ref"], failed["failed_run_ledger_sha256"],
                       ("run", "status", "retry_started", "checkpoint_files")))
    args = dates["D20"]["historical_key_derivation"]
    records = []
    for reference, expected_sha, fields in references:
        raw = read_verified(aliases, reference, expected_sha)
        portions = pick_fields(raw, fields)
        records.append({"source": reference, "source_size": len(raw), "source_sha256": expected_sha,
                        "source_ranges": portions})
    prepare = read_verified(aliases, args["runner_args_ref"], args["runner_args_sha256"])
    prepare_json = json.loads(prepare)
    expected_dates = [prepare_json[name]["target_date"] for name in ("candidate", "original_d20_runner")]
    if expected_dates != [20261120, 20261120]:
        raise ValueError("Unexpected D20 prepare args date")
    matches = list(re.finditer(rb'"target_date":20261120(?=[,}])', prepare))
    status = b'"status":' + json.dumps(prepare_json["status"]).encode()
    if len(matches) != 2 or prepare.count(status) != 1:
        raise ValueError("Unexpected D20 prepare args byte ranges")
    records.append({"source":args["runner_args_ref"], "source_size":len(prepare),
                    "source_sha256":args["runner_args_sha256"],
                    "source_ranges": {
                        "target_dates":[{"offset":m.start(), "length":len(m[0]), "source_text":m[0].decode()}
                                        for m in matches],
                        "status":{"offset":prepare.index(status), "length":len(status), "source_text":status.decode()}
                    }})
    with destination.open("x") as out:
        json.dump({"schema":"v4.r4_incr.date_source_ranges.v1",
                   "scope_evidence_sha256":sha(path.read_bytes()), "source_records":records,
                   "full_source_bytes_included":False}, out, indent=2, ensure_ascii=False)
        out.write("\n")


if __name__ == "__main__":
    main()
