# HK_CONNECT: inspect and reuse the original exact-date authority

This is a local diagnostic recipe, not a claim of restored business output. No
real 20261009 authority or running Mac configuration has been accessed here.

## Proven original owner route

The fixed reference is `lexi2016/v4` commit
`e72607634d46146b0b6c0f4a0396f6b2939589f7`, under
`handoff/v4-running-source-20261005/canonical/`.

- `stage_center/hk_universe_preflight.py`: no CLI. The safe V2 callables are
  `validate_captured_hk_connect_membership_v2` (line 602) and the pure
  `build_captured_hk_connect_authority_v2` (line 765). The current domain reader
  already invokes both. `ensure_hk_connect_universe` (line 463) is the original
  current-day V1 collection/write path and is unsuitable for this inspection.
- `ops/_macos_research_panel_daily_parts/hk_capture_gate.py:26-42`: the original
  producer derives `store_root = args.hk_asset_root.expanduser().resolve().parent.parent`
  and passes that exact root as both store_root and universe_root to
  `ensure_hk_security_master(..., capture=capture, membership_only=True)`.
- `ops/ensure_hk_security_master.py:551-656`: V2 publication writes/readbacks the
  five immutable upstream files and then retains an existing publication receipt
  or timestamps a new one with the actual current time. A new late publication
  cannot establish historical availability.
- `ops/_macos_research_panel_daily_parts/hk_market_capture.py:608-618`: the
  membership callback runs before a quote/snapshot failure is raised. A failed
  panel or quote lane therefore does not by itself prove membership publication
  is absent.

The fetched contract source is 40,555 bytes, SHA256
`9d3d2c2d5ff3bd1c7713a9485e88000ae882f58b0a457b734656094606ba2941`.
This is a reference identity; do not replace the live owner pin with it merely
to make a check pass. The running pin must match the owner identity already
bound in the original target artifact and publication chain.

## Exactly six authority files

Let `D=20261009`, `A=SHA256(raw artifact bytes)`, and obtain
`R=owner.authority_run_id(D,A)`. The original implementation derives R as the
first 24 hexadecimal characters of SHA256 of
`HK_CONNECT_FULL_MARKET:20261009:<A>`.

1. `universes/20261009/HK_CONNECT_FULL_MARKET.json`
2. `universes/20261009/HK_CONNECT_FULL_MARKET.authority/<R>/manifest.json`
3. `universes/20261009/HK_CONNECT_FULL_MARKET.authority/<R>/receipt.json`
4. `universes/20261009/HK_CONNECT_FULL_MARKET.current.json`
5. `universes/20261009/HK_CONNECT_FULL_MARKET.authority/<R>/capture.json`
6. `universes/20261009/HK_CONNECT_FULL_MARKET.authority/<R>/publication.json`

All remain under one existing owner store root. Do not reconstruct a missing
file, mix run directories, substitute D-1, or relabel source dates.

## Minimum local context export

Use the existing running service's interpreter and app directory. In the
diagnostic child process, retain the actual three universe service bindings:

`V4_MANAGER_UNIVERSE_ROOT`, `V4_MANAGER_UNIVERSE_OWNER_ROOT`, and
`V4_MANAGER_UNIVERSE_OWNER_SHA256`.

Also retain the existing optional D-1 bindings exactly as configured:
`V4_MANAGER_HK_CAPTURE_RECEIPT_ROOT` and
`V4_MANAGER_HK_DISPATCH_RECEIPT_ROOT`. Do not remove them to suppress the original
fallback, and do not supply invented roots when they are absent. The helper
records each as `NOT_CONFIGURED`, `BOUND_CANONICAL` with its normalized existing
root, or `CANNOT_CONFIRM` with a bounded diagnostic. Invalid canonical root
bindings stop the inspection before calling the reader. These two variables
are not changed by the helper.

The shell's environment is not automatically proof of the service environment;
verify these five allowlisted bindings against the existing service launch
configuration. Do not dump the entire environment or repin a SHA from whichever
source file happens to be present. Obtain `V4_HK_JOB_ASSET_ROOT` from the original
HK job's actual `--hk-asset-root` argument; it is not a guessed path.

The package identifies a previously saved owner readback. The following local
export refuses different bytes and outputs only the four context values the
existing Connect scope reader uses, plus provenance. No market rows, names,
quotes, or account information are output.

```bash
V4_OWNER_READBACK='/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_LIVE_UI_API_REPAIR_MAC_20261010_R1/ui/owner-readback.json'
V4_DIAG_DIR="$(mktemp -d)"
"$V4_PYTHON" - "$V4_OWNER_READBACK" > "$V4_DIAG_DIR/context.json" <<'PY'
from datetime import datetime
from pathlib import Path
import hashlib, json, re, sys
p = Path(sys.argv[1])
raw = p.read_bytes()
sha = hashlib.sha256(raw).hexdigest()
assert len(raw) == 16410447
assert sha == '6c0fe13667f5872a10cb83608bd29c1f4a7acdfa3c12e10af75cae2d7e40bdbc'
value = json.loads(raw)
original = value['plan_context']
context = {key: original[key] for key in (
    'plan_trade_date', 'research_cutoff', 'market_session', 'calendar_sha256')}
assert context['plan_trade_date'] == '20261009'
assert type(context['market_session']) is str and re.fullmatch(r'\d{8}', context['market_session']), 'CANNOT_CONFIRM:MARKET_SESSION_DATE_INVALID_OR_MISSING'
datetime.strptime(context['market_session'], '%Y%m%d')
assert type(context['calendar_sha256']) is str and re.fullmatch(r'[0-9a-f]{64}', context['calendar_sha256']), 'CANNOT_CONFIRM:CALENDAR_SHA_INVALID_OR_MISSING'
assert type(context['research_cutoff']) is str, 'CANNOT_CONFIRM:PERSISTED_CUTOFF_REQUIRED'
assert datetime.fromisoformat(context['research_cutoff'].replace('Z', '+00:00')).tzinfo is not None, 'CANNOT_CONFIRM:PERSISTED_CUTOFF_REQUIRED'
source = {'path': str(p), 'sha256': sha, 'size_bytes': len(raw)}
product = value.get('plan_product')
if isinstance(product, dict):
    for output_key, input_key in (('run_id', 'run_id'), ('plan_sha256', 'sha256')):
        item = product.get(input_key)
        if type(item) is str and len(item) <= 2048 and '\n' not in item and '\r' not in item:
            source[output_key] = item
print(json.dumps({'context_source': source, 'plan_context': context}, ensure_ascii=False, indent=2))
PY
```

If that saved file is unavailable or its SHA differs, obtain the original
owner's correctly identified context and its own independent SHA. Do not put a
current clock, a guessed cutoff, or a different response into this export.
The helper requires an actual date string for `market_session` and a 64-character
lowercase hexadecimal scalar for `calendar_sha256`; missing or malformed values
return an explicit `CANNOT_CONFIRM` diagnostic. It passes only the four validated
context scalars to the original reader, and does not export nested context data.

## Inspect the current root and the single original-producer root

Place `inspect_connect_metadata.py` in the local diagnostic directory. With
`V4_LIVE_APP_ROOT`, `V4_PYTHON`, and `V4_HK_JOB_ASSET_ROOT` populated from the
existing configuration, run:

```bash
PYTHONDONTWRITEBYTECODE=1 "$V4_PYTHON" /exact/local/path/inspect_connect_metadata.py \
  --app-root "$V4_LIVE_APP_ROOT" \
  --context-json "$V4_DIAG_DIR/context.json" \
  --producer-hk-asset-root "$V4_HK_JOB_ASSET_ROOT" \
  > "$V4_DIAG_DIR/hk-connect-20261009-metadata.json"
```

The helper checks the reviewed current Connect/domain reader SHA, invokes the
unchanged original `read_scope`, preserves the existing owner pin and cutoff,
and outputs only bounded scalar source metadata, counts, hashes, paths, statuses,
and code-only gaps. It compares at most two explicit **authority roots**, without
searching for additional authority roots. This is not a claim that it accesses
only two directories: after target-authority failure, the unchanged `read_scope`
may read the two configured D-1 receipt roots, linked capture/dispatch files, and
original security-master source references. It also uses the original calendar
reader. The report records both D-1 bindings and the permitted original read
route; D-1 results contain only bounded metadata and gaps, never raw rows.
A temporary authority-root binding is confined to this separate diagnostic
process; the live service configuration and both D-1 bindings are unchanged.

The output records that inherited shell values still require comparison with
the actual service config. Do not interpret the diagnostic process as a new
scheduler or owner execution receipt.

## Decision after the local read

- Current manager root missing, original producer root OWNER_VERIFIED: there is
  evidence of a possible wrong-root consumer binding. Check the same target,
  owner contract SHA, run/capture/product SHA, acquired_at and available_at in
  the metadata. Correct only the proven existing-service binding, then read the
  same API/UI target and inspect the original focus-owner output. This validates
  membership authority, not formal Stage, natural execution, or nonempty picks.
- Both roots missing: the root comparison did not find a reusable exact artifact.
  Inspect the original producer's exact-date execution metadata. Do not call the
  collector to backfill historical capture time.
- Existing artifact with missing publication or failed chain: retain the gap.
  Running the publisher now would timestamp present availability. Do not
  fabricate or backdate a publication receipt.
- Owner pin, date, SHA, membership, or cutoff mismatch: preserve the existing
  rejection. No consumer gate change is justified by this inspection.
- D-1 capture verified: retain it as separate source evidence; target-date V2
  authority still controls eligibility.

Only the small context export and resulting metadata report need to leave the
local machine if further review is requested. Full captures and raw readback
bodies remain local.

## Validation of the diagnostic helper

The helper was smoke-checked against two synthetic empty authority roots using
the actual retrieved original owner and the assembled current domain reader.
Checks cover D-1 roots absent, existing D-1 roots preserved and actually passed
through the original fallback, invalid canonical D-1 roots failing closed,
malformed/missing context scalars, and bounded diagnostic/gap output. Commands,
results, and helper/source SHA are recorded in `helper-verification.json`.
No real market inputs, owner run, service environment, or business result were
validated by these checks.
