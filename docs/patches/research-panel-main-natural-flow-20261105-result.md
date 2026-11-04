# Research workbench main-flow repair — 2026-11-05

## Scope and implementation

The existing workbench main column used a fixed viewport height and internal scrolling, clipping the original chart iframe and leaving a large blank area. The frozen change appends `.layout>main{height:auto;min-height:0;overflow:visible}` to `workbench-host/dot/shell/workbench.css`. It changes no iframe/canvas dimensions, chart source, data, filters, formulas, ranking, or BUY behavior. The repo baseline has no tracked external `research-panel` source; the exact SHA-bound patch is recorded in `research-panel-main-natural-flow-20261105.json`.

## Static candidate and review

- Source CSS SHA-256: `6835ec096dac51e414c24e86fe400bf3aecc690acd718040a89d77fa94225b6e`.
- Candidate CSS SHA-256: `d033d27a23d72983fb6249b39c0a9ae2fee54966fb8a833840fabc592668434f`.
- Candidate asset manifest SHA-256: `53e0473cc486492501ea3ffcc99975b7018699b82340d1fffd5c559b270776ba`.
- Candidate inventory: 491 files; 488 allowlisted entries hash-verified; only the CSS differs from source. The three non-allowlisted extras were preserved byte-for-byte. The temporary Vite `.vite` cache was removed and the preview cache path moved outside the candidate.
- Independent reviewer: `/root/top200_reviewer`, **REVIEWED/PASS**, no P0/P1/P2 findings. The reviewer confirmed CSS cascade coverage, the single-file asset delta, manifest hashes, and the two-path plist change.

## Behavior and activation evidence

- Controller CUA preview status: `PREVIEW_UI_VERIFIED` at 1920x880, 1536x704, and 638x871 using the same `002741.SZ` original chart. The 460px iframe, volume, and lower statistics are reachable by page scroll; the candidate count remains 238. See `PREVIEW_QA.json` in the task output folder.
- Controller activation status: `DEPLOYED_API_UI_VERIFIED`. The loaded API release/app root/app manifest remain `v4-ui-date-top200-20261104-r3-api` / `v4-ui-date-top200-20261104-r3-api/app` / `c303fc23cd93a2c7077fc7f1d5595f951a24f54aa46a4dc16fcdb76d4298b3e1`. Only the two research-panel environment paths point to the new static candidate. Active plist SHA-256 is `e7316f85031befe6c7c1cf92d698aa80742b5d4d65ab23660300bf225db83952`; served CSS SHA matches the candidate. Live UI evidence at 1920x880 again shows the same chart, volume, statistics, and 238 candidates. See `ACTIVATION.json` and `LIVE_1920.jpg` in the task output folder.
- Safety flags remain `RESEARCH_ONLY=true`, `production_allowed=false`, `buy_gate_updated=false`, `orders_sent=false`.

## Boundaries

The 8908 Vite preview was stopped and has no listener; its task-owned cache is outside the candidate and cleaned. Natural jobs were not run. All stocks and native Chrome zoom levels were not individually tested. No full repository suite is claimed. This result verifies the frozen CSS layout repair and the controller-recorded activation/UI scope only.
