# Rebound owner candidate evidence — 2026-10-09

- Repository: `lexi2016/v4`; development branch: `v5/rebound-owner-20261009`.
- Authorized baseline: `2719328494a9ec3177a7be56e7348f86dd0137f5`.
- Implementation commit (four necessary new files): `b078849c7f915973e8be6370d1fde691f9559582`.
- Source root: `/workspace/v4`; execution environment: saved cloud Linux, Python `3.12.14`.
- Recorded at: `2026-10-09T07:19:36.573507+00:00`.
- This evidence is static verification, not a product run or Mac acceptance.

| Path | Before SHA256 | After SHA256 |
| --- | --- | --- |
| `V5/src/v5_shadow/rebound_owner.py` | ABSENT (new file) | `9b454daf67fed315f3d7e204dcc35c961805d929300d56b3a641246a839c8fe3` |
| `V5/contracts/rebound_owner_capsule.json` | ABSENT (new file) | `0f407ac5206a1c96a29cdfe2bb16c627c026b4fdd1c052833fff9299c70a6e9d` |
| `V5/tests/test_rebound_owner.py` | ABSENT (new file) | `a3a712fc5e08931cb04401a76f2d6e763b44a0830c1115875fbba8ef98e6b15d` |
| `V5/docs/REBOUND_OWNER_20261009.md` | ABSENT (new file) | `03bfad43314e7071ddbf4c1bda752ff24bb500d43219abe6fc1069a59b90d496` |

Static checks executed:

- `ast.parse` on the new module and test source: PASS (no import or execution).
- Canonical capsule JSON digest equals the module's pinned descriptor: PASS.
- All three descriptor resource bindings: PASS.
- Existing 18 capsule files: SHA256 and Git blob SHA match original manifest.
- `git diff --cached --check`: PASS before the implementation commit.
- Allowlist: only the four new paths above; no modifications to manager_plan,
  legacy_adapter, worker, shadow_store, UI, archive, V4 or other parallel task files.
- Parallel read-only source audit and static review identified and fixed dir-fd
  guard compatibility, unproven nested-label propagation, synthetic manager admission,
  and conflicting snapshot/context identities. This is review, not execution.

Test candidates: **29** (28 contract/boundary/receipt/manager cases and one explicit
Mac opt-in original-owner integration). Every product test: **NOT_RUN** in cloud.
No provider calls, market acquisition, trading, service controls, deployment or merge.

Mac exact command and input contract are in `../REBOUND_OWNER_20261009.md`.
Original algorithm integration needs the existing Mac Python >=3.14 environment with
the exact V5 lock; the cloud's Python 3.12 is not a substitute.

Remaining evidence: original signal-date master receipt (the handed-off historical
four files omit it), history-wide unit consistency/currency, provider finality,
target-date eligibility/PIT, and natural execution. Missing proof remains
CANNOT_CONFIRM. Today's membership task and archive/announcement owners stay independent.

The historical counts and current panel counts in the handoff are not results of
this candidate. The old process hash is not proven. Real-input replay, manager
integration, API/UI, deployment, and natural-time acceptance are all **NOT_RUN**.

This evidence file is committed separately so it can name the immutable code commit.
The final delivery records the resulting branch HEAD and remote readback; this file
does not claim that a push/readback has occurred before it actually occurs.
