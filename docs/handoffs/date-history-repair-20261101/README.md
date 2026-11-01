# Date link and manager-history repair

Current status: `DEPLOYED / API_VERIFIED / UI_VERIFIED` within the two requested
flows. The Writer-stage record below is retained; controller results follow it.

Writer status: tested, pending controller TCP/UI acceptance and independent review.
No service, production plist, authoritative data, external research-panel assets,
workbench binding, or Junda integration was changed.

The active baseline was `junda-single-20261101-310e64e55bd17d85`, manifest
`0e59a4e42fd36d5da42f18df2de0b8a9e6e62e8cc316635db68d14e7ca22902a`.
Git base was `3699f353a`. The live App.vue has accepted changes absent from that
Git base. The canonical App.vue diff therefore contains only the date-link line;
the runtime frontend artifact applies that same line to the entire live source.
Exact source/artifact SHAs and candidate allowlist are in `writer-artifacts.json`.

The unmodified live frontend source/lock/config was rebuilt first. All three
entry HTML files and all seven generated assets exactly matched the live dist.
The date-link patch then changes only index.html and the new main JS/CSS assets;
the manager-selection/daily-command entries and shared assets remain identical.
The new CSS hash reflects Vue's changed component scope id. Existing historical
assets should be retained when the controller adds the new assets.

History baseline: GET `/api/v4/manager-workbench/history?date=20261030` returned
200, 12 versions, 3970 bytes, in 25.9536 seconds. Response SHA:
`75b11f14a396695ba266243b1b3710939f3c17998121e198d885f09eb3ef0167`.
The twelve immutable snapshots total 1,362,543,434 bytes. `legacy_root` is absent;
legacy history contributed zero rows and was not the bottleneck.

The original cProfile reproduced 24.017 seconds: `read_plan` consumed 23.981,
Pydantic validation 20.043, and `ensure_consistent` 14.580 seconds, including
9.735 seconds dumping complete models. File reads consumed only 0.095 seconds.
Long profiles are retained outside Git under the task's temporary
`writer-evidence` directory. Source handoffs contain only response metrics and
SHAs; no full history response is included.

The repair removes repeated deep copies during the product-SHA check. After the
existing owned store decodes JSON, it supplies a private identity token to the
unchanged complete model validation. Canonical encoding walks JSON values once
and reuses the existing compatibility serializers. Ordinary Python inputs keep
the original model-dump normalization. Schema, lane/run/rule consistency, product
SHA, duplicate-stock and count validation remain in force. There is no memo,
metadata admission shortcut, cache producer or API change.

Measurements retained without relabeling failures:

| Measurement | Seconds | Scope |
| --- | ---: | --- |
| Original live HTTP | 25.954 | TCP GET, 12 versions |
| Original offline profile | 24.017 | Original complete store read |
| First direct-encoder profile | 12.626 | Below initial reduction threshold; Python-input semantics subsequently isolated |
| Native `model_validate_json` trial | 17.018 | Cold HTTP route; rejected as slower and reverted |
| Final owned parsed-JSON path | 15.315 | Cold process, real HTTP route through TestClient, no cache |

The final response is byte-identical, including all twelve product hashes. Its
40.99% reduction does **not** meet the initial >50% threshold or <3-second aim.
Full JSON parsing, validation and canonical encoding of 1.36 GB remain. The
controller explicitly authorized stopping further optimization and evaluating
this remaining cost. This handoff does not claim a final performance acceptance.

Verification:

```text
PYTHONDONTWRITEBYTECODE=1 <absolute-project-python> -B -m pytest -q -p no:cacheprovider --basetemp=<isolated-temp> tests/test_manager_snapshot_digest.py
npx vitest run src/App.research-panel-date.spec.ts
npm run build
```

Fifteen distinct contract/store tests passed. After reverting the slower parser,
the seven affected read_plan cases passed again; the other unchanged tests were
reused. Cases cover compatibility fields, products and existing rejection
semantics, malformed JSON/UTF-8, non-object roots, BOM, run-id mismatch and ordinary
Python key normalization. The runtime frontend DOM test covers 10/29 → 10/30 →
11/02 and confirms the link preserves the selected future date.

Read-only inspection confirmed that the existing external panel preserves a
requested unavailable date as `未物化 / CANNOT_CONFIRM` and displays read failure
without substituting the latest date. Real panel clicks and TCP comparison belong
to the controller's isolated candidate. Manager history and research-panel date
availability are separate: the missing 11/02 panel product does not imply empty
11/02 manager history.

The controller owns the sole formal candidate assembly, independent review,
deployment decision and Git synchronization. Writer did not commit or push.

## Controller acceptance and authorized deployment

The user explicitly accepted keeping complete per-snapshot validation and the
approximately 41% measured improvement. No catalog-only history, background
producer or memo was introduced. The independent Reviewer found a nonfinite-JSON
compatibility regression before deployment; the minimal fallback was repaired
and independently checked for NaN, Infinity and -Infinity. Finite inputs still
avoid the original complete model dump. Source commit:
`cd060be79433340879b79e3692ec26b45aee02cf`.

Formal release:
`~/Library/Application Support/com.lexi.v4.local/candidates/date-history-fix-20261101-r1`.
Manifest SHA: `2bcd7c67bc27f515824eb1a861d534f1937e863e44505d8244a54780b694e247`.
Preparation SHA: `59812fd35d96dae5c7de8fb5479a1b30a01d88f0d2954121d813d589944b050c`.
Its 1326 inventory entries hash to
`18d0472bb0b8a3a2f4df18018024fa1ab156dd162b262277b9688d3de51b5a65`.
Only the six recorded app paths changed; 1320 entries are unchanged, with no
deletions or bytecode caches. The earlier failed compatibility candidate's
metadata and source are retained under `evidence/before-nonfinite-r1/`.

The controller reused the unchanged reviewed lifecycle implementation through
`ops.activate_tech_debt_candidate.switch(explicit_target, receipt_sha)`; it did
not invoke that older task's hardcoded `prepare` or CLI target. The new task's
preparation receipt binds the current Junda predecessor, exact plist/PID CAS,
complete candidate inventory, lifecycle-tool SHAs and unchanged external bindings.
Independent review returned `PRE_CUTOVER_PASS` on these exact pins.

Cutover completed with `ACTIVATED_VERIFIED`, PID `1949`, active plist SHA
`fe750d7afb269ced835b14389b53ab1cb52c746cef0ebb71559fbe462cccc061`.
Health/ready are 200; execution identity and frontend
`main-Klhi0XX-.js` are verified. The sampler recorded approximately 12 seconds of
transient unavailability. No automatic rollback was triggered. This is not a
zero-downtime claim. The actual activation result SHA is
`174bf652fc570043bc2d90da0af675d9a84421878b3b03af0e6e41d5cca80b3c`.

| Actual check | Result |
| --- | --- |
| Isolated TCP cold history | 14.771s; 43.09% below the original 25.954s |
| Production cold history | 14.7143s; same 3970 response bytes and 12 records |
| Production history-tab click | 14.814s to 12 visible records; loading indicator gone |
| Date clicks | 10/29 and 10/30 retained; 11/02 explicitly unmaterialized/CANNOT_CONFIRM |
| Browser error logs | Empty in the production test tab |
| Protected history inputs | All 12 catalog and 12 snapshot raw SHAs unchanged |
| Junda panel dependencies | All 485 assets and host/WeChat/PYTHONPATH bindings unchanged |

An initial panel observation was taken before asynchronous host initialization
finished. The apparent 10/30 fallback was not a final failure: waiting for the
actual selected date confirmed 10/29 (with its explicit next-day observation
label) and the 11/02 missing-product placeholder. No external-panel source was
changed. The initial observation and correction remain in local evidence.

The controller closed its test tabs and the temporary 18874 process; current tab
inventory shows only the original user tab, with no held native input. The browser
API could not reload that user-owned tab (`browser.user` unavailable); its automatic
refresh is `CANNOT_CONFIRM`. Actual production tests completed in a separate test
tab. The user should refresh the original page once to load the new frontend.

The full-validation cost remains approximately 15 seconds for 1.36 GB; this is
an improvement, not instant loading. Natural scheduled execution and a real
production rollback were not exercised. Trading/production flags remain false.

### Reversible old-code quarantine

The user authorized inventorying both old source and old candidates, then moving
only proven unused items. The controller examined 678 V4 configuration/manifest/
plist metadata files. Two superseded, never-activated candidates had no external
configuration/reference or process occupancy; under the shared API release lock
they were atomically moved to
`~/Library/Application Support/com.lexi.v4.local/待删除/20261101-date-history-repair/`:

- `junda-single-20261101-1165ad2f-r1`
- `junda-single-20261101-ee6099fd1013eb7c`

Each contains 2056 inventory items. All file hashes, permissions and inodes match
before/after; nothing was deleted. Original path-bound manifests remain unchanged;
restore a whole directory to its original vacant path before attempting reuse.
`MIGRATION_RECEIPT.json` in that directory records original paths and inventories.
The current release, Junda static-root predecessor, rollback ancestors, referenced
releases and other tasks' worktrees were retained. Source
`v4/manager_workbench/legacy.py` remains imported by `api.py`; its name is not
proof of dead code. No standalone source file was proven safe to remove.

### Rollback and evidence

The exact original Junda plist is retained at the formal release's
`config/original-api.plist`; the Junda release remains intact. From this worktree,
use the absolute v4-mac interpreter and the explicit new target, not the old
task's CLI default:

```bash
PYTHONDONTWRITEBYTECODE=1 "/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v4-mac/bin/python" -B - <<'PY'
from pathlib import Path
from ops.activate_tech_debt_candidate import switch
print(switch(
    Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/date-history-fix-20261101-r1'),
    '59812fd35d96dae5c7de8fb5479a1b30a01d88f0d2954121d813d589944b050c',
    rollback=True,
    activation_sha='174bf652fc570043bc2d90da0af675d9a84421878b3b03af0e6e41d5cca80b3c',
))
PY
```

Private runtime evidence is under
`/private/tmp/v4-date-history-repair-20261101/`: preparation/activation, sandbox
lock-denial and corrected-environment records, TCP/API summaries, settled DOMs and
screenshots, health samples, protected-input hashes, browser handoff, quarantine
receipts and independent-review verdicts. Runtime packages, raw history payloads,
logs and backups are excluded from GitHub synchronization.

Final independent read-only review returned `REVIEWED/PASS` for deployment,
production API and the recorded test-tab UI flows, with no unresolved findings.
Its JSON was transcribed by the controller into local `reviewer-final.json` with
the origin identified. It retains the original-user-tab refresh limitation,
approximately 12-second interruption, natural-run `NOT_RUN` and unexercised real
rollback. Source, tests and compact handoff use branch
`codex/v4-date-history-repair-20261101` in `lexi2016/v4`.
