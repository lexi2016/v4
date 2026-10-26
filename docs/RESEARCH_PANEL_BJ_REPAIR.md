# BJ history marker repair

Current status: **INTEGRATED / API_VERIFIED / UI_VERIFIED** for the exact two-case history-consumer repair. Active API release is `local-panel-bj-history-20261025-r1`; source SHA `f008721e1a134ceca712d3215af9cf8cc3238ba75f4b45fb1295a2d092596520`, installed manifest `d242476d87e5128fc371b033027261f139504e069aff2befe9797b337316caa1`, plist `69d6c5276227a6e8e729ceeb6619e353967277f13100061f5704f12555a2df1a`.

Root delivered two actual API responses and the existing 8873 page. Independent API and UI review passed: 920047 has five rows and 920002 one row in the fixed 20261019–23 window; six rows × 16 columns = 96 displayed cells match the saved API baselines. Four page screenshots cover the table horizontally. Expanded details were not visually tested. Other 1308 package entries, scheduler and research data were preserved.

This consumer repair is complete. 920002's four tail dates, active integration of the eight recovered factor sources, natural daily readiness and historical PIT remain unfinished. No full-site or full-market completion claim follows from these two cases. The preparation history below is retained for provenance.

Baseline is the actual bacabd r4 history consumer. Only the returned-row market predicate changes: exact requested .BJ requires BJ; .SH/.SZ require A_SHARE. All original code/date/nonnull original-signal/formula/source/legacy gates remain. No source rows are relabeled.

Frozen stage1 evidence has920047 five rows through10/23 and920002 one10/19 row, both BJ with all23 original signals nonnull and bound TDX_OFFICIAL_TERMS_BOUND_CONVERSION. 920002 native ends9/4 and original dated sync quarantined a malformed7/22 amount/volume signature before network. This source-tail problem is separate and unresolved here; no false five-row completeness or data repair claim.

Only focused synthetic marker/leak/nonnull/source/formula/date cases are new. Old source/API/UI/Futu/fullpanel PASS is reused. Installed packages/native/default data/services remain unchanged until independent scoped acceptance and Root integration. R1 metadata scope exposure is retained, not rerun or promoted.

Independent acceptance: `REVIEWED/PASS_BJ_EXACT_MARKET_PREDICATE_SOURCE_AND12_FOCUSED_TESTS`; 12 tests passed once in 0.32s. The accepted change is exactly one predicate. Source SHA-256: `f008721e1a134ceca712d3215af9cf8cc3238ba75f4b45fb1295a2d092596520`; active R4 preimage: `bacabd0341334eed55e745c2992eae3192015df649d63a1daf797eb47230c68d`. The six frozen real rows passed offline predicate compatibility; this does not claim live API or rendered-page acceptance.

Local implementation base is `71d76f716f5ca8ab30c5b1b9ee7cbb4bbb428655` plus the imported active R4 consumer. The remote source branch has a different base; this is not a shared-commit claim. Candidate integration is a single-file delta from the active R4 package, preserving its other files. It remains inactive until candidate and temporary-page acceptance. Native recovery, missing factor/source evidence, historical PIT and natural daily readiness are separate unfinished scopes.


## 920002 TDX seed 后续（已验收隔离产物，尚未正式接入）

- 新 progress.py 的显式 TDX descriptor 分支以原 wire 的四个 float32 经济条款字段恢复精度，沿原算术顺序与已采纳四事件精确一致。保持 NOT_FUTU_EQUIVALENT、原 Futu 分支、1.5 连续性阈值与未解释跳变拒绝行为。
- 首次 16 个针对用例中 15 通过，1 项揭示 raw/decoder 角色别名问题；保留失败，补精确角色交叉绑定后仅复核该项和直接影响正例，两项通过。原 578 行 seed 首次修复后检查也通过。
- 原实时响应含目标日后的 2026-10-26，原门禁正确拒绝。保留完整 20 行；经授权仅在隔离快照中按目标 2026-10-23 取 19 行，未来一行完整隔离，字段与顺序均不改。原 collector 离线来源回放后 578→582，唯一新增 10-20 至 10-23 四行，独立实际产物验收通过。
- 此阶段依赖已安装 R4 其余 13 个原组件；只新增 progress.py 与对应针对测试，不构成可单独替代整个组件包的发布。canonical native、正式组件/overlay/shim CAS、面板尾部交付与自然日更仍需后续独立接入证据。
