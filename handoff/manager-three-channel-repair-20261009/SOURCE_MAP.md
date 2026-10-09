# 源码身份、增量范围与完整文件

## 四种身份必须分别核对

| 身份 | 固定值 | 意义 |
|---|---|---|
| 新问题包传输 commit | `b19eb112bd641ca97cac1246af7c81d8873641f4` | 本轮输入的不可变 GitHub 内容 |
| 输入 commit 的 tree | `71b42ce8b6bdcdcc8bfe993d90455b56528d049f` | 69 个问题包文件和源码 blob 归属依据 |
| 前序 R3 冻结候选 | `ca01c4d0260fecf7aae3c89e96899f36901bf8f7` | 任务要求接续的候选，不是现役进程身份 |
| 本地合成比较基线 | `7ca0190a721a7fd0fc0c88b79a872889867d111f` | 1,028 个固定树 blob 组成的隔离比较基线；不是远端可部署提交 |

新交付提交只在新的 handoff 目录保存候选源码与证据。其固定 SHA 由发布后的 GitHub 链接及 ZIP 顶层 `REMOTE_READBACK.json` 给出，避免文档自引用提交 SHA。

69 个输入文件共 **1,951,960 字节**，逐文件按固定树 Git blob SHA/大小验证，48 个 source_index 条目另按 SHA-256/字节数验证。原问题包 manifest 的 64 项和 checksum 的 65 项验证通过；GitHub 顶层另有 README 和 2 份 review 文件，合计 69，不混用这几个口径。

参见 [输入核对](reference/input_files_verified.json)、[原包契约核对](evidence/input_contract_verification.json)、[比较基线来源](reference/test_assembly_provenance.json)、[独立来源审计](independent_review/source_identity_receipt.json)。

## 三个补丁 profile

| Profile | 文件数 | 源码角色与限制 |
|---|---:|---|
| `api_r3_candidate` | 6 | 冻结 R3 API 候选与原公告 CLI / upstream 参考源码组成的完整 repo-relative source assembly；不是现役 API 或 worker 目录的已验声明 |
| `web_r3_candidate` | 1 | 冻结 R3 web API DTO validator；没有 layout 改动 |
| `test_delta` | 6 | 5 个新文件、1 个既有测试的契约调整；只在临时副本运行合成测试 |

`before/<profile>/<repo-relative-path>` 和 `after/<profile>/<repo-relative-path>` 是完整文件；新文件没有 before。不要去掉 `apps/api`、`apps/web`、`upstreams` 等路径前缀。patch 路径统一为 repo 根相对路径。

## 7 个运行文件 SHA-256

| 路径 | Before SHA-256 | After SHA-256 |
|---|---|---|
| `apps/api/v35_api/manager_research_router.py` | `9d8d132c58e7cf1c5a5609d93261483d578268ac24c60c2fa7a6a79b87344341` | `5c2bb2aa5716726295811eee7919dce1e36420ce027589b0e467351b79b7fd7a` |
| `ops/run_manager_daily_announcement.py` | `bfb853fb982e0b2da1024fa942ae9dc5d67fa88a8d112f46054608641129c1ee` | `aee0e5c31f30b296864a7ad81263fbc748b65cb9b4d443f83a756019cbc94a38` |
| `upstreams/v3_shared_data/shared_data/hk_security_master.py` | `ac2c16669236d24d6d03cac183238ca8dccd8fd23895ae14ad34cef40c049008` | `aa197bb1b7e01bd80d1f2e79681f5f17a80d4b4b82143906eae37b71b92f3a5b` |
| `v4/manager_research/plan_owner_dispatch.py` | `2b532168bfdce41080121df318cb619011b98bb76195eba39df43046a130b987` | `e4ff0cf9a9aa5af2277ff0c91773dfbb05b656121a65850bc2087b850f8e2bee` |
| `v4/manager_research/workspace_announcements.py` | `ea259666727b71c78760d666f3fe7f90350829bdce5f2b55745927528546af04` | `82187a190f2a308cc193473a9583f0c8edb82782ce45217a1dce8c866f172f0b` |
| `v4/manager_research/workspace_plan.py` | `c734f3e986af81b39bf11c09d93caf7a205526c8b4df940a4beeb011f74e0ebb` | `881599ba5a68badd7e18271c57666937f3e954088dfcfcb4c827dcf99419be7f` |
| `apps/web/src/api/managerWorkspace.ts` | `27689d66f46e47b2ed714adb3fa571a5fd024a26c5d3d97d238ae5931e2afcfb` | `35a879624032cfffb1c3e4afba3c4ae6298df7d5dffb5db90d9ad42142f496ee` |

## Before 来源在固定输入提交中的位置

以下每条均属于 `b19eb112bd641ca97cac1246af7c81d8873641f4`；role/side 取自原问题包 source_index。具体 before 字节、Git blob SHA、大小和 after 身份见机器清单。

| Repo-relative 路径 | 提供方 role / side | 固定提交内文件 |
|---|---|---|
| `apps/api/v35_api/manager_research_router.py` | `api` / `candidate_after` | `handoff/manager-three-channel-problems-20261009/package/source/candidate_after/api/apps/api/v35_api/manager_research_router.py` |
| `ops/run_manager_daily_announcement.py` | `announcement` / `reference` | `handoff/manager-three-channel-problems-20261009/package/source/reference/original_r3_business_source/ops/run_manager_daily_announcement.py` |
| `upstreams/v3_shared_data/shared_data/hk_security_master.py` | `api` / `reference` | `handoff/manager-three-channel-problems-20261009/package/source/reference/api/upstreams/v3_shared_data/shared_data/hk_security_master.py` |
| `v4/manager_research/plan_owner_dispatch.py` | `api` / `candidate_after` | `handoff/manager-three-channel-problems-20261009/package/source/candidate_after/api/v4/manager_research/plan_owner_dispatch.py` |
| `v4/manager_research/workspace_announcements.py` | `api` / `reference` | `handoff/manager-three-channel-problems-20261009/package/source/reference/api/v4/manager_research/workspace_announcements.py` |
| `v4/manager_research/workspace_plan.py` | `api` / `reference` | `handoff/manager-three-channel-problems-20261009/package/source/reference/api/v4/manager_research/workspace_plan.py` |
| `apps/web/src/api/managerWorkspace.ts` | `web` / `candidate_after` | `handoff/manager-three-channel-problems-20261009/package/source/candidate_after/web/apps/web/src/api/managerWorkspace.ts` |

## 测试文件

| Repo-relative 路径 | 变化 | After SHA-256 |
|---|---|---|
| `tests/test_manager_announcement_handoff_20261009.py` | added | `dd38c69af5230927d59f4c10ec375b41506999663a623da278a76c14a101dfe2` |
| `tests/test_manager_us_mapping_three_channel_20261009.py` | added | `9f7f1a3f73a539b470ba18a1ec029360c77734de21015895d73bc03cdcc1fd2a` |
| `tests/test_manager_three_channel_hk_reader.py` | added | `d037d4f43559e45d23f92b63a27317f2e5587b1b86649fbb9e6198a62618e7e5` |
| `tests/test_manager_screen_summary_contract.py` | modified | `0b67119b4b5637dce32e8c61cbfd4c066c35469569c8524cd912d5d75466dd09` |
| `tests/manager_three_channel_ui_fixture.py` | added | `1891b76ff2f0f07300831f46878ce416a83aa35441d28e91755eaaadb02ba894` |
| `apps/web/src/api/managerWorkspace.threeChannel.spec.ts` | added | `a3f3f5d01cea2d8b2fab55968117af76dc50d0ef87d8552b4aaca9ca1b2895d4` |

`test_manager_screen_summary_contract.py` 的 before SHA 为 `9f39c7eaa7fa730322f84e199c94440a838e44332dde35145d09e619b901e09b`。其他 5 个路径在基线应不存在，before 检查会验证其缺席，不会静默覆盖同名文件。

附带 16 份未变化的原测试辅助文件，逐个匹配固定树 blob。参见 [test_source_manifest.json](test_source_manifest.json)；这只是测试依赖闭包，不是完整应用依赖。原 US reviewed/registry 运行资料未提供，没有随包补造。

## 保留的源码身份

原 Issue32 的 `app.py`、`preselection_router.py`、`preselection_service.py` 以未改 reference 附带；API profile 验证时也验证这三份保留文件。原 US algorithm/bridge/service、调度配置、阈值、BUY、Stage、Vibe 及页面布局未列入 patch。通道报告和独立审查提供相应未修改文件审计。

现成 `verify_delivery.py` / `replay_delivery.py` 沿用前序 R3 经审查工具，工具内容未改。[工具身份](reference/reused_tool_identity.json)。为复用其固定 contract，`source_manifest.json` 保留 `v4.manager_r3.delivery.v1`，同时声明 `task_schema=v4.manager_three_channel.repair.v1`；这不是把新任务混标为旧修复。

当前 source_manifest SHA-256：`ccd38bc88ab8aa2231e844ef581470bea32545f7d48f988996dc9290f9689e9d`。包总 checksum 覆盖该清单、完整源码、补丁、文档和证据；清单本身不把自己纳入递归校验。
