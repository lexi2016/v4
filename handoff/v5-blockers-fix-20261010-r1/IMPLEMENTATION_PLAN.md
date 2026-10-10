# V5 blockers implementation plan

> For agentic workers: use superpowers systematic-debugging, test-driven-development, and verification-before-completion. Root executes interface work; three isolated agents implement/review independent tasks. Existing user authorization covers reversible implementation and a new private GitHub branch.

**Goal:** Deliver minimal source increments for the frozen V5 blockers and explicit, verifiable remaining Mac/external-review work.

**Architecture:** Preserve the three original source roots. Use original owners for saves/imports and retain every business/PIT gate. Cross-day recovery gets its own original-owner store. Identity compares full code structure. The existing external file/worker workflow gets a callable transport contract and read-only preclaim validation; no model service is created or claimed connected.

**Tech stack:** Python 3.14.6, original uv.lock dependencies, unittest, original source owners.

**Spec:** input/REPRO_AND_ACCEPTANCE.md and input/ADDITIONAL_INTERFACE_AND_PROGRESS.md at fixed GitHub 46081f5bcfb5f0c9e63aaa8b2b7baf65ae191eff. US_STATUS_APPENDIX.md supersedes ZIP-era US NOT_RUN.

## Global constraints

- Do not re-read/re-decide the 392 announcements or fabricate the original reviewer's new PASS.
- Preserve V4, old plans and historical PIT, BUY/Stage, admission, native units, scale1, and original data/pointers.
- Preserve 3d9541ac/e06d/ebe5944e source identities separately. No unrelated pin refresh.
- New private GitHub branch only; no merge, deployment, service start/stop, model fit, or business-data modification.
- Original ZIP binary could not be retrieved: 1,177 original-ref source paths fetched; all Python bytes agree with ZIP checksum index. Four sanitized metadata/document differences are explicitly recorded.

## Review focus

- Cross-day auto must select only the exact target recovery store; explicit history retains historical qualification.
- A missing or malformed review, stale heartbeat, wrong request/source/identity or changed file must block before any business attempt.
- Owner code constants, nested code, imported helpers/globals/native layout must still reject substantive changes.
- Independent reviewer output remains external evidence; structural validation never impersonates the original reviewer.
- Identical completed handoff is stable; callback errors are unknown outcomes with no automatic submission retry.

## Task 1: Cross-day recovery

- [x] Reproduce the fixed old-target original chain at actual current time.
- [x] Add current-day/cross-day/auto/history/input-change/no-write regressions.
- [x] Change only V5 manager adapter routing and response identity, using a separate current_recovery owner store.
- [x] Run original chain, manager tests and boundary checks; record exact source hashes.

## Task 2: Rebound identity

- [x] Reproduce a valid frozen loader rejected before inspecting its code attributes.
- [x] Replace marshal serialization equality at the two identity comparison sites with full, type-strict recursive code structure comparison.
- [x] Test reference hold/release plus function, nested code, helper, globals, constants and native-layout rejection.
- [x] Run the scoped original repair/admission/observation suites. Preserve opt-in-only private tests.

## Task 3: Original reviewer binding

- [x] Prove missing/wrong binding is rejected before any revision directory is created.
- [x] Add a read-only preflight/request tool and exact original-reviewer return requirements.
- [x] Preserve create_revision bytes and its full original validation; new original-reviewer file remains pending.
- [x] Run original 10+7 suites and new structure/no-write tests.

## Task 4: Reader/reviewer callable contract and preclaim checks

Files: new src/v5_shadow/daily_review_handoff.py and tests/test_daily_review_handoff.py; minimal integration in daily_tick.py, daily_announcement_revision.py and daily_owner_adapters.py adapter identity.

- [x] RED: missing decision_revision and same reader/reviewer identity must never allocate an announcement business attempt, even when all three files exist.
- [x] Implement preflight_revision(request) as read-only safe file/hash/binding/identity/decision digest validation. The original owner remains authoritative and revalidates before creation.
- [x] Implement a narrowly injected submit/poll contract for an existing host-owned channel. Task/source/worker/request IDs, acknowledgement, heartbeat, failure/unknown outcome and returned file hashes are explicit; absence is BLOCKED. No configured command, dynamic import, network client, or fabricated model worker.
- [x] A supplied handoff receipt must be fully bound and completed before owner dispatch; legacy explicit reviewed-file handoffs remain accepted after the same preflight. Waiting and invalid returns do not claim the business ledger.
- [x] Test missing channel, distinct identities, stale/future heartbeat, changed task/source/output, failure/unknown result and stable completion; run original daily suites plus integrated owner chain.

## Task 5: Independent review and delivery

- [x] Review combined increments independently and fix concrete important findings with regressions.
- [x] Deliver minimal patches, complete after-files, precise before/after SHA, raw scoped logs, Mac steps and rollback.
- [ ] Publish only necessary new handoff files on a new GitHub branch from fixed 46081f5b and read back commit/file identities.

## Rulings

- The provided repair specification and standing autonomy authorize implementation now; additional skill-specific planning permission is not required.
- Preserve future target sessions supported by the original planner; reject only future supplied now/cutoff, as before.
- A missing original reviewer or host channel remains an external BLOCKED item after code delivery. No local structural PASS will be described as completion of that review.

## Final review addendum

Five Important findings were confirmed by independent reviewers and fixed after failing regressions: post-callback clock sampling, strict recovery journal presence, semantic source SHA preflight, a per-job preclaim hook, and exact JSON type/decimal preservation. Final runtime and whole-suite evidence are in VALIDATION.md in the delivery. The publication checkbox is intentionally pending in this pre-publication plan snapshot; final remote commit/SHA readback is reported with the delivered commit.

Full discovery contains reproduced baseline failures and unavailable private inputs. This does not authorize merging/deploying or relaxing those gates. Standing repository authorization calls for preserving the complete tested candidate and evidence on a new private handoff branch; that authorized delivery does not wait for unavailable Mac inputs or a skill menu.
