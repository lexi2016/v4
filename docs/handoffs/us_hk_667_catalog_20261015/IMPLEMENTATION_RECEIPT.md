# US→HK catalog implementation receipt

本批完成的是 2026-10-14 名单快照对应的只读资料目录。来源包 SHA256 为 `dac3c820fcd6919fabdccc9c37ee9055b729b200fcde5e48f0dcf527de81bc6d`，667 行港股通名单 SHA256 为 `9b799c0b74ac5047f4e44a1b3dfd1dfa5ca9ce978fa3b8e7877913c423424c9c`。可复跑命令：`python3 docs/handoffs/us_hk_667_catalog_20261015/rebuild_catalog.py --replace`。重建通过 ZIP CRC、15 个成员清单及成员 SHA、A/B CSV/XLSX 对照、A/覆盖表/报告章节与名单顺序核对；输出 667 股票、1003 条关系、649 只存在关系行、667 个报告章节。18 只没有 B 表关系行的代码记录在 `source_audit.json`。

Catalog 文件为 `v4/manager_workbench/research_data/us_hk_667_catalog_20261015.json`（6,831,359 字节，SHA256 `3d7e1c3931a66a6844f4cb5c0d35030ed0e615e3e8246bc0b22caddc61dbb671`，内部完整性 SHA256 `fd362d817032f4f0a8f6f033c44df64435232382ea514dc31beee7b285deb0c5`）。所有原始关系行及原始字段保留；所有独立事实核验仍为 `PENDING`，预测仍为 `UNTESTED`、历史 PIT 仍为 `NOT_VALIDATED`；`RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。源文件自报分类计数只作为来源声明保存，不构成事实或预测验证；旧 997 条关系逐边比较仍为 `NOT_RUN`。

既有文件本批前字节备份及其 SHA 清单在 `preimage/` 和 `preimage_manifest.json`。以下五个现有文件有本批修改；旧 SHA 与当前 SHA 可用清单复核：

| 文件 | 本批前 SHA256 | 当前 SHA256 |
|---|---|---|
| `v4/manager_workbench/api.py` | `348e567f78c2b85eab7353ca752174a0d6a86e2d233b69cc54a82035a865fc30` | `5bb49c21de74eac44745d8b05f02c253fe1693b680843eee1a42bd3c71dd5f15` |
| `apps/web/src/manager-workbench/Workbench.vue` | `136ac87a9f119fcaf78ce01637650452928470c3388a31d2b2def4325bfa3691` | `f069c5d09657707ff80403204a818cffe632d8e79310e2eee79ffa5970cebc65` |
| `apps/web/src/manager-workbench/types.ts` | `e50b35e625cd8b3db2ca5513c2e3bf7ee8d7d85f60ee1e19c54c2bdea1542fec` | `f8aa0b58342bea63a1b8f80648db1b95106d29923d1f22d3cad7b51696bf86de` |
| `apps/web/src/manager-workbench/api.ts` | `d172b6c936b1dc7f77b0c0a93d158254798f50ab8b181310427434dbfe171a99` | `b7d35ca34d5499048b9150aeec7d92e73eb8637666e8f1c3893f73de8be0da93` |
| `apps/web/src/manager-workbench/useWorkbench.ts` | `9360b853f68623228202914b9e89684a63f4757095d3c01999e4808e62a304a9` | `fe423f4f756834daf7819ac01d9803dd40adef0efd5b2c38199599ced6892b2f` |

本批新增实现、测试和派生收据：

- `v4/manager_workbench/us_mapping_catalog.py` — SHA256 `174981af052ae77a56af972a79775f7819b0d8194639964718c19b55284c724d`
- `tests/manager_workbench/test_us_mapping_catalog.py` — SHA256 `b0016cf683ae61b2c1223c9878ddae16f7540eaae3f916461ad26485edbdc6de`
- `apps/web/src/manager-workbench/__tests__/us_mapping_catalog.spec.ts` — SHA256 `f422ddba9c8cd2dad19c36131282c4c9246566927d7e165bfeda2c3ffcdc98fa`
- `docs/handoffs/us_hk_667_catalog_20261015/rebuild_catalog.py` — SHA256 `8dcaf8260fa191a636c16baab74f3d90c96e9478ce11fe6981bb0af6ae9ce900`
- `docs/handoffs/us_hk_667_catalog_20261015/source_audit.json` — SHA256 `7f0af6267d9b511bf3e343e90d7000d698c0f16608f05df2fceebf79d056939f`
- `docs/handoffs/us_hk_667_catalog_20261015/preimage_manifest.json` and the five exact preimage copies referenced by that manifest.

验证记录：

- `python3 docs/handoffs/us_hk_667_catalog_20261015/rebuild_catalog.py --replace` — PASS；重建输出 SHA 与上述一致。
- `PYTHONPATH=. .venv/bin/pytest --basetemp=/tmp/us_hk_catalog_pytest_20261015 -q tests/manager_workbench/test_us_mapping_catalog.py` — PASS，5 passed；有一条 Starlette `httpx` deprecation warning。
- 在 `apps/web` 执行 `node_modules/.bin/vitest run src/manager-workbench/__tests__/us_mapping_catalog.spec.ts` — PASS，1 passed。
- 在 `apps/web` 执行 `node_modules/.bin/vue-tsc --noEmit --strict --skipLibCheck --target ES2022 --module ESNext --moduleResolution Bundler --types vitest/globals src/manager-workbench/Workbench.vue src/manager-workbench/useWorkbench.ts` — PASS。
- 在 `apps/web` 执行完整 `node_modules/.bin/vue-tsc --noEmit` — FAIL，报告 5 条现存 TypeScript 诊断：`src/api/managerWorkspace.attention.spec.ts` 两项 `mapping` 可能为 `undefined`；`src/manager-workbench/__tests__/us_factor.spec.ts` 缺 `./fixtures/sample`；`src/views/ManagerSelectionView.spec.ts` 两条未使用 `@ts-expect-error`。本批目标文件没有出现在这些诊断中。

当前证据限于重建器、FastAPI TestClient 和 Vue 组件测试；没有启动 8873 服务，因此运行中的 API、页面及自然时段结果为 `CANNOT_CONFIRM`。没有提交或推送。独立 Reviewer 尚未给出结论；本 receipt 是交接，不是最终验收。`controller_ledger.json` 与 `PRIMARY_SOURCE_SPOTCHECK.md` 是主控既有文件，本批未修改。独立事实核验、预测验证、历史 PIT 验证和自然页面验收均未由本批完成。
