"""Fictional minimal example: presence is not exact, owner-verified support."""
import json

code = "SYNTH.00001"
required = {}
for n in range(1, 61):
    required[(f"FAKE_PRIOR_{n:02d}", "high")] = 1000 + n
required[("FAKE_SIGNAL", "close")] = 1200
for n in range(1, 7):
    required[(f"FAKE_TRADE_{n:02d}", "trade")] = 8000 + n

# Fake source values: six highs and three trade cells match; two trade cells
# are present but differ. The other 56 required cells are absent.
raw = {key: value for key, value in list(required.items())[:6]}
trade_keys = [key for key in required if key[1] == "trade"]
for key in trade_keys[:3]:
    raw[key] = required[key]
for delta, key in enumerate(trade_keys[3:5], start=7):
    raw[key] = required[key] + delta

presence = len(set(raw) & set(required))
exact = [key for key, value in raw.items() if key in required and value == required[key]]
mismatches = [key for key, value in raw.items() if key in required and value != required[key]]
missing = sorted(set(required) - set(raw))
unit_proven = False
source_proven = False
ready = (len(required) == 67 and len(exact) == 67 and not mismatches and not missing
         and unit_proven and source_proven)
result = {
    "classification": "SYNTHETIC_CODE_FIX_REPRO_ONLY",
    "code": code,
    "required_cells": len(required),
    "raw_presence": presence,
    "exact_matches": len(exact),
    "mismatches": len(mismatches),
    "missing": len(missing),
    "normalization_applied": False,
    "price_or_volume_unit_proven": unit_proven,
    "source_and_owner_proof": source_proven,
    "result": "PENDING" if not ready else "READY",
    "not_business_evidence": True,
}
assert (len(required), presence, len(exact), len(mismatches), len(missing)) == (67, 11, 9, 2, 56)
assert result["result"] == "PENDING"
print(json.dumps(result, sort_keys=True, indent=2))
