# 源码角色、累计增量与精确身份映射

基线固定为 `b98d85c95d19780e2900dce7de9372328e67acf6`，共享父基线 `66bb05a2e12976775ccb997191ce943bae8cc9a5`。所有完整 SHA/大小/来源以 [source_manifest.json](source_manifest.json) 为机器合同；下表展示相同身份。

R1/R2 是固定候选输入，不代表现役已接入。current profile 的 before 来自 R3 所附实际角色快照；`workspace_daily_channels.py` 例外，来自固定父提交中的 Mac completion 源，其本机当前前像须原 owner 重新核。R3 namespace 缺失要求 absent-before 门禁；HK child 的现存 namespace 则保留，不能套用 R1 的新增文件前提。

本轮相对已验 R1/R2 候选共有七件 API 运行源码增量：五件 binding/dispatch/cycle/router/renderer、daily-channel 来源指针，以及最终独立评审要求的 PREOPEN safe wrapper。最后一项保留真实异常类型并限制异常原因，未改变原时间/预算/筛选。

API 与 worker 分别使用自己的完整 app 源码副本，包内 after 只覆盖列明的必要路径。worker 五件累计源码已经包括最终 autorun 方法及异常修复。actual API consumer 在 `v3_shared_data/shared_data/hk_daily_supplement.py`，不是 HK02 updater 的 producer。

## api_current

| 源码路径 | before SHA-256 | after SHA-256 |
| --- | --- | --- |
| [apps/api/v35_api/manager_research_router.py](after/api_current/apps/api/v35_api/manager_research_router.py) | `84f65a351e1e44171820cb8698e4198b3084e39b8d0cfe82c6b4bc05595f8073` | `9d8d132c58e7cf1c5a5609d93261483d578268ac24c60c2fa7a6a79b87344341` |
| [infrastructure/_research_peripheral_store_parts/_namespace.py](after/api_current/infrastructure/_research_peripheral_store_parts/_namespace.py) | ABSENT：本机须核不存在 | `04d71a71d33cdc90ec362289095dd2ac6e357f79af1528f8c573f6ddcc24e68d` |
| [infrastructure/scheduling/manager_announcement_supervisor.py](after/api_current/infrastructure/scheduling/manager_announcement_supervisor.py) | `73eb6a2f7cbf2e2307a87edc3013e355c331f2ce87e6e0ae693b9f78de2dd34a` | `e9a1e6f79abf268855a88d15dc579744ec4739f3561eccc56972badd89653ffa` |
| [ops/render_manager_announcement_binding.py](after/api_current/ops/render_manager_announcement_binding.py) | `6d9f7a221df8ea8cdb0eb5e79a699f4a8f38459dbf1c4c1742b7550b8da0cc4a` | `44fba219e65a2c67bf0dc5d7d9f012e6ece757bb5a2b38a273f616dbfe7aa4db` |
| [ops/run_manager_announcement_cycle.py](after/api_current/ops/run_manager_announcement_cycle.py) | `c6f9cfa57515682b4f076e10f2030196dc9377bdbb9ec4abe737e36d15485c1c` | `01b93a8985bc43f8f08ae5c6d97637abc2273fb20987fb27c6a78c6fc5b59d44` |
| [v3_shared_data/shared_data/hk_daily_supplement.py](after/api_current/v3_shared_data/shared_data/hk_daily_supplement.py) | `5528a6b44bfb5b79265732b85beb1fb89860355b48a852da07264fb34231c79c` | `f71d6bb8bc0d55a0205d9734562c37d249654e3e39ccc85e18dd6398aa3c3862` |
| [v4/manager_research/plan_owner_dispatch.py](after/api_current/v4/manager_research/plan_owner_dispatch.py) | `8fad78ec64b1ff3ab80242fedc93dfcf7cbed25e6839821aab7f024ca297bf75` | `2b532168bfdce41080121df318cb619011b98bb76195eba39df43046a130b987` |
| [v4/manager_research/service.py](after/api_current/v4/manager_research/service.py) | `16edcea443ed19fa5a2808f9160b4255bcfe65c309eb48207815afdd834fdd37` | `d7798b66cd8d1691c7b9f081380ce702c7e840b5fb137f4d72aeef56e4bef8a4` |
| [v4/manager_research/us_mapping_research.py](after/api_current/v4/manager_research/us_mapping_research.py) | `297dc6f5950d3614437378c22e3157b6866823fbf25fd39cb47f112ffea40da7` | `f4a0919382d6daecaac67429a886980197fc2476f99de3ccda241fb1da8ba8b7` |
| [v4/manager_research/workspace.py](after/api_current/v4/manager_research/workspace.py) | `183e3ebd0322883a8f8cef37c0244f424f16c63d3120245e263bb9585133dea3` | `a6225ef5583a73c066a5c31400f84e237aaceb63abefcf199cfb8c9b8af7dcdc` |
| [v4/manager_research/workspace_daily_channels.py](after/api_current/v4/manager_research/workspace_daily_channels.py) | `de4e91150d3198dda40e170660de8a83c717811d478411941015b7cf1364c15f` | `e5a74449f211c9e8ecfb4f886317db2263d524f0e29fa7912c9094928a5c6bab` |
| [v4/manager_research/workspace_history.py](after/api_current/v4/manager_research/workspace_history.py) | `da5e1223326631cc9070c3059ca606bac3840ef468ad5c06f2f3a51534f82ec1` | `75a8ba0e550d092c7862b268f89b11862282a5c6d05810c32500e4e15c3026af` |
| [v4/manager_research/workspace_plan_autorun.py](after/api_current/v4/manager_research/workspace_plan_autorun.py) | `703bef8d9a04861c6cb4161880427126badd69eece234f9b53eaa5ae59d7c6ef` | `d7b2940f1203b62d642137a6b8eecffac566d0c1bf625d514c1345c0fc1a2a34` |

## api_r2_increment

| 源码路径 | before SHA-256 | after SHA-256 |
| --- | --- | --- |
| [apps/api/v35_api/manager_research_router.py](after/api_r2_increment/apps/api/v35_api/manager_research_router.py) | `c3ec90ffb88f1378c4d9a1912fc78747f4440d0331696de4f1a015ad72946f4c` | `9d8d132c58e7cf1c5a5609d93261483d578268ac24c60c2fa7a6a79b87344341` |
| [infrastructure/scheduling/manager_announcement_supervisor.py](after/api_r2_increment/infrastructure/scheduling/manager_announcement_supervisor.py) | `2ed9640b7c1568df065884f9f71a1df82b288c342bc94135ef4fd06b4c510373` | `e9a1e6f79abf268855a88d15dc579744ec4739f3561eccc56972badd89653ffa` |
| [ops/render_manager_announcement_binding.py](after/api_r2_increment/ops/render_manager_announcement_binding.py) | `78049be0625c15539dcd44c1924ba8f89d5dd5a06a074c723a84d68fb45b3f39` | `44fba219e65a2c67bf0dc5d7d9f012e6ece757bb5a2b38a273f616dbfe7aa4db` |
| [ops/run_manager_announcement_cycle.py](after/api_r2_increment/ops/run_manager_announcement_cycle.py) | `ac05519d31be2ad5de640190d9219335e14cd70e6273bdc652b32b85e929ffa1` | `01b93a8985bc43f8f08ae5c6d97637abc2273fb20987fb27c6a78c6fc5b59d44` |
| [v4/manager_research/plan_owner_dispatch.py](after/api_r2_increment/v4/manager_research/plan_owner_dispatch.py) | `d896359dbfd39f41ed3e316d54424c6f1172d935aa1d77a47463167d7bf1ed90` | `2b532168bfdce41080121df318cb619011b98bb76195eba39df43046a130b987` |
| [v4/manager_research/workspace_daily_channels.py](after/api_r2_increment/v4/manager_research/workspace_daily_channels.py) | `de4e91150d3198dda40e170660de8a83c717811d478411941015b7cf1364c15f` | `e5a74449f211c9e8ecfb4f886317db2263d524f0e29fa7912c9094928a5c6bab` |
| [v4/manager_research/workspace_plan_autorun.py](after/api_r2_increment/v4/manager_research/workspace_plan_autorun.py) | `14d168300bba42124649f56b79ae65b41359bcfa6928b59fea4a36beb2b511f5` | `d7b2940f1203b62d642137a6b8eecffac566d0c1bf625d514c1345c0fc1a2a34` |

## worker_current

| 源码路径 | before SHA-256 | after SHA-256 |
| --- | --- | --- |
| [infrastructure/scheduling/manager_announcement_supervisor.py](after/worker_current/infrastructure/scheduling/manager_announcement_supervisor.py) | `fd41e7ae1ba82429fb75364d42e96c435aa5855fb471c4fb55a0d38c962aa22a` | `e9a1e6f79abf268855a88d15dc579744ec4739f3561eccc56972badd89653ffa` |
| [ops/render_manager_announcement_binding.py](after/worker_current/ops/render_manager_announcement_binding.py) | `6d9f7a221df8ea8cdb0eb5e79a699f4a8f38459dbf1c4c1742b7550b8da0cc4a` | `44fba219e65a2c67bf0dc5d7d9f012e6ece757bb5a2b38a273f616dbfe7aa4db` |
| [ops/run_manager_announcement_cycle.py](after/worker_current/ops/run_manager_announcement_cycle.py) | `cd91604a7f7d7f2f960bbbd337fcd453bf97bb298c14f0a7fb8804fdcbaf0a84` | `01b93a8985bc43f8f08ae5c6d97637abc2273fb20987fb27c6a78c6fc5b59d44` |
| [v4/manager_research/plan_owner_dispatch.py](after/worker_current/v4/manager_research/plan_owner_dispatch.py) | `f4ddb61e341aa48f24aad62e9d0aa7bf2c9a0fc3d07bfae7ec285f78f1467fe3` | `2b532168bfdce41080121df318cb619011b98bb76195eba39df43046a130b987` |
| [v4/manager_research/workspace_plan_autorun.py](after/worker_current/v4/manager_research/workspace_plan_autorun.py) | `e785ae1d465175bec0517e7c3b4a8d6e16593967cba554aa0428817a85cd079b` | `d7b2940f1203b62d642137a6b8eecffac566d0c1bf625d514c1345c0fc1a2a34` |

## hk_child

| 源码路径 | before SHA-256 | after SHA-256 |
| --- | --- | --- |
| [ops/_macos_research_panel_daily_parts/hk_capture_gate.py](after/hk_child/ops/_macos_research_panel_daily_parts/hk_capture_gate.py) | `d3db5b9644bbf2fb1f4e245717907862ebe1cee2d0f650a8d45d732fd4a71940` | `d07be30a40c35aee9d710fcdcc7ae66b031488cc4c5e7029824e3c76ed3fd71c` |
| [ops/ensure_hk_security_master.py](after/hk_child/ops/ensure_hk_security_master.py) | `6c341a33c0283b023219c46cc2a1c6aaca49cf4b5dcb88aa2fb5527a13145601` | `495ced4f0f06f170606ee576e035dafc99b540cd9fad0a28f2f2a36e5989ddb9` |
| [ops/macos_research_panel_daily.py](after/hk_child/ops/macos_research_panel_daily.py) | `07aa9770c6ae0bb0cfd012e57843a37fedda6724a57cd52d7c339d854fc6609b` | `1963990fcde99b2681c837b8b66ea12f1ab066aba47729af5d0900073bc79ef3` |

## web_cumulative

| 源码路径 | before SHA-256 | after SHA-256 |
| --- | --- | --- |
| [apps/web/src/api/managerWorkspace.ts](after/web_cumulative/apps/web/src/api/managerWorkspace.ts) | `5854af5d1e2b33cc469ba6abd49096bb2f727280161c663edf4b757742f9ce92` | `27689d66f46e47b2ed714adb3fa571a5fd024a26c5d3d97d238ae5931e2afcfb` |
| [apps/web/src/manager-selection/catalystObservationPanel.ts](after/web_cumulative/apps/web/src/manager-selection/catalystObservationPanel.ts) | `fbb20e417bb4d9ff7cbd25c5aa29f387a1650438d6e638216b3f4d7c1a209497` | `ffd5c8cbfdaba9eb7e277695114647ef037b88ae16269be5547d3eff0649d3a3` |
| [apps/web/src/manager-selection/dailyResearchRun.ts](after/web_cumulative/apps/web/src/manager-selection/dailyResearchRun.ts) | ABSENT：本机须核不存在 | `5e12c62c954b1689fb8540621d7db650ebe88aa0ef763363ff42fef40a52107d` |
| [apps/web/src/manager-selection/researchAttention.ts](after/web_cumulative/apps/web/src/manager-selection/researchAttention.ts) | `16bb02dd12c22fd6c55f6c42bb57f8e48ac66864673ba403380381cb2b63f3ef` | `a7aeb4e0a84aaa340260e7a09d522b5e96cf579fcca18f6aa747154716a32a1c` |

## 保护文件

| 文件 | SHA-256 | profile |
| --- | --- | --- |
| `apps/api/v35_api/app.py` | `5d344dfe902db37f81e06d1d401e9a7e20ae910d8f7647b732ae2b3ba4f019e5` | api_current, api_r2_increment |
| `apps/api/v35_api/preselection_router.py` | `718d54a6c6aa8cde2871ce4dc41cbc1d825f199a57b605e4f5ec70d8c4fe19ae` | api_current, api_r2_increment |
| `apps/api/v35_api/preselection_service.py` | `cbed3aa4797889051eb7bebe4b8e3240b568d72b4dfb5c20f65e914d39e48044` | api_current, api_r2_increment |
| `ops/_macos_research_panel_daily_parts/_namespace.py` | `45da791482883c7c371268a99056960c577f299b43a5629394b3178fbea9f8b1` | hk_child |

共享 scheduler daemon/launcher 源码未改；完整比对见 `evidence/binding_identity.log`。不随本包更新 Stage、BUY、Vibe8910、原 US source scheduler 或公告任务。

## 发布政策候选与测试依赖

`release_policy_review/` 是原 shared owner 审查材料，独立于五个 runtime profile；新增仅五条 exact shared path 对 manager 的权限，须原 owner 在原锁/active-base流程审查采用。旧政策 receipt 不成为新政策 receipt。

`tests/app/` 是所需原测试与三件新测的导出，详见 `test_source_manifest.json`。`reference/test_dependencies/` 两件原 live-acquisition 源仅用于合成 owner roundtrip；不是任何 producer 的部署补丁。其他真实模块复用本机已核全量源码，不由 Chat 的不完整测试装配提供运行保证。

## 实际运行身份

本轮核验了源码字节和合成合同，实际进程加载身份为 NOT_RUN。R3 附带的 Mac 根、plist/env/binding 是问题包时点的观察，接手时必须在原 owner 锁内重读。源码 SHA、进程 running、HTTP 200、历史 canary 均不能代替原 dispatch 与真实计划读回。
