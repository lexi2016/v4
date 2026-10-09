# Strict V5 manager membership binding candidate

Optional top-level request key `membership`:

```json
{"membership":{"root":"/absolute/separate-private-membership-root","files":{"<each of the seven relative JSON paths>":"<raw SHA256>"},"authority_owner_sha256":"2b121a55eeff37a1838f64e47a3ee5abf0a3f2e19afae87a6fcca4a22e08c7ef","require_v2":true}}
```

No arbitrary owner-root/code loading is accepted. authority_owner_root resolves to
this release's verified `V5/vendor/hk_membership_baseline`, pinned by the existing
source descriptor. Binding a different owner SHA or require_v2=false is rejected.
The seven exact artifacts are artifact/manifest/receipt/current/capture/publication
plus retained sdk.capture.json, all under universes/<target_date>/. Parent Mac
should map its existing manager-reader-binding.json fields to this contract;
cloud has NOT read that Mac-local file. Do not invent missing file hashes.

The new root must not overlap manager input/output, legacy rebound or independent
rebound roots. Before owner execution each raw file is SHA-checked and copied
privately; the original input set is checked again after manager execution.
Seven expected paths are independently reconstructed by the pinned v2 reader.
The retained SDK SHA and its producer/run/date/plate responses must match capture.
Input errors remain explicit CANNOT_CONFIRM scope gaps; wrong owner or malformed
binding rejects the request. Missing membership retains the old unbound behavior.

An isolated child executes unchanged read_universe_evidence(require_v2=True),
with actual wall-clock readback and no injected historical clock. Python guards
prohibit writes/network/process creation (not an OS sandbox). A transport adapter
returns that native reader's codes/source or original error/diagnostic to the
UNCHANGED connect_selection.read_scope. It checks original target/date/calendar,
acquired_at and persisted available_at against each workspace context cutoff;
it retains original filter_cards/gate_workspace and selection diagnostics.
No alternative eligibility or ticker-list gate is implemented.

The membership binding participates in original workspace input identity and
saved-plan/same-run attempt/readback through the original scope path. It is not
an appended observation-only field. The response also includes independent
membership_readback for verification; ordinary published workspace carries the
original eligibility diagnostics. No API/UI deployment is performed here.

Mac real receipt reports 698 members, available_at 2026-10-09T10:01:07.690323Z.
That is later than the previous plan cutoff 2026-10-09T18:00:56.016117+08:00
(10:00:56Z): DO NOT reuse that cutoff. Use actual current time for a NEW run,
then independently read it back. No backdated publication or clock override.

Separate unresolved gaps:
- `_workspace_security_master_root` remains unbound. Connect membership is not
  a security-name/issuer master and does not resolve the 1735-material mapping.
- existing_materials.project_archive reads article.retrieved_at and available_at
  explicitly (lines 46–48), adding ARCHIVE_ARTICLE_ACQUISITION_TIME_MISSING when
  absent. The frozen archive contract _ARTICLE_FIELDS instead lists collected_at,
  first_seen_at and published_at; it rejects undeclared extra fields. No owner
  attestation equates these timestamps. This candidate changes none of those
  fields or PIT checks. Publication/current time is never substituted.
- 100 missing structured themes remain an independent original input gap.

Mac candidate commands (cloud runtime tests NOT_RUN):

```sh
cd /absolute/v4/V5
PYTHONPATH=src:tests python3 -B -m unittest discover -s tests -p 'test_manager_membership.py' -v
PYTHONPATH=src:tests python3 -B -m unittest discover -s tests -p 'test_manager_plan*.py' -v
```

Six tests build synthetic 698-member private products with the existing recovery
fixture, then exercise actual manager subprocess/original scope: admitted v2,
after-cutoff rejection, bad hash isolated, wrong owner/v1, missing seventh file,
and original refresh/readback. Fixture times derive from current wall clock,
never a future fixed cutoff. They do not claim real SDK origin or selection.
