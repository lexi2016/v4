# Issue #30 — delivery package review

**Result: PASS for the isolated source/evidence delivery scope.** No open blocking package finding remains. One P3 documentation naming error was reported, corrected by the parent, and read back.

Reviewed package: `/workspace/scratch/a245cda1e07c/delivery/8873-module-isolation-candidate-20261010-r1`.

Reviewer: `/root/publisher`, the historical native-reference adaptation author. This is a separate read-only packaging/documentation check; the independent code-review identity and conclusions remain those recorded by `/root/independent_review` in `review/independent_review.md`.

Reviewed at: 2026-10-10 15:19:21 UTC.

## 1. Independent package replay

I inspected and then executed the delivered `tools/verify_delivery.py` using the clean `testenv_final` interpreter with bytecode writes disabled. It exited **0 / PASS**:

| Check | Observed result |
| --- | --- |
| Initial package snapshot | **428 files**, exact declared file set and SHA matches |
| Before / after source files | **23 / 26** |
| JSON and Python syntax | PASS |
| Both forward patches | Applied in a new temporary tree; result exactly matched every `full-after/` file |
| Combined reverse patch | Applied to that result; exactly restored every `before/` file |
| Service actions | None |
| Package writes by this reviewer | None; replay used a disposable external tree |

The parent subsequently corrected the documentation word below and added the native call-site/initial-verification records, reporting 430 packaging files. I did not rerun the complete package verifier after those packaging-only additions, as requested. The parent will regenerate and verify the final root manifest after the remaining remote/package-review receipts and ZIP are assembled. The **428-file count describes the independently replayed snapshot**, not the eventual ZIP file count.

## 2. Code identity and historical publisher binding

I independently checked `CODE_SHA256.json` against actual before/after bytes, sizes and Git blob hashes. All **26 after files match the tested `work/` files exactly**. The inventory records **7 changed files** and **19 unchanged files**. The seven changes are the three existing ops entry/helper files, the new business policy helper, two new test files, and the historical native reference.

The final packaged native reference SHA-256 is:

```text
2b74e2193c7924b0c580129677738f3c766b938aea4d32341a0a7798ddfe7cd3
```

Its **47 original historical uppercase constant AST expressions are unchanged**. All **five embedded guard pins** equal both `review/final_guard_pins.json` and their actual `full-after/` file bytes. The seven recorded function definitions, line numbers and call collections in `review/NATIVE_CALL_SITES.json` match the actual reference AST and the same final source SHA.

These identities agree with `logs/final-native-frozen-pins-r2.json` and the final independent review. The code remains explicitly a historical reference with unconfirmed current Mac binding.

## 3. Main-document accuracy

| Document | Assessment |
| --- | --- |
| `README.md` | Correctly describes one 8873 gateway, exact owner delta and current-base rebuild, reverse-delta rollback, 106 isolated tests, unchanged historical pins, and the uncompleted live/owner/staging requirements. It says Issue #30 should remain open. |
| `docs/ARCHITECTURE.md` | Correctly separates service role from business module identity, external authority from self-approved delta, the original common lock from a second publisher, and transaction recovery from requested module rollback. It explicitly limits the loader claim to fresh standalone execution and retains the non-running recovery limitation. |
| `docs/ACCEPTANCE.md` | Correctly reports the final 106-test result, labels synthetic versus real behavior, and marks loaded-but-non-running recovery as PARTIAL/CANNOT_CONFIRM. A passing refusal/incomplete-recovery assertion is not presented as restored live health. |
| `docs/USAGE_AND_ROLLBACK.md` | Gives offline verification/testing commands, inactive candidate preparation, and module reverse-delta preparation. It does not present the historical switch as a runnable current command, and distinguishes `reverse.patch` source restoration from service or business rollback. |
| `docs/PROVENANCE.md` | Pins current and historical inputs separately, distinguishes copied snapshot bytes from recorded Mac-source bytes, documents the input metadata discrepancy, and explains the final remote receipt packaging boundary. |
| `docs/MAC_EVIDENCE_REQUEST.md` | Requests the missing current identity, actual publisher/staging closure, real owner/build/state evidence, and failure semantics through read-only evidence collection. It explicitly does not authorize service actions. |

**Closed P3 finding:** the architecture document initially named `_lock`, which is not the actual helper. The parent changed it to `_locked`. I read the corrected document and confirmed the definition in `full-after/publisher_reference/api_only_cutover_r2_ready.py` and its call-site record. No code change was needed.

## 4. Input provenance and synthetic evidence

All **114 input source snapshots** match their retained `copied_sha256` and byte counts. The actual manifest contains **6** non-identical/redacted files and **82** recorded occurrences; these exactly match `review/input_metadata_discrepancy.json`. The older **10 / 89** narrative is preserved as input evidence and explicitly explained, so it is not silently treated as an accurate retained-payload count.

The synthetic export has **157 files**, including an index of **156 entries** that excludes itself. Every indexed byte count and SHA matches, as does the canonical aggregate. It records **3 scenarios** and **9 candidates**; its source-identity hashes match the final packaged code, and the evidence runner hash agrees across the tool copy, evidence copy and run summary.

The export is correctly labeled `SYNTHETIC_ONLY`, with native publisher/service/API/UI/Mac actions not run. Its original absolute run paths and original hashes are intentionally retained as execution evidence; the usage document correctly requires regeneration rather than path substitution when reproducing it.

## 5. Tests and environment

I read the packaged final r2 receipt and log: **106 passed in 6.35 seconds, exit code 0**. I did not rerun pytest in this packaging review.

The environment record contains **19** single-version distributions; each recorded version matches the supplied `uv.lock`, whose SHA also matches the environment record. The reproduction requirements identify the same 19 distributions and versions. An initial literal-name comparison in my check differed only on valid spellings (`Pygments`/`pygments`, `pydantic_core`/`pydantic-core`, `typing_extensions`/`typing-extensions`). Comparison through the installed `packaging.utils.canonicalize_name` resolved that checker false positive; no dependency version mismatch or package edit was required. The JSON review preserves that check and its resolution.

## 6. Final scope

The source, tests, patches, final reference pins, input provenance and synthetic evidence are consistent with the candidate-only claims in the documents. Current Mac publisher/staging binding, approved real module ownership, shared/frontend joint integration, live API/UI/natural behavior, and complete non-running recovery remain unconfirmed as documented.

The remaining outer-manifest/ZIP verification belongs to the parent's final packaging step after its additional receipts. This review provides no deployment or service-action authorization. I changed no package or code files and performed no remote actions.

