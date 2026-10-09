# Independent V4 Stage R4 review

**Verdict: PASS for the frozen application, release tools, tests, and isolated acceptance run.** The independent copied-package run passed all **479 exact test identities**, with no failures, errors, or skipped cases. The UI TAP report also contained zero cancelled and zero TODO cases. There are no open reproduced findings from this review.

Reviewer role: `/root/r4_independent_review`. The reviewer did not author or change the application, release guard, preparation coordinator, or publication implementation. The reviewer authored the verification runner and its 42 gate tests; `/root/r4_release` independently read that runner and its gates and reported no blocking defect. The root author also ran the complete frozen package independently.

## Frozen package and run

The parent froze the package at `/workspace/scratch/49c844334a98/stage-r3-live-integration-20261009-r4`. The reviewer copied all 213 files, preserving their bytes and modes, into:

`/workspace/scratch/49c844334a98/v4/handoff/stage-r3-live-integration-20261009-r4/work/review/final_package_frozen`

The complete copied file inventory matched before execution and again after the full run. Package verification passed both before and after testing.

| Frozen artifact | SHA-256 |
| --- | --- |
| SOURCE_MAP.json | `8773920e5d09da693b42d453bc4638e0cc1358d10da8c53fb12fe115eb0e6ab9` |
| TEST_EXPECTATIONS.json | `4a7e7ecb44e98eb58469e0d310e19d3dc49ad1c8d89c17a2d12152ebca488b58` |
| Reviewed 213-file DELIVERY_MANIFEST.json | `439056ef8f1a342fcf5e04af491e61a4c52bde5bc66795101209ac08e11bfb81` |
| Independent full RESULTS.json | `1e26aeaf89f366de50cfdb52c0dbb75338d40112a2155e4148391593c0662bdc` |
| Independent role receipt | `11341e4046cfa79bc226e37d63bdb45abca2953388984a00d56409ad6c56219d` |

The run started at `2026-10-09T15:04:25.774333+00:00` and finished at `2026-10-09T15:07:13.117159+00:00`, taking 167.342826 seconds. Its environment was Python 3.12.14, Node 24.19.0, Vue/compiler/server-renderer 3.5.40, Babel parser 7.29.7, and Linux 6.18.44 x86_64 with glibc 2.39. The full result records executable paths and dependency package-file hashes. The installed review runtime's package-lock SHA was `b0b4d2a1ddbbabe75eef96abc947b1dc2fa1c12e8d8c4337bafc5d806643a096`.

## Acceptance results

Expected counts, case identities, and test-source file hashes were frozen before the run. The runner required that fixed inventory, checked real JUnit testcase outcomes against declared totals, checked real TAP assertions and its plan, and rejected omitted or substituted case identities.

| Suite | Exact cases passed | Composition |
| --- | ---: | --- |
| API | 129 | 47 R4 cases plus 82 original R3 API regressions, run in separate processes and retained separately |
| UI | 70 | Current App source and compiled Vue panel/contract checks using a fresh API fixture |
| Release | 152 | 112 original release regressions plus 40 Stage additions |
| Integration | 86 | 10 build-helper, 18 package-integrity, 18 preparation-coordinator, and 40 publication cases |
| Review gates | 42 | Frozen-source/case accounting, negative JUnit/TAP cases, and real subprocess portability/skip cases |
| **Total** | **479** | **Zero failures, errors, skips, cancellations, or TODO cases** |

The release regressions ran from a fresh verified `ops/` and `tests/` copy so their original relative-path assumptions were preserved without editing the test files. The original and copied file SHA/mode maps matched again after testing.

The exporter freshly generated both `consumer_response.json` and `workbench_response.json` using the exact R4 API after bytes, original R3 stores and owner writer, and the actual route/projection source. The runner verified the two files and their receipt, market/run/artifact/algorithm/raw-artifact identities, owner-history binding, and count agreement before giving those files to the UI tests. The fixture contained 10 selected rows for each market, with A-share request/source counts 216/206 and HK counts 695/695. These are explicitly synthetic fixture results. The independently accepted real R3 research run remains a separate receipt.

## Findings found and closed

The reviewer retained the original failures and false-success evidence. The implementation authors made the production fixes. The reviewer then repeated the original probes against the corrected bytes.

### UI build helper

The initial helper SHA was `4ee043ebef270425dae3da6233017cc483b6aa453cca00c11f64ad90abb3b284`. It accepted a synthetic successful build with missing HTML-referenced scripts, and it missed a change to the prepared-source provenance manifest during the build.

The corrected helper SHA is `06aa4fd4a034af1cf3b1e761a5e9d0c062eec1f26152f2b08f6f2c202e16e4dc`. The identical probes now reject with `STATIC_LOCAL_DEPENDENCY_MISSING` and `PREPARED_SOURCE_CHANGED`. The latter reports source preservation as false, and neither failure seals a static inventory digest. Both findings are closed.

### Publication HTTP verification

The initial probed publisher SHA was `f911692dd27e73a4de72522d06fe2c842abd5a1e4af729c14825657466f42e8f`. Its simulated end-to-end publication accepted four contradictory HTTP responses and returned `STAGE_API_SWITCHED_AND_READBACK_VERIFIED` without recovery.

The corrected publisher SHA is `6a3771b465f7ed8fb570050cba395f210c3eafa899252081c6b0aaa873dfda63`. All four original probes now reject and invoke the original recovery primitives, restoring the exact preimage plist.

| Original counterexample | Corrected rejection |
| --- | --- |
| Historical response reports `orders_sent=true` | `HISTORICAL_FINANCIAL_SAFETY_CHANGED` |
| Approved target has `unified_rows=[]` while market lanes each retain ten rows | `RESEARCH_HTTP_UNIFIED_ROWS_MISMATCH` |
| Approved A-share selected evidence has the wrong algorithm SHA | `RESEARCH_HTTP_SELECTED_EVIDENCE_MISMATCH:A_SHARE` |
| Approved A-share requested count changes from 216 to 200 | `RESEARCH_HTTP_MARKET_COUNTS_OR_STATUS_MISMATCH:A_SHARE` |

Every corrected probe produced the simulated action sequence `bootout`, `bootstrap`, `bootout`, `bootstrap`, with exact preimage restoration. The tool file remained unchanged. The separate frozen 40-case publication suite also independently passed before the complete package run.

## Source and integration assessment

The source package contains four API and three UI after files with fixed preimages. The current full App preimage is retained; the changes add bound Stage evidence in the existing flow. Existing history, routes, manager navigation, callbacks, and preselection behavior remain covered by the source and regression checks.

The release policy extends only the declared Stage ownership and shared paths. Complete static file inventories bind additions, modifications, and deletions, while deletion outside the declared static tree is rejected. The candidate is checked against the current active base plus the exact delta, including non-delta preservation and stale source/base rejection. Sparse Git preparation happens in a fresh destination and supports the actual non-Git input tree.

The coordinator independently reconstructs the expected prepared UI graph from the same active application plus the three reviewed UI files. It rechecks the build graph, generated static bytes, binding configuration pair, research receipt dependencies, package source pins, and active inputs. Its publication plan retains the current manager and history roots. The original builder's isolated manager plan remains marked ineligible for publication.

The publication wrapper reuses the unchanged publisher's shared lock registration, leased pointer compare-and-swap, metadata preservation, immutable prepared transaction, service actions, and rollback primitives. Its new continuation loader binds the new publication directory, prepared receipt, plan, backup, exact original base, and read-only guard records. Recovery remains possible after candidate corruption without requiring candidate tools to validate successfully. The frozen original publisher and original guard SHA values are recorded in the role receipt; their source bytes and constants were not changed.

## Scope and evidence

This review establishes source, package, and isolated fixture behavior. It does not establish a new Mac runtime or ACL result, a real npm/Vite production build, live 8873 HTTP/browser acceptance, actual launchd execution or deployment, or natural market-session acceptance. The existing R3 Mac, real PyTDX, isolated HTTP, and browser receipts retain their original scope and are not relabeled as this R4 run.

The initial UI environment failures are preserved: the suggested runtime paths did not contain Vue. Exact cached packages were restored offline into the separate review runtime with lifecycle scripts disabled; subsequent UI and complete-package runs passed.

Primary evidence is in this review directory:

- `INDEPENDENT_REVIEW_RECEIPT.json`: compact role attestation, all suite totals, dependency identity, source pins, and evidence hashes.
- `FINAL_PACKAGE_COPY_RECEIPT.json`: complete 213-file byte/size/mode inventory.
- `full_package_independent_run/RESULTS.json`: exact commands, output hashes, testcase identities, package checks, and fresh API-to-UI fixture binding.
- `full_package_independent_run/{api,release,integration,review_gates}.junit.xml`: aggregate reports; original API process XML files are retained as `api_r4.junit.xml` and `api_r3.junit.xml`.
- `full_package_independent_run/*.stdout.log` and `*.stderr.log`: unedited command output, including UI TAP output.
- `PUBLICATION_REVIEW_RECEIPT.json`: publication source/transaction review and the four original/fixed probe bindings.
- `evidence_initial/`: original failed environment attempts, initial counterexamples, formal gate RED/GREEN evidence, and independent corrected reruns.

The ready-to-run checker is `tools/run_checks.py` in the delivered package. It requires an explicit installed UI runtime and a new absolute output directory. The exact command used here is retained in the evidence; no test expectations are generated or weakened by running the checker.

`RESEARCH_ONLY=true`; `production_allowed=false`; `buy_gate_updated=false`; `orders_sent=false`. No real service action, market acquisition, live state write, or deployment was performed by this review.
