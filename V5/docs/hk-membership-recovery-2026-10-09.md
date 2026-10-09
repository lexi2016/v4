# V5 retained SDK membership recovery candidate

Only HK Connect membership is published to an explicitly marked, fresh V5
private directory. No OpenD call, V4 write, market-data collection, shared latest
pointer change, API publication or manager-plan mutation is performed by this
candidate. Existing 698 rows are not reduced to the legacy 651 constant.

Frozen source: 8342862f05ca9f6516f51b3164b6110651e5af77, canonical handoff:
- hk_market_capture.py: 0a9651f88bc8a50d4b5e8ec4b6775a5291918f9f2556cf37c05b80a55cdfd84a
- hk_universe_preflight.py: 9d3d2c2d5ff3bd1c7713a9485e88000ae882f58b0a457b734656094606ba2941
- ensure_hk_security_master.py: 6c341a33c0283b023219c46cc2a1c6aaca49cf4b5dcb88aa2fb5527a13145601
- manager_research_evidence.py: 4bfd8ec335eade9a97340fe17fc0742f2dba546d0e254fdfed2833ed324bb73d
All four match the Mac report. No reliance on the unavailable 55a5ba0 GitHub ref.

The V5 capsule keeps the original v2 membership checks and independent evidence
reader. Its preflight copy adds strict recovery provenance validation and changes
only the recovered branch's provenance labels to RETAINED_FUTU_SDK_RECOVERY /
RECOVERY_FROM_RETAINED_SDK_CAPTURE. Native capture semantics remain unchanged.
Original build_captured_hk_connect_authority_v2 creates the bytes/hashes; the
unchanged read_universe_evidence(require_v2=True) reconstructs and verifies the
persisted chain against the explicitly pinned V5 contract owner. The publisher
writes immutable files in a fresh marked root, with real publication available_at
only after all five owner artifacts plus retained SDK bytes are read back.
The original as-of gate is exercised against the acquisition instant and must
reject publication that became available later. MANUAL_RECOVERY/natural=false
remain explicit. Source SDK bytes and all output hashes are re-read before return.

The SDK raw capture is bound by raw SHA and original producer code SHA. Both
plate response hashes, complete column/row sets, return codes, dates and member
codes are validated by the original v2 function. It retains tagged non-finite
SDK values byte-for-byte in the evidence rows. It never decodes {$float:nan} as
a business field or treats it as zero. Bare JSON NaN/Infinity is rejected.

No quote or security_master_rows are fabricated. quote_status, panel_status and
security_master_status stay NOT_EVALUATED; price_unit and market_finality are
null. This decouples membership from failed quote serialization without claiming
that quotes or the security master passed validation. In particular stock_owner
is required and cannot be changed to null and called valid; child_type may be
null, shares/market-value nullable handling cannot admit dict/inf/negative values.
Those rules have not been relaxed. Today's complete quote frame was not retained,
so the field that failed today remains unknown. Historical stock_owner696 and
shares/market-value31 NaNs are historical observations, not today's counts.

Mac tests, no cloud product execution:

```sh
cd /absolute/v4/V5
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_hk_membership_recovery.py' -v
```

The six synthetic tests cover 698 membership, preserved tagged NaNs/unknown
quote fields, bare NaN rejection, response hash corruption, invalid code,
quote-failure separation, source SHA mismatch and prior-availability rejection.
Static cloud verification is not a passing Mac run.

For the real recovery, the existing Mac task creates a NEW isolated output
folder and `.v5-hk-membership-root` containing `v5.hk-membership-root.v1\n`.
Call run_recovery with the following JSON, substituting only the private output:

```json
{
  "sdk_path": "/Users/lexi/Documents/Codex/2026-10-05/task-3/v5-hk-eligibility-20261009-current/capture-manifest.sdk.capture.json",
  "sdk_sha256": "80b881a8bee1823b716aa0f5c8be5c4894bbddc75108ac0ebce8dd5a17bfbb69",
  "output_root": "/absolute/new-v5-private-membership-root",
  "target_date": "20261009"
}
```

Use a new request/plan cutoff AFTER the actual publication available_at. Never
bind these 15:00:08 HK observations to a pre-open plan or the old 14:58 cutoff.
Compare all 698 codes with independent-readback.json, reported code-set SHA
ce3c7eb8757c6c4d9dc8540653fb9d355479b5940547a9850147a847963c0446;
use its documented serialization, not an assumed hash format. Publishing this
private prerequisite does not itself wire or publish a manager workspace.
