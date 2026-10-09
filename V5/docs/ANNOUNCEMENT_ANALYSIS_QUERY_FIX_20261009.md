# Exact announcement analysis query publication

Base: 7f31b7ed227a7ce5a1911301a1475b1683f7391d (parent reports Mac 11 new +33 related PASS, real b30c28d3e6c2459cb4497787ce16fa53 plan consumed e724d07b product with SATISFIED/MATCHED). The new issue is publication identity: EXPLICIT owner readback was saved under the default query. Browser ANNOUNCEMENT_ANALYSIS_RESPONSE_DATE_INVALID is correct. Cloud did not read Mac RESULT.json or screenshot.

No frontend validation changes; no relabelled payload. Existing read_owner(binding,cutoff) remains the original explicit path. New opt-in default_analysis=True first verifies that same original explicit binding/owner chain, then binds the SHA-verified existing manager contracts/trading_calendar.py and market_calendar_2026.json into the isolated child's contracts namespace and actually invokes the original announcement_analysis.read(owner,target,None). That function resolves previous_hk_session and creates PREVIOUS_HK_TRADING_SESSION itself. OfflineAnalysisOwner still requires the resolved date to match its recovery catalog. If it does not, fail; never substitute the explicit response under the default query. Both original vendor trees remain unchanged.

New publisher v5_shadow.announcement_analysis_api reads both variants through that owner, verifies product SHA equality, and publishes an atomic generation containing these exact keys for target 20261009:

| GET path/query | Response date_selection_basis | Response publication_date |
|---|---|---|
| /api/v4/manager/research/announcements/analysis?date=20261009 | PREVIOUS_HK_TRADING_SESSION | 2026-10-08 |
| same path ?date=20261009&publication_date=20261008 | EXPLICIT | 2026-10-08 |
| same path ?date=20261009&publication_date=2026-10-08 | EXPLICIT | 2026-10-08 |

Both ISO and compact explicit date aliases are supported by the original date parser and stored as separate exact query keys. No implicit variant is manufactured. The default record replaces the previously misbound default using compare-and-swap; unrelated module routes/dates remain. API generation publication only: owner product/import/recovery/readback files, original plans and their SHAs are not written, and no business classification is recomputed. NOT_ASSESSED and null counts remain unchanged. No network request is made by the publisher; only original private file reads and the module's immutable publication store.

## Mac minimal actions

Do not repeat the already-passed 7f31 full suite. On the fixed follow-up commit:
```bash
PYTHONPATH=V5/src:V5/tests python3 -B -m unittest test_announcement_analysis_api -v
V5_ANNOUNCEMENT_OFFLINE_TEST_BUNDLE="<existing fixed 1a699a0 bundle>" \
PYTHONPATH=V5/src:V5/tests python3 -B -m unittest \
  test_manager_offline_announcement.OfflineAnnouncementOriginalChainTests.test_default_query_uses_original_calendar_and_real_default_read -v
```
Four new publisher/query tests and one original-fixture default-read test. Cloud only AST/source/hash/diff checks; tests NOT_RUN.

Reuse the existing four-field announcement_offline_owner binding JSON from the 7f31 manager request. If only the original manager_binding.v1.json is available, this derives the four fields without changing it:
```bash
python3 - "$ORIGINAL_MANAGER_BINDING" "$PRIVATE_CONSUMER_BINDING" <<'PY'
import hashlib,json,sys
from pathlib import Path
raw=Path(sys.argv[1]).read_bytes();owner=json.loads(raw)
result=dict(root=owner['owner_root'],binding_sha256=hashlib.sha256(raw).hexdigest(),
            target_date=owner['target_trade_date'],publication_date=owner['publication_date'])
with Path(sys.argv[2]).open('x') as stream:json.dump(result,stream)
PY
```
Use the same isolated module config that currently serves the announcements/analysis route (its routes must include that exact path). Obtain CURRENT_GENERATION_SHA from its existing active.json; do not supply null for a populated root or reuse a stale SHA. Publish corrected query records using:
```bash
PYTHONPATH=V5/src python3 -B -m v5_shadow.announcement_analysis_api \
  --binding "$PRIVATE_CONSUMER_BINDING" \
  --config "$EXISTING_ISOLATED_ANALYSIS_MODULE_CONFIG" \
  --expected-generation "$CURRENT_GENERATION_SHA"
```
No code change or restart is needed in an already-running module_api to see the new generation; use the existing isolated preview/gateway workflow if the temporary processes were closed. This command is handed to Mac, not executed in cloud.

Acceptance: GET all three table entries through the isolated gateway, verify basis/publication/product SHA and null counts, then open `/manager-selection/?plan_date=20261009` for default and `/manager-selection/?plan_date=20261009&announcement_date=20261008` for explicit. Inspect the actual announcement-analysis request and confirm browser no longer shows RESPONSE_DATE_INVALID. Retain existing plan b30c28..., 698 qualification and 695 observation; do not regenerate them for this query-only correction. Before preview switch use the existing single Mac publisher; this cloud change does not activate or deploy services.
