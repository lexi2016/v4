# Archive builder identity implementation plan

> For agentic workers: use superpowers:executing-plans. Author the candidate and tests here; the user-designated independent Mac task owns every product execution.

**Goal:** Bind the complete original builder source to one explicit acquisition run and reject identity mutations before successful archive publication.

**Architecture:** A V5 owner adapter invokes the byte-pinned original collector against only the declared status/summary, records its actual clock calls, and retains its exact persisted source bytes. The importer and independent reader replay the same original owner in memory, compare the entire source byte stream, invoke the original archive builder, and compare the entire v1 payload before admitting the v2 extension.

**Tech stack:** Python standard library, existing original collector/builder/store, existing isolated archive reader and manager owner.

**Spec:** `handoff/v5-article-identity-20261010/REPAIR_REQUIREMENTS.md` at `cdd430e4dcd8d3e8c5949baff21a4831b4689444`.

## Global constraints

- Preserve candidate `7115f65267a1496d0ca8214cc14130f8c2b65d87`, including microseconds, explicit response groups, status path, issuer/body/URL and PIT checks.
- Only V5 wiring changes; original owner/V4/frozen handoffs remain unchanged.
- Never infer claim_type, reduce the source to article rows, or replace the original source SHA with a fresh JSON serialization.
- No real collection, deployment, trading, credentials, system changes or product-test execution here. All product tests remain NOT_RUN; synthetic execution never sets natural_verified true.
- Independent GitHub delivery branch from the fixed task commit; no merge or shared-branch overwrite.

## Review focus

- A mutually consistent modified source and archive must still fail if the original owner cannot reproduce the complete source from the bound run.
- A missing source or producer receipt must not fall back to the old v2 admission path.
- Identity repair must preserve precise legacy rejection reasons for body, URL, group, date, status and publication changes.
- Persisted source serialization, original naive clocks and owner-generation cutoff semantics must remain distinguishable from v2 acquisition/availability times.
- Source/receipt files must survive manager input path validation and be required again by the independent archive reader.

## Task 1: Original owner capsule and bound source contract

**Files:** Create `V5/src/v5_shadow/archive_builder_v1.py`, `V5/contracts/archive_builder_source_manifest.json`, and byte-identical owner/support copies under `V5/vendor/archive_builder_baseline/`.

**Consumes:** Existing acquisition receipt v3, explicit status and capture file bindings; original collector `build_hourly_research_input(*, data_root, business_date, slot)` and builder `build_research_archive(source, *, source_input_sha256)`.

**Produces:** `run_build(request)` calls an isolated CLI which returns explicit `builder_source`, `builder_receipt`, complete `capture_files`, and rebuilt `archive_v1`. `verify_builder(original, source_ref, owner_ref, receipt_ref, read)` independently replays the complete owner and archive builder without writes.

- [x] Author complete-source preservation and same-run rejection test candidates; Mac owns RED/GREEN execution.
- [x] Add the pinned original collector/normalizer/builder closure. The absent original `_namespace.py` is supplied explicitly as V5 structural support using byte-identical fixed generic namespace code, with a Mac original-path SHA gate; never label it an already supplied original file.
- [x] Implement real owner source publication and exact-byte readback; record actual owner clocks and keep optional fields intact.
- [x] Implement readonly source replay, exact source-byte equality and complete original archive comparison, preserving reason codes and safety fields.
- [ ] Mac: execute the original three baseline control/mutation tests first; require the control success and exact unexpected-acceptance failures before calling the baseline RED. This step is NOT_RUN here.

## Task 2: Importer and independent reader wiring

**Files:** Modify `V5/src/v5_shadow/archive_article_v2.py`, `V5/src/v5_shadow/archive_reader.py`, `V5/src/v5_shadow/manager_plan.py`, producer dependency/identity manifest, and related test fixtures.

**Consumes:** The explicit builder source and owner receipt references from Task 1.

**Produces:** V2 payload with required source/owner references; archive binding includes every required byte; child identities include the new adapter/capsule.

- [x] Preserve existing semantic capture checks, then verify the bound source and rebuilt v1 before writes.
- [x] Require the source contract on every v2 independent read; keep v1 dispatch explicit and unchanged.
- [x] Keep exact source files in the existing archive binding/path allowlist and manager worker identity.
- [ ] Mac: run identity mutations, missing source/SHA/run/date/content mutations, legacy rejection cases, and original store/reader/material/manager/same-run plan roundtrip. This step is NOT_RUN here.

## Task 3: Review and delivery

- [x] Conduct a fresh independent static review against the spec; correct material findings and add test candidates.
- [x] Verify syntax without importing product modules, package paths/SHA, patch replay and original-owner byte preservation. Report these only as static/artifact checks.
- [x] Save exact patch, before/after hashes, runnable Mac commands, remaining real-source proof gap and rollback instructions in a new handoff.
- [ ] Commit through GitHub to an independent branch; read back the fixed commit and changed blob SHAs.

## Execution rulings

- The supplied repair requirements explicitly reserve all product execution for the existing Mac task. RED/GREEN are authored candidates, not verified outcomes; no local unit suite or product import is authorized by this plan.
- The source producer supports the existing bounded ZSXQ collector. Full-source equality rejects extra or changed fields; it never drops them to manufacture acceptance. Special claim_type/fallback/duplicate cases are original-builder contract tests, separate from real collector-output fixtures.
- Use recorded original clock calls for deterministic readonly replay. They prove replay consistency only; real provenance and natural-time acceptance remain unconfirmed until the same-batch Mac owner evidence is read back.
