# Issue 30 implementation plan

> Execution: Superpowers systematic-debugging, writing-plans, test-driven-development and executing-plans; independent fresh-context review after implementation.

**Goal:** Reuse the existing 8873 publisher to enforce business-module deltas and construct inverse deltas on the latest active release without changing other modules.

**Spec:** `../verified_input/CHAT_TASK.md`, fixed GitHub commit `f615f4edcf4eb57aa6cf9ab407f2c2c2ed329a9b`; historical actual switch reference `a0a0b88dc133d14ee5763569272c174bcd7cc445`.

**Architecture:** Existing `build_integrated_app`/inventory/lock/CAS remain authoritative. A focused ownership validator reads a separately approved contract pinned by the active LaunchAgent. Business metadata travels in the existing delta receipt and release manifest. The existing role builder gains a gateway business mode, preserving the original launch bindings and static bytes. Business rollback produces a new inverse-delta candidate from current active and uses the same switch path. The historical native switch reference gets explicit shared-lock and business verification call sites; its frozen pins are retained, and its identity as the current Mac publisher remains unconfirmed.

## Global constraints

- Same `com.lexi.v35.api-only`, `127.0.0.1:8873`; no added service/port, data producer, or panel.
- `RESEARCH_ONLY=true`, `production_allowed=false`, `buy_gate_updated=false`, `orders_sent=false`.
- Do not change Stage, Vibe, BUY algorithms, owner state, live services or production data.
- No real business module owner is approved by the supplied evidence. Production ownership examples remain PROPOSED/disabled; only synthetic fixtures are enabled in tests.
- Retain immutable before bytes; record exact SHA and red/green commands/results. No live, Mac or natural-run claim.

## Tasks and interfaces

### 1. Ownership and provenance enforcement

- [x] Add failing tests for arbitrary gateway delta, cross owner/shared/unknown ownership, unsafe paths and unbound contracts.
- [x] Add `ops/api_business_modules.py` for strict contract validation and receipt binding. Trusted external contract is read from `V35_API_MODULE_OWNERSHIP_PATH` and `V35_API_MODULE_OWNERSHIP_SHA256`, never selected by the delta itself.
- [x] Extend original build/verify helpers with business receipt validation, generation and exact launch-binding checks. Legacy low-level role fixtures remain usable as inactive mechanism tests; native publication must require business metadata.
- [x] Tests assert active/source/static/state byte preservation and rejection before candidate writes.

### 2. Existing builder and reverse delta

- [x] Add failing sequential A/B, same-base stale B, fresh B rebuild, rollback A preserving B, addition/deletion and stale rollback tests.
- [x] Extend `build_module_candidate` in its existing file with a gateway-only business mode; pass no role-routing changes to the LaunchAgent. Reuse the same shared lock through preparation and verification.
- [x] Implement `prepare_module_rollback` in the existing integration helper. Verify target ancestry/lineage and current target bytes; reject intervening same-module/shared dependencies. Generate a reverse receipt and source from the retained parent; no old whole-app pointer switch.
- [x] Preserve existing delta checks while adding explicitly declared deletion support for reversing added files. Mode/bytes and non-target inventory remain verified.

### 3. Native entry seam

- [x] Patch only the frozen historical publisher reference and targeted tests. Lease required at every mutating entry; same gateway lock; mandatory business verifier before bootout and immediately before CAS.
- [x] Reject public whole-release rollback; retain emergency recovery of the immediately preceding current release.
- [x] Run isolated seam/failure tests. Mac current publisher identity, crash continuity, actual reload and health remain NOT_RUN/CANNOT_CONFIRM.

### 4. Verification and delivery

- [x] Run supplied publisher/proxy tests with original assertions, plus the new business matrix, in isolated Python 3.14 environment. Record any additional dependency exact source provenance.
- [x] Fresh independent reviewer inspects code, requirements, actual test receipts and unresolved runtime boundaries. Reproduce and fix concrete findings.
- [x] Package full after, applicable runtime/reverse and native-reference patches, before/after SHA, dependency/read ledger, requirement mapping, synthetic receipts, Mac preparation/rebinding and rollback steps.
- [ ] Sync a new independent GitHub handoff branch and read back commit/key blob identities; no merge/deploy.

## Review focus

1. Contract self-authorization, missing owner and duplicate/overlapping ownership must fail closed.
2. Candidate-root aliases, symlink ancestors, nested state data and malformed deletion receipts must not cause writes outside owned temporary roots.
3. A/B concurrency and rollback after later A or shared updates must preserve current bytes or reject before any service action.
4. A failed build must not leave a publishable partial candidate; evidence must preserve failure phase and exit code.
5. A non-running or unidentifiable native service cannot be labeled recovered/healthy. Historical pinned reference must not be advertised as a current deployment command.

## Rulings

- The supplied task already authorizes implementation and specifies its architecture. Complete the candidate and isolated tests without another design-approval stop; live switching stays pending as explicitly required.
- Business owner and live publisher evidence are absent. Implement enforcement against an externally pinned contract, leave real owners disabled, and deliver a separately labeled historical entry patch; do not invent current identity.
- Two exact test-only dependencies were found elsewhere in the same fixed GitHub commit: `owned_io.py` and `stage_service_overlay_contract.py`. They are unchanged dependencies, not new publisher/Stage implementations.
