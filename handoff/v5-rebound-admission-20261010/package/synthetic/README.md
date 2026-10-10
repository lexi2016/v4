# Fictional cell audit reproduction

`synthetic_raw_cell_gate.py` creates a fake identifier (`SYNTH.00001`) and 67 required cells from invented labels and values. It includes 6 exact high matches, 3 exact trade matches, 2 mismatched trade values, and 56 absent cells. No real date, quote, code, source row, capture, or panel is read. It performs no normalization and outputs `PENDING` because exact coverage is incomplete and unit/source proofs are explicitly false.

Run with Python 3:

```sh
python3 -I -B synthetic/synthetic_raw_cell_gate.py
```

Expected output is captured in `../evidence/synthetic-run.json`. This is only an executable demonstration that raw-field presence is different from exact value support. It cannot establish or simulate real business admission.
