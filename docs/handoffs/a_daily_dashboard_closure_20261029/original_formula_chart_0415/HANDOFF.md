# d35c original formula: three bound D29 chart projections

Frozen scope: `dashboard_resume_20261030/original_formula_chart_0415/SCOPE.json`.
Source baseline `310a8812af3962c5e1c0e0e2f91d147bdde40b5d`; only the new
`ops/render_original_formula_projection.py`, its focused test, and this handoff
directory were added. Existing dirty source and accepted code were preserved.

The script consumes SOURCE_CONFIG's exact d35c text and `ae4243…` original
interpreter, existing `coverage_247.json`, its hash-bound three-stock cache,
current product manifest/artifact/config/row references, and the original R19
HTML renderer pinned at `49bd460a…`. It does not read the native price panel,
fetch data, construct a new authoritative source, alter formulas/memberships,
or fill historical event-return coverage. All values are the pinned engine's
`json_ready` output; Decimal strings, false/null, all 51 names, all 22 IDs,
conditions, positions, payloads and styles are retained.

Results in the scope's artifact directory:

| Sample | Full available prefix rows | 51/22 retained | Unsupported drawing types |
| --- | ---: | --- | ---: |
| 600025.SH | 2150 | Every row | 0 |
| 000410.SZ | 7188 | Every row | 0 |
| 920454.BJ | 1201 | Every row | 0 |

The one-stock canary succeeded before the other two. Each has a complete
`*.projection.json`, self-contained `*.html`, and actual `*.actual.png`.
`MANIFEST.json` and `RESULT.json` bind output and input references/SHA. The
embedded renderer rows were checked equal to the lossless projection. Original
R19 `choose` and `paint` functions are byte-identical; only transport, D29 date,
candidate/lineage labels and the existing text checkbox default were adapted.

Actual headless Chrome readback separately checked each last date D29, full row
count, DOM 51-variable/22-drawing tables, enabled original text rendering,
nonempty canvas, and no page errors. All three PNGs were visually opened. The
120-row default views contain 242/249/208 triggered drawings respectively.
`ACTUAL_RENDER_READBACK.json` records browser closure and deletion of its own
temporary profile. No desktop/user profile was accessed, no service started,
and no browser dependency was installed.

Limits: the existing R19 palette and triangular icon representation are reused,
not certified as native TongDaXin visual equivalence. Dense original text
annotations overlap; they were not filtered or silently dropped. All full
prefix rows are retained, while the default screenshot shows the last 120.
Historical PIT, listing-lifetime completeness and full-condition historical
returns remain unconfirmed. The 247/all-market paths were not run.

Targeted tests: three methods passed; a fourth initially could not create its
new basetemp because the handoff parent did not exist. After creating that
owned directory, only that affected SHA/scope method ran and passed. Effective
four methods passed, covering exact values/types, all drawings, unsupported
type preservation/rejection, missing fields, pin drift, and the three-symbol
scope. The temporary fixture directory and this batch's bytecode files were
removed. No prior suite was rerun.

Writer handoff is not final acceptance. Root dispatches the single independent
Reviewer against the actual source, frozen scope, projection lineage and actual
three-chart evidence. No further calculation or rendering is needed by Writer.
No commit, push or deployment was performed.
