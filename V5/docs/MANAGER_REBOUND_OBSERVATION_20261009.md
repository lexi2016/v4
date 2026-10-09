# Manager read-time rebound observation candidate

The five independent-owner files are copied byte-for-byte from
`e11197d5056af80c6f6a2e80579e2cd2c3910b80`. No algorithm, owner readback,
snapshot consistency check, unit/finality gate or original manager screen changes.
Only manager_plan.py and a new integration test add the consumer connection.

Existing manager requests still work. Add this optional top-level binding:

```json
{"rebound_owner":{"root":"/absolute/private-rebound-output","reference":{"run_id":"<32hex>","artifact_sha256":"<64hex>","manifest_sha256":"<64hex>","receipt_sha256":"<64hex>"}}}
```

Use the exact committed reference returned by the independent owner, not its
legacy_diagnostic. The output root must be separate from all manager input/output
roots, including the optional legacy rebound shadow root (same and ancestor/descendant
paths are rejected; distinct siblings are allowed). Manager reads/validates original three-file receipt before and after the
workspace computation; it never starts a rebound calculation. Malformed binding
identities/overlapping roots reject the request. Missing/corrupt committed bytes
produce a CANNOT_CONFIRM observation with the original read error, preserving
other workspace lanes instead of passing unverified content.

The ordinary workspace payload gains `rebound_research_observation`. It contains
only manager_projection's downgraded observation, blockers, original run reference
and explicit read-time scope. It never carries legacy_diagnostic or replaces
market_screen/daily_channels/selection. Saved original plan bytes and same-run
readback remain unchanged: this field is an independent response observation,
not a claim that the saved plan consumed this owner. Ordinary API publication
already carries the full payload. No UI renderer or deployment is added here.

Projection uses the RETURNED workspace plan_context (including saved historical
cutoff), not blindly request.now. Target/signal mismatch, synthetic inputs,
owner request cutoff or actual finished_at after that cutoff suppress observation.
Units, provider finality, target membership, owner-origin/read-lease and natural
run evidence remain unproven. Formal eligible_screen is always null.

Remaining real input gap from the owner handoff: signal-day master original
manifest/artifact/receipt, with exact file hashes, is required alongside panel
manifest/parquet. Old four-file historical witness alone is insufficient. Missing
receipt is not synthesized; neither old master nor today's target qualification
replaces the required signal-day master. No real owner run is claimed here.

Mac commands in the existing isolated checkout (cloud product tests NOT_RUN):

```sh
cd /absolute/v4/V5
PYTHONPATH=src:tests python3 -B -m unittest discover -s tests -p 'test_manager_rebound_observation.py' -v
PYTHONPATH=src:tests python3 -B -m unittest discover -s tests -p 'test_manager_plan*.py' -v
```

The eight integration tests use explicitly fabricated contract fixtures through
actual manager subprocess + original owner three-file readback. They test failure
visibility, bad receipt, date/cutoff, root overlap, saved-plan separation, downgraded
recorded observation and synthetic rejection. They do not claim actual algorithm
execution or real-market evidence. The independently supplied test_rebound_owner.py
and its optional original-algorithm suite retain their original Mac instructions.

Static provenance: manager baseline 73262cb3f7a10414dad459a4b4e9f0dea0623f5e;
manager_plan.py before SHA 564df49c79527caa874ff041247f98c8b4f48d4e41c3ec2efcf2a5a7dc24817f;
after SHA cfb8d766eb55bd2af4bfdcd32cca745bb3ee0ca943aff5d906b6c1ebfad0d93d.
Cloud AST/diff checks only; Mac tests, real integration, API/UI and deployment NOT_RUN.

Follow-up path admission tests add same-root, both nesting directions and distinct
sibling coverage for legacy shadow versus rebound_owner. This does not change
legacy-only request behavior or claim pairwise disjointness of pre-existing input
groups; it requires the NEW observation root to be disjoint from each input/output
root. Product runtime validation remains delegated to Mac.
