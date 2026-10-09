# Manager owner 输入接入：最小返修候选 R1

本包完成固定 R2 上的两处计划身份修复，并补齐原 owner 到实际 `create_app` 消费链的确定性测试。**新增 20 项回归全部通过；所执行的全部 295 项仍为 268 PASS / 27 FAIL。本包不是全系统通过或可直接上线的证明。**

## 固定身份

- 私有仓库：`lexi2016/v4`。
- 新独立交接分支：`chat/manager-owner-input-integration-20261009-r1`。
- 父基线 commit：`a7f5d09fb19de10564925757207977aadc080cc1`，保留上一轮前端 validator 恢复。
- 输入 ZIP SHA-256：`67098b73089120e7f1758835ce48ce48258ff427a84faca6a19d2415f0306726`；两份上传逐字节相同。
- 固定 R2 release-manifest SHA-256：`f6385dd23e9fda4d2169f20d6dc68b6e1e519b2b1a35e1ceb0bfd3111a079ad5`。
- 生产前像：请求包的 `code/r2_chat_patch_target`。完整原始来源身份见 `request/SOURCE_SNAPSHOT_MANIFEST.json`。

## 实际修改

| 源码 | 修复 | 验证 |
|---|---|---|
| `v4/manager_research/connect_selection.py` | membership 卡片身份排除本次读取时钟 `read_at`，保留持久化来源时间 `available_at` | 相同工件只换读取时钟仍 CURRENT；同读取时钟而真实来源时间变化则 STALE |
| `v4/manager_research/workspace.py` | 定时复用增加完整 `date_bindings` 相等条件 | 错选股日期不再复用旧产品；相同日期、输入与 cutoff 仍复用同 run |

生产补丁只有 **2 文件、4 行增加 / 3 行删除**，其中两行是注释调整。`runtime.patch` 可正向应用与反向回放；`before/`、`after/` 提供完整字节，`MANIFEST.json` 提供 SHA-256。

## 四项业务验收仍要分开

公告 10/08 → 10/09 缺真实 capture/独立 Reader/Reviewer/import；HK Connect 缺目标日 V2 authority 的实际根绑定；超跌缺精确日 master/panel 与可被正式 reader 接受的成交量证明；计划必须用同一实际应用注入的 owner 在输入固定后刷新，再 GET 校验。合成测试证明链路可消费，不能代替这些真实输入。

特别是超跌：当前 native volume 合同仍为 `NOT_PROVEN`。补 master/panel 后可能只到 `READY_WITH_GAPS / PARTIAL`；不能承诺直接出现严格候选，也不能用任意 manifest 字段伪造全六日单位/scale 证明。

## 阅读与执行入口

- `RESULTS_AND_BOUNDARIES.md`：结论、两处根因、四项 owner/consumer/acceptance、完整测试状态。
- `MAC_APPLY_AND_ACCEPTANCE.md`：源 SHA 核对、隔离候选应用、原 owner 接续、只读回读与回滚说明。
- `TESTS_AND_ENVIRONMENT.md`：准确命令、31 项锁定依赖、Python 3.12 / 3.14 差异、测试支撑身份。
- `review/baseline_triage/TRIAGE_REPORT.md`：原失败逐项归因，保留真实 journal 顺序差异。
- `review/final_code/FINAL_CODE_REVIEW.md`：独立源码审查与额外边界测试；跨 cutoff 的新 run 行为单独保留。
- `tools/verify_delivery.py`：只读核验目标源码，并仅在临时目录中验证 patch 正反向字节。

本轮没有 merge、部署、切换或启停服务，没有改业务数据、Stage、BUY、Vibe 8910 或仓库公开性。Mac 实际 API/UI、完整部署闭包和自然时段验收均为 **NOT_RUN / CANNOT_CONFIRM**。真实配置、来源 SHA、时间与失败状态由原 owner 留存，不能以本包的离线根替代现役身份。
