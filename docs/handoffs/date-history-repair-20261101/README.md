# Date link and manager-history repair

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
`history-cprofile.txt` retains the original profile.

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
| First direct-encoder profile | 12.626 | Complete reads; Python-input semantics subsequently isolated |
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
