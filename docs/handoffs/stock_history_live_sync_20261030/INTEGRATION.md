# Per-stock history completion → existing research website

Scope: local research website publication only. Frozen R2 runner, historical
rules, raw prices, pins, Main/Stage and the framework remain unchanged.

The original failure is a missing connection: R2 atomically completes offline
`stocks/<symbol>/RESULT.json`, but the website still reads the older dated
product/index. The installed chart bridge also allows only one changed row.
An incoming same-date product currently resets the selected stock.000554 has
only1/7887 dates in that older product; its real R2 history remains in progress.

`ops/sync_stock_history_completion.py` prepares an exact completed subset using
only accepted R2 row/cache/case refs. It verifies date, generation/input, original
rule/config/formula/code hashes, calendar values, all event dates/aggregates and
non-statistical row equality. The unchanged5808-row universe, candidate247
memberships, counts, original chart refs and other date/index entries survive.
Only new completed stocks are processed after a previous publication; the exact
published receipt refs and previously validated immutable rows are reused.

Preparation writes exclusively into the isolated `--stage` directory. Its
`PLAN.json` binds the before-index/event SHA and every immutable target/staged
ref. On activation, the original Main owner's hash-bound `save` first persists
all immutable objects, then takes the existing Main A_LONG stable-inode flock, rescans completed receipts after any lock wait, CAS-checks both old pointers, atomically replaces
one complete index and finally emits the existing completion event. Every sidecar
is already accessible when the new index becomes visible. If emitting the event
fails, the new index is restored only if it still equals our just-written value.
No history producer, rendering, acquisition, formula execution or page-time
calculation is added.

Names retain the same projection with a new numeric-manifest binding. Company
material shards remain byte-for-byte unchanged: the new materials index declares
both the current numeric manifest and `source_numeric_manifest` for those old
shards. Existing event shards likewise keep per-symbol `case_numeric_origins`;
new completed cases bind the new manifest. Requested event-case GETs still
require exact statistics SHA, generation, input and date. No materials are
refetched or relabelled as newly researched.

The chart bridge checks the exact origin/current row-ref difference against the
bound `history_updated_symbols`; every changed row is checked once while
preparing publication. Each chart GET reads only its requested changed old/new
row, preserving all original chart identity and file SHA checks. It never reads
all247 full caches per click. Canonical source and the exact installed API role
are separate: apply only the latter profile delta, never overwrite the active
role with the canonical file. See `EXACT_INSTALLED_READER.diff` and
`deployed_api/research_lane_source.py`.

The existing SSE path emits `a_share_daily_completed` after index/event identity
matches. The UI preserves same-date/generation selected stock and sidebar filter,
then reloads that stock's bound details. A bound incomplete stock displays
“历史统计补齐中 · 已发布历史覆盖…完成后自动更新” and suppresses unfinished success cards. Completed
stocks display their accepted history. Group labels and earlier group-binding
repair remain included. `daily.html` changes only this script's cache version.

Activation commands (run from this worktree after the root's reviewed lease and
fresh plist/PID/manifest/index CAS, using the absolute PANEL_PYTHON):

```sh
"$PANEL_PYTHON" ops/sync_stock_history_completion.py --batch "$B10" --root "$DAILY_ROOT" --stage "$B11/prepared_activation"
"$PANEL_PYTHON" ops/sync_stock_history_completion.py --stage "$B11/prepared_activation" --publish
"$PANEL_PYTHON" ops/sync_stock_history_completion.py --batch "$B10" --root "$DAILY_ROOT" --stage "$B11/watch" --watch
```

The retained watcher uses macOS kqueue vnode notifications on the existing stock
directories and newly created directories; startup reconciliation closes the
subscription race. It has an exclusive owner lock and preserves every R2
checkpoint. No timed polling or scheduler registration is used. The exact shared lock is `/Users/lexi/Library/Application Support/com.lexi.v35.local/state/dispatcher/scheduler_lane_owners/A_LONG.lock`; it is opened without create/unlink and held only across fresh reconciliation and publication. Main scheduled1540/1610/1640 already holds this inode through its inherited lane FD. Root freezes concurrent legacy/direct manual publication during this phase: those bypass paths are not globally prevented by code. Any future manual publisher must obey the same existing lock and ownership SOP. Its lifetime is
independent of UI requests. A separate detached retained supervisor and log/PID
receipt are required at activation, without changing the frozen R2 runner.

Validation:7 targeted source tests are covered;6 passed together after the two reviewer P2 fixes, then4 affected publication/owner-lock tests passed after adding shared ownership. The two fixed P2 findings were misleading old-row-as-current-checkpoint wording and missing cross-day latest/event rejection. Existing unaffected PASS is reused; exact installed-profile isolated reads passed000554 pending,
001328 complete861dates and002003 complete5266dates, with original chart READY,
materials PARTIAL_RECEIVED, correct manifest and appropriate event cases. The
isolated preparation includes18 actually completed stocks. This is not live
publication or natural-run acceptance. Root's real UI should load the new asset
once, then remain open across a subsequent genuine per-stock completion to
observe automatic refresh.

Rollback: preserve the original API plist/release and the before-index/event
bytes. Under the release lease, restore them only if they still match this
activation's after refs. Stop only this task's watcher after recording its last
publication; do not stop/restart R2, Main or Stage. Keep all immutable results,
checkpoints and failure receipts. Drift from another owner stops this adapter
without replacing their data.

RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false;
orders_sent=false. No model, PIT, trading or full247 completion claim.

## Actual installation and real completion acceptance

The independently accepted source was installed only into
`a-stock-history-auto-sync-20261030-r1-api`, manifest SHA256
`790e1e067123510a0a7da8ed2017fcfd3ebaf0849073eef5017855e5705d3df1`,
API PID90855. Retained kqueue consumer90871/supervisor90870 publishes completed
R2 receipts through the shared Main A_LONG lock and original owner saves. Root's
real Chrome page was opened on002527 while pending1/3687 at13:50:05; its genuine
13:52:03 completion automatically changed the same selected stock to accepted
pullback D2 54/111 and D5 52/109, without a reload. Root's
`ROOT_LIVE_UI_ACCEPTANCE.json` binds the before/after receipts/screenshots.000554
now has full7887-date evaluation, original chart/materials and correct event
cases. Its smallK sample is one immature event, zero valid returns; this is
correctly shown as insufficient, not a0% or a substitute group's rate. An earlier
conditional placeholder screenshot was taken before its async reply; no extra
UI patch was installed for that false alarm.

This acceptance covers the current frozen R2 batch's real per-stock completion
→ publication → SSE → same-page refresh. It does not claim all247 complete or
future research-day scheduled cache integration into Main. Future-day incremental
cache consumption is the existing owner's separately documented hook; Main and
Stage were preserved.

Own-framework compatibility source lives exclusively under
`research/stock_panel_collab_20261030`. It consumes the pinned public framework
projection validator and the existing original renderer/API; all46 framework
files stay unchanged. See its README/COMPATIBILITY for explicit host context and
company-validator gaps. No sanitized framework was installed.
