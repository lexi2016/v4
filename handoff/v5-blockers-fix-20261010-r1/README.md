# V5 blockers 修复候选交付 · 2026-10-10 R1

本目录交付三个固定源根上的最小源码增量、完整修改后文件、回归测试及可复核证据。**工程修复已实现并验证；原 reviewer 补充返回、Mac 私有资产和实际运行通道验收仍待完成。**

原任务：[START_HERE.md](https://github.com/lexi2016/v4/blob/46081f5bcfb5f0c9e63aaa8b2b7baf65ae191eff/handoff/v5-blockers-20261010/START_HERE.md)。只在新的独立工作分支增加本目录，原冻结源、main 和并行分支不被覆盖；未合并、部署或启停服务。

## 已交付的修复

| 问题 | 现在的行为 | 增量 |
|---|---|---|
| 10/9 目标在 10/10 保存后，auto 错入历史读口 | 使用原 owner 的独立 `current_recovery` 存储；当前恢复身份明确为 `CURRENT_RECOVERY`，auto 读回同 run/SHA；显式历史继续原资格门禁。缺 exact journal 时 `OWNER_ATTEMPT_UNVERIFIED`、不消费 | [经理补丁](manager/changes.patch) |
| 有效 frozen loader 被 marshal 引用状态误拒绝 | 比较全部 18 项 code 属性并递归比较常量、嵌套 code；引用持有/释放不影响结果，函数/helper/globals/native 布局变化仍拒绝 | [超跌补丁](rebound/changes.patch) |
| 原 reviewer 缺 `decision_revision` | 原 create 的写入前门禁保持不变；新增只读请求/返回校验工具，严格保持原字段类型与精确数值；真实原独审返回缺失时仍 BLOCKED | [修订补丁](revision/changes.patch) · [已准备的补充请求](original-reviewer/reviewer-binding-request.json) |
| Reader/独审缺少可调用交接合同 | 提供既有 host channel 的显式 submit/poll、request/source/身份绑定、heartbeat/失败/未知回执；实际 claim 前读回输入，等待不耗业务 attempt；缺通道明确 BLOCKED | [接口合同](INTERFACE_CONTRACT.md) |

三个补丁分别应用于 `3d9541ac`、`ebe5944e`、`e06d`，不能把一个根的修改后文件整树覆盖到另一个根。[完整前后 SHA](CHANGE_MANIFEST.json) 包含每个路径、原 commit、字节数和 SHA；每个组件另有 `BEFORE_SHA256SUMS`、`AFTER_SHA256SUMS`、`before/`、`after/`。

## 验证结论

- 经理/接口最终回归 **82/82 PASS**。
- 超跌新增身份回归 **18/18 PASS**；原四模块 **77 PASS + 4 SKIP**，总共 81 项。
- e06d 原 98 项加新增 28 项，最终 **126/126 PASS**。
- 两名独立审查者发现的 **5 项 Important** 均已补 RED 回归并修复；[原始发现与闭环](REVIEW_RESOLUTION.md) 分开记录。
- 三份补丁均在新的冻结基线副本实测 `git apply --check` 与 `git apply`，结果逐文件等于已测候选。
- 完整项目 discovery **仍有基线失败与未具备的私有输入**；详见 [VALIDATION.md](VALIDATION.md)，没有声称全项目通过。

## Mac 接续

按 [MAC_ACCEPTANCE.md](MAC_ACCEPTANCE.md) 在独立候选目录应用增量、核对 SHA、使用原锁定 3.14.6 环境运行测试，再进行真实原 owner、API/Chrome 和私有资产验收。该文档包含回滚方法。

已准备的新 revision_id：`decision-r20261010-rebind-638bfee44529438d`。它尚未用于真实 create，Mac 仍需确认该 ID 在真实恢复目录中不存在。补充请求 SHA256：`98464a39323fd332e29dbed82344b9e9c5eefed75fede37ec7dca8c93991845c`；请求未发送，**新的真实 reviewer 文件及 SHA 尚未取得**。使用原 392 条语义与 decisions 的固定字节，只要求原独审补充绑定，不在本轮重做语义审核。

超跌未更改 scale=1、价格/量单位、admission 或 694 批量限制；数值观察不构成正式准入。旧经理计划、历史 PIT、V4、BUY/Stage、原 panel/pointer 均不在修改范围。

## 独立 US 状态

上游最新附录记录 `7a3d3bc1e7a51899a60b455fcc6502c9e66eab60` 已在 Mac 以 3.14.6 完成 **11/11**，未部署；本轮未重做或混入该修复。所需 20261008 native master 仍缺，不能用 10/9 或 Connect 替代；已索引四键下跌、33 配置中 8 个上涨项不在四键映射，覆盖为 PARTIAL，不能称全市场零机会。[附录原文](evidence/UPSTREAM_US_STATUS_APPENDIX.md)。

## 来源说明

原 ZIP 的二进制传输未成功。本轮按固定原 commit 取得并验证 **1,177 个源路径、403 个唯一 Git blob**；1,173 个路径与 ZIP SHA 索引一致，所有 Python 字节一致。4 个差异仅为原版与脱敏版元数据/文档，未修改对应运行时门禁；没有声称核验整 ZIP 或读取缺失的原 Mac 私有 trace。[逐路径来源说明](SOURCE_READBACK.md)。
