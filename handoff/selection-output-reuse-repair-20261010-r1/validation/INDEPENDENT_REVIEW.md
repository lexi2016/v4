# Independent review — three local repairs in two production files

## Verdict

**Final two-file production delta, covering three defects: no Critical or Important defect found; acceptable as narrowly scoped local repairs. It does not establish the cause or recovery of the missing real 20261009 / 2026-10-08 selection product.**

The reviewed source assembly is not a Git checkout. The fixed reference commit is `lexi2016/v4 e72607634d46146b0b6c0f4a0396f6b2939589f7`. The original files come from the supplied historical runner and current consumer snapshots, respectively. No production file, input artifact, service configuration, collector, publisher, Mac session, or live owner state was changed by this review. This report and its test logs are audit outputs only.

One separate Important diagnostic-tool issue and one Minor metadata-projection issue were found in the initial `inspect_connect_metadata.py` / recipe. **Both were corrected and independently re-reviewed; both are closed.** The diagnostic tool is acceptable for the stated local metadata-inspection purpose. Its synthetic checks are not live authority or selection acceptance.

## Source identities

| File | Before SHA-256 | Reviewed after SHA-256 |
|---|---|---|
| `app/ops/run_manager_daily_announcement.py` | `bfb853fb982e0b2da1024fa942ae9dc5d67fa88a8d112f46054608641129c1ee` | `a50bd2dc9bfe4bc671348d1bb3bacb54810db4d377abefb236689b0e6c2353e3` |
| `app/v4/manager_research/workspace_plan.py` | `881599ba5a68badd7e18271c57666937f3e954088dfcfcb4c827dcf99419be7f` | `89d2f93201aa5284ab4d7bde5d9facc73834057d1d9cf7f9bbd6cd4ca5b95c3d` |

Final reviewed test-file identities:

- `repair_tests/test_selection_reuse_announcement.py`: `b841ff113e88569e162c9aab00e0112aba5b3d24714721ca88b9acb8c4a758d1`.
- `repair_tests/test_selection_reuse_oversold.py`: `001efa2a9b7020d801a210353ff106fabf40cf57c657b9b0a053fc1c84f75467`.
- `repair_tests/test_selection_reuse_readback.py`: `9130d0ccf876af0a5269aee840d0d64c709255d59300f6638b4e21b643a9e640`.

## Production review findings

### Critical

None found in the reviewed two-file delta.

### Important

None found in the reviewed two-file delta. The missing live inputs remain an acceptance limitation, not a reason to bypass a validator or manufacture a product.

### Minor — floating-point presentation retains its existing precision limit

`workspace_plan.py` lines 1276–1279 compare the decimal values, while lines 1352 and 1382 convert the cutoff back to `float` for the existing output contract. Both presentation fields derive from the same cutoff, but an exact Decimal value need not survive the float conversion.

Reproduced synthetic example:

| Field | Value |
|---|---:|
| `prior60_high` | `0.3500000000000001` |
| `close` | `0.2800000000000001` |
| exact Decimal cutoff | `0.28000000000000008` |
| output float cutoff | `0.2800000000000001` |
| `oversold_flag` | `False` |

The decision is correct under the chosen decimal rule, while the float display can appear equal to close. This is a non-blocking high-precision display limitation; it does not justify broadening this patch or the API schema. Describe the change as using the same cutoff source for comparison and existing float presentation. Do not claim that every possible input precision is displayed exactly.

## Why the announcement patch is correct and bounded

At `run_manager_daily_announcement.py` lines 152–163, the receipt is validated against the original source manifest and explicit normalized decisions, added to the product, and included in the final base identity. The already validated selection extension is removed temporarily; the base is resealed; the same `article_decisions` are passed through the existing `make_extension` and `attach_extension`; the receipt is validated again before exclusive output writing.

This matches the existing successful order in `_register_handoff`, lines 597–613. There is no replacement stock-selection algorithm, fabricated decision, or parallel producer. The original `make_extension` validates the exact article set, count, record SHAs, issuer identities, disposition, and basis (`announcement_selection.py` lines 62–150). The original projection validator still requires:

- the extension's own digest;
- `base_product_sha256 == digest(product without sha256 and stock_selection)`;
- unchanged source-manifest identity and source binding;
- exact article decision bindings.

Those checks remain in `announcement_selection.py` lines 166–213. Receipt validation at `workspace_announcements.py` lines 1714–1763 still binds target/publication dates, semantic/body/catalog SHAs, explicit decision count and digest, reader/reviewer identities, review conclusion, receipt digest, and all four research-only flags. No check was removed or weakened.

The regenerated extension uses decisions that have already passed the original normalization and validation path. It changes the extension's base identity after the receipt is included; it does not change any disposition. The final product equals the original registered-handoff product for selected, conditional-watch, not-selected, not-assessed-content, and no-decisions cases. No-decisions continues to mean unassessed, rather than an empty reviewed selection.

The import test uses the original registered handoff as authority and compares its product SHA to the rebuilt product. It does not import an unregistered candidate file or bypass review registration. A build-only repair is therefore not proof that an absent live handoff has been recovered. `_register_handoff` was already ordered correctly before this patch.

## Why the additional CLI readback repair is correct and bounded

The final runner also reuses the existing `_readback` implementation from the fixed reference commit's `handoff/manager-three-channel-repair-20261009/after/api_r3_candidate/ops/run_manager_daily_announcement.py`. The full reference file SHA is `aee0e5c31f30b296864a7ad81263fbc748b65cb9b4d443f83a756019cbc94a38`. Independent comparison confirms that the final `_readback` function is verbatim equal to that reference; the function including one terminal newline has SHA `4d204abb797a968cb8616de41b98a5c0f74698144f47df0041105b48a89a880e`.

The old wrapper constructed a three-field pseudo-product containing only target date, publication date and product SHA, then called the validator intended for a full product. The current API's valid owner receipt contains a complete group of four handoff identities. `validate_owner_analysis_import_receipt` correctly requires a product's raw judgment and manifest to check that group (`workspace_announcements.py` lines 2172–2188); the pseudo-product lacks them, so the old wrapper rejects a valid current response with `ANNOUNCEMENT_OWNER_IMPORT_RECEIPT_HANDOFF_BINDING_INVALID`.

The replacement calls the already existing `validate_owner_analysis_readback(result)` at runner line 651 and adds its import. It removes no validation rule. That consumer validator (`workspace_announcements.py` lines 2192–2263) was specifically written for the API projection, which does not contain the raw judgment. It verifies the complete analysis/receipt/consumption-validation/source-catalog chain, its statuses and flags, product and manifest digests, catalog run and SHA, evidence/handoff/judgment identities, receipt digest and persisted availability. The full product, reviewer artifacts and handoff remain validated by the original owner API. `_import` still calls the full-product import-receipt validator with an actual product; it was not switched to the projection validator.

The wrapper retains its exact requested target/publication checks and verifies the resulting product identity. It still performs the same GET through the existing loopback transport. No new endpoint, producer, approval shortcut, legacy-file rewrite or source data is introduced.

The ten added cases use the real TestClient owner routes and synthetic registered inputs: one valid current receipt, eight missing/unverified/mismatched chain cases, and one older-schema receipt whose existing bytes remain unchanged. All ten pass after the change. The older-schema case still requires the API's current full handoff validation and explicit legacy binding status; it does not use another day's product or upgrade a stored receipt. This CLI result attests current owner readback consistency, not historical pre-cutoff plan availability or successful live workspace selection.

## Why the oversold patch is correct and bounded

The original expression `close <= 0.8 * prior60_high` rejects decimal equalities such as 0.28 / 0.35 because the binary float multiplication produces `0.27999999999999997`. The patch converts the existing ratio and already validated numerical values through `Decimal(str(...))`. It preserves the inclusive comparison and introduces no epsilon, tolerance, new candidate source, or relaxed price rule.

`_screen_number` at `workspace_plan.py` lines 569–578 rejects booleans, non-finite values, and non-positive prices before the new comparison. `prior60_high` remains available only after the complete set of 60 valid, non-duplicated prior-session highs is established. Independent in-memory checks of close/high separately equal to `None`, `NaN`, `+inf`, `-inf`, `0`, and `-1` covered 12 invalid-value scenarios: all remained pending with `oversold_flag=None`; an invalid prior high also left cutoff unknown.

The existing volume comparison is unchanged. The tests retain `NOT_PROVEN` unit/scale evidence; every numeric scenario remains pending with no strict/near/card selection. Consequently these tests cannot demonstrate that a live volume owner attestation exists or that the current 693 pending rows are recoverable through this arithmetic repair.

The five committed numerical tests exercise the actual `read_rebound_screen` with explicitly synthetic calendar, file, and owner boundaries. They cover the two decimal equalities, a value above the first boundary, a value below it, and missing close. They do not exercise an owner-verified volume path or the near-candidate branch. They also do not establish market-session authenticity; their synthetic date tokens are explicitly marked as test inputs.

## Independent final 25-case execution

The final fixture includes both the API clock seam and the persisted historical-fixture file snapshot. The clock is patched only in tests; the original production cutoff check remains intact.

| Execution | Result | Evidence |
|---|---|---|
| Original `_build`, `_readback`, and `read_rebound_screen` bodies, replayed in memory against the final fixtures | **8 failed, 17 passed**, one dependency warning, 1.63s | `independent_before_25_final.log` |
| Final reviewed production files against the same final fixtures | **25 passed**, one dependency warning, 1.65s | `independent_after_25_final.log` |

The earlier two-defect stage is retained as separate evidence: `independent_before_final_fixture.log` contains **7 failed / 8 passed**, and `independent_after_final_fixture.log` contains **15 passed**. At that stage the runner SHA was `1e92182c63721b4bdd2e8efeb31a404ac767f11785b0d370cba15d514c1bb16f`; the additional readback test file and repair were not yet present. These stage results are not substituted for the final 25-case results.

The original-function failures are specific:

1. Four announcement disposition cases fail in original `read_projection` with `ANNOUNCEMENT_SELECTION_BASE_PRODUCT_SHA_MISMATCH`.
2. The announcement API/repeated-read case fails first at rebuilt-product equality with the original registered-handoff product.
3. The two exact 80% numeric cases return `False` instead of `True`.
4. The valid current CLI readback case fails with `ANNOUNCEMENT_OWNER_IMPORT_RECEIPT_HANDOFF_BINDING_INVALID`.

The other seventeen cases already pass before the production repairs. The eight negative readback cases also reject under the old wrapper's blanket rejection of a modern receipt; the new positive case is necessary to establish that the repaired wrapper accepts a valid modern response while retaining those rejections. Wrong target/publication inputs, a resealed receipt containing the wrong semantic source SHA, and a different existing output continue to reject before replacement output is written. The final announcement test snapshots the persisted synthetic historical handoff subtree before current import and compares its actual file hashes after import plus two workspace reads. The whole owner-state snapshot also remains unchanged across the two GETs.

The only warning in these runs is the installed Starlette test-client deprecation concerning httpx/httpx2. This review did not alter dependencies to suppress it.

An initial exploratory replay used a copied globals dictionary, which prevented the existing fixture patches from reaching the screen function. That experiment was excluded. The accepted replay below executes each original function definition into its existing module globals within a separate Python process, so the final fixture seams remain effective and the production files on disk remain untouched.

## Reproducing the accepted original-function replay

The recorded assembly root is `/workspace/scratch/53ae4d14e489/work/app`. The following is a test harness, not a production execution path. It preserves the original source bodies and changes only the current Python process's three function bindings.

```bash
cd /workspace/scratch/53ae4d14e489/work/app
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=.:/workspace/scratch/53ae4d14e489/work/python-deps \
python - <<'PY'
import ast
from pathlib import Path
import pytest
from ops import run_manager_daily_announcement as cli
from v4.manager_research import workspace_plan as wp

cases = [
    (cli, '_build', Path('/workspace/scratch/53ae4d14e489/intake/V4_SELECTION_OUTPUT_REUSE_ISSUE_20261010_R2/source/historical-r2-release/app/ops/run_manager_daily_announcement.py')),
    (cli, '_readback', Path('/workspace/scratch/53ae4d14e489/intake/V4_SELECTION_OUTPUT_REUSE_ISSUE_20261010_R2/source/historical-r2-release/app/ops/run_manager_daily_announcement.py')),
    (wp, 'read_rebound_screen', Path('/workspace/scratch/53ae4d14e489/intake/V4_SELECTION_OUTPUT_REUSE_ISSUE_20261010_R2/source/current-live-release/app/v4/manager_research/workspace_plan.py')),
]
for module, name, path in cases:
    function = next(node for node in ast.parse(path.read_text()).body
                    if isinstance(node, ast.FunctionDef) and node.name == name)
    subset = ast.Module(body=[
        ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0),
        function,
    ], type_ignores=[])
    ast.fix_missing_locations(subset)
    exec(compile(subset, str(path), 'exec'), vars(module))
raise SystemExit(pytest.main([
    '-q', '--tb=short', '-p', 'no:cacheprovider',
    '/workspace/scratch/53ae4d14e489/work/repair_tests',
]))
PY
```

For the after run, use a fresh Python process with the same environment:

```bash
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=.:/workspace/scratch/53ae4d14e489/work/python-deps \
python -m pytest -q -p no:cacheprovider \
  /workspace/scratch/53ae4d14e489/work/repair_tests
```

## Diagnostic helper review — initial findings

Reviewed initial helper: `/workspace/scratch/53ae4d14e489/agent-connect/inspect_connect_metadata.py`, SHA-256 `2046a4325a56479cfef12b0e9d5d9534fb857ae6c0a615b4560b347f5b60d014`.

### Important — missing conditional D-1 read-scope audit

The helper initially recorded only the three `V4_MANAGER_UNIVERSE_*` bindings (`inspect_connect_metadata.py` lines 26 and 92–104) and called unchanged `read_scope` at line 149. That reader, `connect_selection.py` lines 130–138, conditionally reads `V4_MANAGER_HK_CAPTURE_RECEIPT_ROOT` and `V4_MANAGER_HK_DISPATCH_RECEIPT_ROOT` after target V2 failure when the original context has a market session.

`connect_capture_adapter.py` lines 184–200 then read the configured prior-session panel, manifest and raw capture; lines 253–271 read the existing security-master evidence; lines 315–317 invoke dispatch validation, whose lines 96–112 enumerate the specified date/slot's dispatch receipts. Thus the initial recipe's statement that it does not scan other roots was too strong and its binding provenance incomplete.

This is not a production reader bug. The D-1 result remains separate evidence and does not replace target-date qualification. No collector, publisher, ensure call, network action or external data transmission was identified. The diagnostic correction should explicitly audit the two inherited receipt-root bindings and document the conditional read scope, preserving the original reader and context. It should not silently clear environment variables or fabricate a target-date result. If the extra bindings cannot be confirmed, report the reason transparently rather than claiming the full reader replay ran within a narrower scope.

### Minor — output fields initially lacked sufficient scalar constraints

The initial context projection at helper lines 100–101 copied `market_session` and `calendar_sha256` values directly. A malformed context could contain a nested object under one of these metadata field names, which the reader rejects as invalid but the diagnostic report echoes. Owner-field projection similarly checked names more strongly than value types. The helper should reject or sanitize invalid container values with a fixed diagnostic code before claiming a strict metadata-only report. No real sensitive output was observed in this review.

### Corrected helper disposition — findings closed

**Both findings are closed; the corrected local diagnostic tool is acceptable for delivery.** The above initial findings are retained as the review record, not as outstanding issues.

Final identities independently checked against `helper-verification.json`:

| File | SHA-256 |
|---|---|
| `inspect_connect_metadata.py` | `b333f542da12467bddb23d0b1ebec6fdfc1456bece9b840a6eff8f71a1e7514e` |
| `HK_CONNECT_LOCAL_REUSE_RECIPE.md` | `c8b624aa1276a546c4a0c314a67814cbf55ca83e73945769e05e45458cc2f6b1` |
| `verify_connect_helper.py` | `d8f62af95c73d895fe8dcf05cb37f3cff5fa88cf60c0b6ce9d4da047652c0eac` |
| `helper-verification.json` | `5626041398d27ce22acfb79ea37def8b3488afcb95008d53bd3b487411a231c9` |

The corrected helper at lines 30, 87–103 and 158–175 records the two optional D-1 bindings and conditional access route. Invalid noncanonical bindings yield `CANNOT_CONFIRM` before owner loading or reader invocation (lines 178–181). The original D-1 environment is retained. Only the diagnostic subprocess's universe root is temporarily changed and restored.

The context guards at lines 125–141 reject missing, nested or invalid market-session dates and calendar SHAs. The cutoff remains validated at lines 155–156. `scalar_metadata` and `gap_metadata` at lines 69–84 restrict emitted values; diagnostic, calendar, owner, source and D-1 projections use them. The recipe now distinguishes at most two explicitly compared authority roots from the original reader's additional configured evidence reads and asks the operator to verify all five service bindings.

The reviewer inspected the 13-item PASS record and its verification code. Coverage includes two empty authority roots, preserved D-1 roots entering the original missing-file branch, relative/symlink root rejection, six malformed-context cases, owner/source pin rejection and metadata value guards. These recorded checks were not rerun by the reviewer; their code, statuses and source identities were inspected. They use synthetic empty/absent roots and do not establish a complete authority success, full D-1 capture/dispatch success, real service configuration or live business output.

The tool preserves explicit owner pinning, target date, source-SHA checks and cutoff semantics. Its second comparison root is derived from the supplied existing HK job's `--hk-asset-root.parent.parent` rather than a filesystem search. The report still identifies bindings as those inherited by the diagnostic process; matching them to the running service remains an explicit local prerequisite.

## Acceptance limits

- The independent evidence in this report is the local synthetic suite and code inspection. The primary workflow's supplied 17-test pass and historical reference result of 1 failure / 38 passes before and after are separate evidence; this reviewer did not repeat those suites.
- Repeated TestClient GETs are not a process restart, browser reload, live API/UI session, scheduler execution, or natural-run acceptance.
- Synthetic historical fixture preservation is not replay of the real historical 33-security result.
- The current Mac's original reviewed announcement inputs, exact published handoff, V2 authority, volume unit/scale attestation and Stage artifact are not in this review's verified inputs.
- Neither patch restores those missing owner artifacts. It is not justified to declare real 20261009 selection recovery, nonempty live candidates, or natural execution success.
- No Stage, BUY, Vibe8910, source-date, SHA, review, PIT, unit/scale or completeness gate was changed by the reviewed production delta.
