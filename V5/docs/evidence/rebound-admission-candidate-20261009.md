# Rebound evidence admission candidate

This adds an independent research selection reader. It does not replace or
claim completion of the original master owner, write a panel, collect data,
install a scheduler, enable trading, or update the daily ledger.

Status: candidate only. Cloud validation is AST parsing and source review.
Mac tests, real owner evidence adaptation, integration and natural execution
are NOT_RUN. No real HK units, finality or membership proof is claimed by this
delivery. Tests use explicitly synthetic admission fixtures with the committed
observation reader and panel read stubbed; the calendar, trust pins and byte
reads are exercised by the candidates without provider requests.

## Reachable result and preserved algorithm

`admit_rebound_observation` reads the committed observation artifact/manifest/
receipt through `read_rebound_observation`. It uses the unchanged observation's
two booleans: both true -> strict, one true -> near, both false -> excluded.
It introduces no threshold, epsilon, price conversion, zero filling or rank.
The frozen comparison is close <= 0.8 times prior 60-session high and current
volume >= 1.5 times prior five-full-session mean. Absolute amount, low rebound,
20-record context, master valuation fields and natural execution are not
admission conditions.

Admission is per target-member code. Each admitted row requires all 67 owner
attested cells: 60 exact prior-session highs, current close, and all six exact
full-session volumes. Each cell must match the SHA-bound panel copy. Current
close/volume, prior high maximum and five-volume mean also match the committed
observation's core values. The mean check uses the same pandas reduction as
the frozen calculation; the decision remains its original boolean.

Only that row's evidence can return `status=OWNER_VERIFIED`, with scope
`ONE_CODE_EXACT_60_PRICE_AND_SIX_VOLUME_SESSIONS`. This does not mark the whole
panel, the complete master owner, or a pending code verified.

Missing per-code proof, incomplete numeric input, duplicate panel rows, wrong
cells, mixed units/scales or a pre-close capture leaves that code pending.
Other proved codes can still be strict/near/excluded. Target members absent
from the signal panel are explicitly pending; panel codes outside today's
membership are separately listed. `READY` requires no pending member, so an
empty strict/near result is backed by complete membership accounting.

## Trust boundary

The process hosting the original owner provisions a policy path and its SHA
in deployment configuration independently of requests and evidence writers.
Only this privileged wiring calls:

```python
authority = load_deployment_authority(
    deployment_config.rebound_policy_path,
    expected_policy_sha256=deployment_config.rebound_policy_sha256,
)
selection = admit_rebound_observation(
    observation_root, committed_reference,
    authority=authority,
    attestation_id=request.owner_evidence_id,
    membership_id=request.membership_evidence_id,
)
```

The request supplies only selectors for already approved evidence. It cannot
supply a policy, a policy SHA, source contract, owner identity or VERIFIED
switch. No CLI or environment fallback exposes those trust settings. Python
code controlling the deployment capability is privileged; this is not a
defense against a compromised same-process administrator or dishonest owner.

The pinned policy explicitly approves each attestation and membership file
by immutable relative path and SHA, pins the current admission implementation,
the actual observation implementation digest and source capsule, and pins
original owner/decoder/document identities. These are not self-signatures.
The pin must not be populated automatically from an untrusted request. An
operator/owner must review the actual evidence and provision the approval.

`source_contracts` are independently approved original-provider semantics,
not arbitrary extra panel manifest fields. Each has an original owner code
SHA, decoder SHA and an actual saved contract document SHA; the policy states
HKD, RAW/UNADJUSTED price basis, positive price scale, SHARES/LOTS volume unit,
positive volume scale and the supported daily finality contract. All price
cells for a code must share one basis/currency/scale, and all six volume cells
one unit/scale. This candidate does not convert mixed sources. Ratios are
dimensionless, but this particular evidence interface requires original-owner
unit documentation before it admits a row.

Each source contract also contains `field_bindings` for the panel fields it
actually proves. Every used high, close or trade cell requires a binding for
its original field name, storage type, storage locator, conversion basis and
adjustment basis. For a documented VIPDOC trade field these might identify
`trade_v`, `uint32_le`, byte offset 24 and the exact scale/adjustment section
of the approved document; these facts alone do not prove the financial unit.
The independent owner must verify all entries against the pinned decoder and
contract document before approving the deployment policy. Descriptions copied
from an unverified manifest, an undocumented times-100 cache conversion, or
`NOT_PROVEN` placeholders cannot stand in for that review. The reader does
not infer types, units or conversion rules from magnitude.

The owner reviews and approves the raw-cell mapping. `raw_locator` identifies
the exact original decoded field/record for that review. This V5 reader binds
and rehashes those raw bytes and compares attested values with the panel; it
does not implement a second vendor decoder. Approving a fake or incomplete
mapping at the independent deployment boundary invalidates the trust model.

## Exact interfaces

The runtime validates exact field names. All SHA values are lowercase 64-hex;
times are timezone-aware actual timestamps; codes are `HK.00001` style. JSON
with duplicate keys or nonfinite numbers is rejected. Evidence paths are
relative to one deployment-configured root, with symlink components refused.

Policy `v5.rebound_deployment_trust.v1`:

```text
policy_id, evidence_root
owner_identity, membership_owner_identity:
  owner_id, owner_source_sha256, reviewer_id
observation_implementation_sha256 = sha256_json(observation._identity())
admission_implementation_sha256 = rebound_admission.implementation_sha256()
source_capsule_sha256 = observation.PIN
source_contracts[contract_id]:
  owner_source_sha256, decoder_sha256
  document: {relative, sha256}
  price_basis: RAW | UNADJUSTED
  price_currency: HKD
  price_scale: positive finite number
  volume_unit: SHARES | LOTS
  volume_scale: positive finite number
  finality_rule: DAILY_BARS_CAPTURE_AFTER_NATIVE_CLOSE
  field_bindings[high | close | trade]:
    native_field, storage_type, storage_locator
    conversion_basis, adjustment_basis
attestations[id]: {relative, sha256}
memberships[id]: {relative, sha256}
```

Owner evidence `v5.rebound_owner_cell_attestation.v1`:

```text
owner_identity, reviewed_at
observation_reference: {run_id, artifact_sha256, manifest_sha256, receipt_sha256}
target_date, signal_date, research_cutoff
panel_sha256, panel_manifest_sha256, calendar_sha256
raw_sources[source_id]:
  relative, sha256, source_contract_id, owner_source_sha256, decoder_sha256
  capture_started_at, captured_at, available_at
codes[code]:
  cells: [{date, field: high | close | trade, value, raw_source_id, raw_locator}]
```

Evidence binds the original observation cutoff exactly; approval/review may
occur later but must already have happened by actual admission time. Source
capture and availability must be no later than that observation cutoff.
Dates/windows come from the unchanged, SHA-pinned native calendar Python and
JSON. Only the current actual HK target day is admitted, and the runtime must
match the observation implementation and dependency receipt. Changing the
observation source for a repair-reader extension requires a new observation
and deployment policy approval, not a hardcoded old observation hash.

Membership evidence `v5.rebound_target_membership_attestation.v1`:

```text
owner_identity, target_date
capture_started_at, captured_at, available_at, reviewed_at
codes: sorted unique complete original-owner target membership
codes_sha256: sha256_json(codes)
raw_source: {relative, sha256}
```

The membership capture's HK date must equal target and its availability must
precede the observation cutoff. The deployment owner must verify completeness
against the existing membership producer before approving its digest. A 15:00
capture is labeled `AS_OF_TARGET_CAPTURE_NOT_PREOPEN_ATTESTATION`; it is never
backdated into preopen availability. Historical master names are not a
substitute for this membership authority.

## Finality without an invented provider flag

`DAILY_BARS_CAPTURE_AFTER_NATIVE_CLOSE` requires an independently reviewed
daily-product contract and a real provider capture beginning after each
covered session's calendar close. The reader uses the original native HK
calendar (full close currently 16:10; half sessions allowed for prior highs,
never for the six volume comparisons). It does not use a synthetic 15:00
clock or demand a provider flag that the protocol does not have.

`capture_started_at` here means actual provider acquisition, not a later disk
read of an old intraday snapshot. A `.day` byte read timestamp alone therefore
cannot satisfy this schema. If the owner has no documented product semantics
or true capture/availability lineage for inherited history, those codes must
stay pending until evidence is recovered. Presenting this schema does not
assert that such evidence already exists on the Mac.

## Minimal original-reader hooks

1. Existing owner creates/reads the unchanged committed numeric observation.
   The parent's repair reader extension can recognize its explicit internal
   gap-repair manifest; neither frozen vendor file is changed here.
2. Mac original owner reviews source documentation, decoder, raw bytes and all
   required cell mappings. It persists the above evidence projection without
   changing raw observations or claiming unproved inherited history.
3. The existing target-membership owner projects its actual saved capture.
4. Privileged deployment wiring approves exact evidence SHA values and calls
   this reader. The existing ledger can persist the returned selection and
   `selection_sha256`; this module writes no business product or new pointer.
5. Manager performs the existing ledger's trusted readback, then calls
   `manager_admitted_selection(selection, target_date=..., signal_date=...,
   research_cutoff=...)`. This pure consumer validates the selection digest,
   source references, safety flags, dates, per-group counts, unique/disjoint
   codes, full target accounting, two-boolean grouping and 67-cell evidence
   scope. It returns a deep copy and writes nothing. It must
   not rewrite it as the complete original master-owner proof or mark a natural
   run successful. Global trust/byte/date failures raise a coded ValueError;
   per-code deficiencies are in pending with exact reason codes.

Successful output remains `research_only=true`, `production_allowed=false`,
`orders_sent=false`, `full_master_owner_verified=false`, `natural_verified=false`.
No amount field is mislabeled HKD because no amount is projected. Proved price
and volume units apply only to the admitted row's checked core cells.

The manager cutoff must be at or after `evaluated_at`, not merely the earlier
observation `research_cutoff`: owner review/admission may finish later. All
source, evaluation and manager timestamps must remain on the same HK target
date. This consumer does not authenticate arbitrary JSON: `selection_sha256`
is an integrity checksum, not a signature. The existing trusted ledger must
bind the returned payload to its committed producer record before calling it;
request-supplied objects must never enter this hook directly.

## Mac verification candidates

From the V5 checkout in its existing pinned environment:

```sh
PYTHONPATH=src uv run --locked python -m unittest discover -s tests -p 'test_rebound_admission.py' -v
```

The suite includes real pinned-calendar loading, positive strict/near/excluded,
coverage-backed valid empty, missing target members, partial proof scope,
numeric gaps, policy/evidence/raw/document mutation, wrong pins, symlinks,
date/cutoff/source mismatch, duplicate cells, wrong values, nonfinite values,
pre-close captures, mixed scales and missing field/storage/transform contracts.
It does not demonstrate genuine source
proof or execute the original product calculator. The parent must separately
run the real existing-owner integration with actual approved Mac evidence.
Consumer candidates additionally cover late admission versus the manager
cutoff, date mismatches, content mutation, duplicate codes, inconsistent counts
or status, fabricated group/evidence labels, extra rank and deep-copy isolation.
