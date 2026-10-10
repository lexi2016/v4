# V5 module01 minimal repair implementation plan

> **For agentic workers:** Use Superpowers systematic-debugging, test-driven-development and verification-before-completion. Independent source areas are delegated; the controller integrates and obtains a fresh final review. Steps use checkbox syntax.

**Goal:** Preserve the existing V5 announcement owner → manager plan → ordinary read chain, repair verified run/read and UI control defects, and deliver a reviewable code candidate.

**Architecture:** The fixed V5 tree is the target. Existing V4 candidates are semantic donors only. Keep immutable products, original validators and read-only module APIs; do not create another store, writer, operation identity, or deployment.

**Tech Stack:** Python 3.14.6 with the unmodified V5 uv.lock; the existing pinned frontend project, lockfile, TypeScript and Vitest.

**Spec:** lexi2016/v4@9cac0fffe12fda6ec06e106206e0c647b427913f:handoff/v5-chat-module01-20261010/PROMPT_FOR_CHAT.md.

## Global constraints

- Target V5 source: f7cb731c384ee6890a87d16c19a5b5a621779477. Source-only assembly is byte-checked against Git blobs.
- Preserve original dates, owner, SHA, PIT, research-only flags, BUY, V4 and 8910 boundaries.
- Existing run and same-run terminal are authoritative; latest is a separate observation.
- Mac 392-decision originals, current installed preimages and live UI acceptance are NOT_RUN here.
- Do not broaden COMPLETE_EMPTY, old US receipt compatibility, rebound admission or dormant catalyst replay.
- Keep dependencies and source manifests unchanged unless a proven necessary change requires updating them.
- User explicitly authorizes implementation and an independent GitHub branch; do not pause for a second design approval or deploy.

## Review focus

1. A completes, B advances latest before A's independent read: A remains valid; B is never called completed without its own terminal.
2. Product A with journal B, missing terminal, corrupt source, or wrong date: reject or show explicit unverified state, never borrow identity.
3. Read-only V5 API with legacy frontend refresh code: page cannot open generation; headers can restrict capability only.
4. A request resolves after cancel/date/view changes: it cannot render stale data or re-enable an unsafe action.
5. A healthy nonempty announcement lane coexists with missing US/other sources: keep original results, gaps and qualification limits visible.

## Task 1: manager exact readback and same-run display

Files: `src/v5_shadow/manager_plan.py`; `tests/test_module01_exact_run.py`. Change `manager_plan_io.py` only if the already allowed run paths are insufficient.

Interfaces: preserve `readback.status`, `run_id`, `plan_sha256`, `attempt`, and input identity; add a separately labelled `latest_observation`. Use existing `plan_store` view and original workspace validators, with explicit requested-run equality.

- [x] Write deterministic tests using actual owner saves A/B, missing/swapped terminal and read-only source guards; run and retain RED.
- [x] Implement the minimum exact selection and same-run response binding; keep original immutable bytes and historical validator behavior.
- [x] Run the new tests and relevant original manager tests; retain raw GREEN/failure logs.

## Task 2: API capability and frontend request lifecycle

Files: `src/v5_shadow/module_api.py`, `src/v5_shadow/api_gateway.py`; `ui/manager-workbench/source/apps/web/src/api/managerWorkspace.ts`, `manager-selection/catalystObservationPanel.ts`; new Python and frontend tests.

Interfaces: `X-V5-Workspace-Access: READ_ONLY` is emitted by the actual read-only module or GET-only manager workspace gateway route. It only restricts UI actions. Generic gateway routes that admit POST do not claim to be read-only. Preserve the legacy optional frontend refresh function without adding a V5 write endpoint.

- [x] Write actual HTTP tests proving capabilities, payload preservation, original POST rejection and generic gateway behavior; observe RED.
- [x] Emit the capability header without modifying saved DTOs or source identities; run targeted HTTP tests GREEN.
- [x] Write portable frontend tests for binding validation, a single successful POST consumption, cancel/date/view races, historical/read-only gates and unknown side effects; observe RED.
- [x] Implement only these proven UI/API defects; leave already integrated CURRENT_RECOVERY and daily channel files unchanged.

## Task 3: original announcement chain and cross-language integration

Files: `tests/module01_owner_fixture.py`, `tests/test_module01_announcement_contract.py`, targeted integration test/driver as needed. No producer or capsule modification without a reproduced blocking defect.

Interfaces: a clearly labelled synthetic four-decision owner fixture uses the original capture/register/import/readback functions. Its actual manager and HTTP DTO feeds the complete frontend validator; no simplified validator stands in for it.

- [x] Verify fixed fixture source provenance; build the original owner result in a private temporary root.
- [x] Test nonempty announcement preservation with missing lanes, source/date/receipt tampering and safe read-only readback.
- [x] Export actual module/gateway HTTP bytes to the frontend integration test and run its complete validator.
- [x] Record real Mac fixture-dependent tests as NOT_RUN; do not replace their excluded fixture.

## Task 4: delivery and independent review

- [x] Build SOURCE_TARGET_MAP, exact before/after file images, runtime/reverse patches and hashes; validate patch and reverse in disposable copies.
- [x] Record dependency closure, commands, runtime versions, raw failures and unresolved limits; no inflated full-system claim.
- [x] Obtain a fresh independent review; fix substantive findings with regression tests.
- [x] Provide guarded Mac candidate/application/API/static/UI/CAS rollback instructions using explicit operator-supplied paths.
- [x] Commit only scoped changed files to a new GitHub branch rooted at the pinned V5 commit, then read back commit/tree/file identities.

## Final implementation and verification record

The unique code commit is `6daed6271313b5ae5324c8948f163258ab8d1fa3`, parent `f7cb731c384ee6890a87d16c19a5b5a621779477`, on the independent branch `v5/module01-announcement-readback-20261010-chat`. All 20 code/test files and branch identity were read back. The subsequent materials commit adds the complete handoff without changing these code bytes.

Two proven integration defects were added to this plan: the publication CLI read twice, and the existing overlay manifest contradicted itself. Both have retained RED/GREEN evidence. Fresh review found incomplete frontend terminal admission and incorrect read-only classification for a separate refresh route; both were fixed and independently rechecked. No Critical/Important findings remain.

Final targeted frontend tests: 44/44; affected frontend suite: 85 PASS / 2 missing-original FAIL; full typecheck and final build exit 0. The original 442/23 frontend entry and Python 222 entry with errors/skips remain recorded, with exact dependency/fixture classification. This is not a full-engineering or Mac acceptance claim. Forward and reverse patches plus the read-only preimage guard were verified on disposable copies.

Mac 392 originals, installed preimages, deployment, real API/static/browser and natural-period acceptance remain NOT_RUN. Detailed evidence, original failures, donor map and Mac instructions are in `handoff/v5-module01-minimal-repair-20261010-chat/`.
