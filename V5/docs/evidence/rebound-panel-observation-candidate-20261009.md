# Panel-only rebound observation candidate evidence

- Repository/branch: `lexi2016/v4`, `v5/rebound-owner-20261009`.
- Original delegated baseline: `2719328494a9ec3177a7be56e7348f86dd0137f5`.
- This increment starts from: `e11197d5056af80c6f6a2e80579e2cd2c3910b80`.
- Immutable implementation commit: `9d3c1ea910454e5bf405687d21de1c4fa021f22e`.
- Static verification root: `/workspace/v4`; cloud Python 3.12.14, Linux.
- Recorded UTC: `2026-10-09T10:31:54.441899+00:00`.

| File | Before SHA256 | After SHA256 |
| --- | --- | --- |
| `V5/src/v5_shadow/rebound_observation.py` | ABSENT | `ecf2473791bddea11ac307472a0564193518fb121e15eaf17d7e6a2ff4e8041b` |
| `V5/contracts/rebound_observation_capsule.json` | ABSENT | `0fabf3acd32f9cca6286bbf72f4a51cd8c1a5701e745393ed2a52cdd1bb21062` |
| `V5/tests/test_rebound_observation.py` | ABSENT | `27df7d56ee86b6a912514c3af398a412b9785167ae326fe604caa2e3c9512506` |
| `V5/docs/REBOUND_PANEL_OBSERVATION_20261009.md` | ABSENT | `6dfc8c20921fa671b7bfb7220904b9971d71a23b34b9ed1473bbf5a14067e450` |

Executed static checks only:

- New module and test AST parse/compile: PASS; no product module import or execution.
- Both embedded Mac subprocess test scripts parse/compile: PASS.
- Reconstructed extracted-calculator AST compile: PASS, **not executed**.
- Capsule canonical pin, all bindings, frozen-source SHA and each extracted span SHA: MATCH.
- Fixed original AST boundary counts: setup 11, loop arithmetic 59, background 3.
- Original complete-master owner, manager_plan, legacy_adapter, worker, shadow_store,
  and frozen workspace_plan bytes match the increment baseline; no existing file changed.
- Staged `git diff --cached --check`: PASS before implementation commit.
- Parallel read-only review found and fixed public-schema/source-binding weaknesses,
  caller-selected worker time, ambiguous background naming and shared projection lists.
  Final review found no definite new execution blocker; this is not a product test result.

13 new test candidates, including two opt-in Mac cases: original-owner differential
(15 input variants; independent list of 26 numeric/state fields plus amount), and
panel-only execution with no master directory through durable receipt/readback.
Semantic tampering cases cover extra eligibility labels, inconsistent arithmetic
patterns, promoted units, and mismatched panel identity.

Cloud product tests: **NOT_RUN**. Mac new tests: **NOT_RUN** here. Real data: **NOT_READ**.
Parent reports the previous owner 29 tests and manager wiring 10 tests passed on Mac;
that does not attest this new extraction, observation adapter, or real-panel output.
No collection, trading, deployment, merge, manager edits, or frozen vendor changes.

Runtime result identity is FROZEN_NUMERIC_BODY_EXTRACT_NOT_COMPLETE_MASTER_OWNER.
This increment removes the unrelated complete-master dependency only from the new
current-observation entrypoint. Original panel witness, date/PIT, stable-copy and
core numeric completeness checks remain. Source/currency/scale/finality/eligibility
unknowns do not become verified labels; eligible_screen is always null.

Mac commands, exact two-role input contract, durable result viewing and separate
manager observation integration are in `../REBOUND_PANEL_OBSERVATION_20261009.md`.
Current target is HK today, clock is taken by the worker; this is not a historical
10/8 PIT reconstruction or a replacement for 10/9 intraday quotes.

This evidence names the immutable implementation commit. Final branch HEAD and
remote readback are reported after the actual push; no pre-claim of synchronization.
