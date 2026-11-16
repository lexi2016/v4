# Exact ChiNext IPO seed boundary

The default cross-day ratio gate quarantined the frozen native history for 301686.SZ at its first two listed sessions. The scoped IPO exception checks the externally pinned evidence for that symbol and dated boundary, the exact issuer notice URL and SHA-256, five official TDX records, the calendar references, and the unchanged native prefix. The existing owner still validates incoming rows and every later ratio. The clean-room overlay reads the exact boundary prices from the evidence, so this branch can be tested with synthetic inputs and contains no market quote payloads.

| Source identity | SHA-256 |
| --- | --- |
| Required original R3 progress module | `9ecb89c1a418d1188a7bd48904db96c9bb5dff5202fdf0ffac2e5955edeb4deb` |
| Result of applying the shared overlay | `9429274d8759a4c923df4c05479979d965a1e045e06c700eb32f9ce96c699d8e` |
| Shared overlay patch | `5a8d9d11e3ebdb6ce096ef575343de99c4a7d066ddbb3d5b2669529ea598fcb4` |
| Separately retained reviewed local module | `8ae3ad31d58680f053110175ae6c5e1403584097cc1ac0749f7e4bf6dea32788` |

Apply the patch to the exact original R3 module. The inherited source tree uses a different preimage. The reviewed local module remains available under its own identity.

Run the eleven portable tests with the project Python.

```sh
"$PANEL_PYTHON" -B -m pytest -q -p no:cacheprovider tests/test_a_daily_301686_seed_overlay.py
```

Both versions passed an isolated one-stock replay with the archived official packages. The existing owner appended two accepted daily records, preserved the prior native bytes, and refused thirteen out-of-scope mutations. The Git branch carries neither the required local evidence nor its launch configuration. This was an offline test and does not change the installed role or canonical panel.
