# 经理选股工作台：原 US owner 源码补充与 Mac 接续

本包补齐原 US 映射 owner 的历史部署源码来源，供 Mac 主控辨认当前版本。**业务修复仍以 R1 固定提交 `66339d576431285cfaa7e62ca58de31e7548a931` 为准；本包不包含新的业务补丁或部署。三路每日自然运行验收仍未完成。**

- 原问题包：[`0fd5eb3 / README`](https://github.com/lexi2016/v4/blob/0fd5eb374cb155232ed003d5fc4d0d3594252491/handoff/manager-workbench-problem-pack-20261008/README.md)。
- 已独立审查的修复：[`66339d5 / README`](https://github.com/lexi2016/v4/blob/66339d576431285cfaa7e62ca58de31e7548a931/handoff/manager-workbench-repair-20261008/README.md)。
- 本包父提交：`66339d576431285cfaa7e62ca58de31e7548a931`；独立分支：`chat/manager-workbench-source-followup-20261008-r1`。
- 唯一新增目录：`handoff/manager-workbench-source-followup-20261008/`。原 R1 交付及其生产源码、测试、pins 不变。
- 本轮环境：Linux 隔离工作区。已核固定 GitHub 来源；没有 Mac 执行通道。云浏览器与用户 Mac 的 localhost 不等同。

## 1. 新增的可核结果

旧交接 [`840b9538`](https://github.com/lexi2016/v4/tree/840b9538c45c9ba8fd56f8e89048aff230df0f0f/handoff/us-mapping-daily-workbench-20261005) 的 canonical 与其登记的 R2 部署版不同。现已从原 `page_overlay.patch` 的完整新增文件，再应用原 `daily_overlay.patch` 的六个 hunk，精确还原旧交接登记的 R2 部署字节。本次未实地复核历史 Mac 服务。

| 对象 | SHA256 | 字节数 |
| --- | --- | ---: |
| 原 page 前像 | `5d06b07077f4adef851e9c0711e41b406da6e51ce75d989561a93c347a27e2c8` | 11,447 |
| R2 canonical | `f9b545202dc0a8865413f4a6bd7742ab6e69d5d9c756fee5ab3abd7070dff2e8` | 13,999 |
| 精确重构的历史 R2 runtime | `297dc6f5950d3614437378c22e3157b6866823fbf25fd39cb47f112ffea40da7` | 14,052 |

重构结果与同一固定提交的 `DAILY_DELIVERY.json.deployed_sha256` 完全一致。两份提取 patch section 均与远端原 blob 唯一且逐字节匹配。独立复核在临时目录重新应用单文件补丁，确认零 fuzz、零 offset，且没有导入或执行重构出的 US 模块。详见 [来源及缺口对照](SOURCE_GAP_MAP.md)、[独立复核](evidence/independent_review.md) 与 [重构回执](reference/reconstruction_receipt.json)。

此文件只对应历史 `manager-us-mapping-daily-20261006-r2`。已检查的 R3 交接材料没有给出该模块的逐文件 SHA，整体 manifest/inventory 的 SHA 也不能推出它。**文件身份为 `HISTORICAL_R2_REFERENCE_ONLY`，当前 R3 准入为 `NOT_ESTABLISHED`。**

`reference/` 保存精确前像、两个原补丁片段、历史部署文件和重构脚本。重构脚本只在临时目录处理这一份文件，结果写入同目录的参考文件与回执；它不安装、导入或执行业务模块。可在本包的工作副本中复核：

```sh
python reference/reconstruct_us_mapping_r2.py
```

## 2. 当前仍需本机补齐的证据

| 待核对象 | 目前证据边界 | Mac 接续要求 |
| --- | --- | --- |
| 实际 API / scheduler 身份 | 冻结配置和 Linux 候选已记录；当前服务进程加载身份未验证 | 取得真正服务进程、解释器、模块路径与 SHA，匹配实际 release inventory |
| 原 US owner | 历史 R2 实际字节已还原；R1 组装源码的 service/router 未提供直接入口，不能据此推断实际 R3 缺失 | 核对当前 module、service、router、relation registry、reviewed seed 的原始 SHA 和实际调用关系；不以旧 R2 代填 |
| 当前前端源码 | 问题包指定的 `businessStatus.ts` SHA `36228506…` 对应字节和完整前端入口仍未从所核交接补齐 | 保留当前文件，核对实际完整源码，按原构建流程验证 R1 三个 TS 文件的集成 |
| 原 06:30 公告任务 | 新发现的 `9dfa5034` 是 10 月 7 日旧文档，未补齐任务定义或 R1 后的运行回执 | 提供原 heartbeat → reader → 独立 reviewer → handoff → owner import 的任务定义和真实运行证据 |
| HK02 成交量量纲 | 本次 US 来源没有提供单位、倍率或跨来源一致性证明 | 由原 HK02 owner 提供；没有证明时保持 `NOT_PROVEN`，不根据数值猜测 |

原三路规则和安全边界继续有效：公告采用原判断及 owner 产品；港股通保持目标日资格、上一完整日 capture、D−1 Top100 的不同身份；超跌保持原 0.80 / 1.5 阈值、交易日和量纲合同。缺失数据保留未知并逐来源隔离。`RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false` 不变。

## 3. Luna Max 的接续顺序

沿 R1 的 [Mac 部署与验收说明](https://github.com/lexi2016/v4/blob/66339d576431285cfaa7e62ca58de31e7548a931/handoff/manager-workbench-repair-20261008/docs/DEPLOY_AND_ACCEPT.md) 执行；本包只补充来源辨识。

1. **形成真实前像。** 核对当前 API、scheduler、前端及上述原 US 文件集合。保留真实进程加载身份和逐文件 SHA；若与 R1 before pin 不一致，先提交差异供适配，不能放宽校验。
2. **在实际 release 的隔离副本集成 R1。** 使用本机原依赖和完整入口执行代码测试、完整构建、exact-root owner canary，形成可审阅的候选 inventory、binding 和回滚前像，再由 Mac 主控按现有切换流程部署。
3. **返回分层验收回执。** 分别给出代码、部署、公告同产品 API parity、首屏三路页面及自然时段结果。页面需与 API 对上股票、原理由、数据日期、生成时间和 run。自动化需有原公告 heartbeat 完整链及 scheduler → 原 plan owner → immutable product → 同 run attempt 的真实触发链；人工 canary 或手动导入保持自己的执行类型。

回执中保留原错误、未知状态和未到时段；不能改时间回填。可以用新的固定 GitHub 交接提交返回这些摘要与必要差异，继续由 Chat 适配和复核。

## 4. 验证层次

| 层次 | 本轮结论 |
| --- | --- |
| 历史源码来源和精确重构 | PASS，主控与独立复核均确认；见回执 |
| R1 业务代码测试 | 本轮未改代码、未重跑；复用 R1 已记录的 123 项 Python、29 项前端及 scoped TypeScript 结果和原有构建缺口 |
| 本机集成、部署、实时 API、实际页面 | NOT_RUN |
| 三路每日自然运行 | NOT_VERIFIED |

`package_manifest.json` 列出本包其余交付文件的路径、字节数、SHA256 和 Git blob SHA；不包含凭证、账号数据、原始行情或运行产物。
