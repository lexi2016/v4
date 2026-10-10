# 用最小现场证据继续完成真实选股修复

本轮已经完成代码、固定来源核对与合成业务回归。要继续判断现场断点，需要读取 Mac 上已有的原 owner 证据；当前会话无法访问 `/Users/lexi/...`，问题包也明确没有包含完整真实 catalog、reviewer、decisions、panel、Stage artifact 或保存的 16 MB body。

优先复用现有文件和配置。下面要求的是精确元数据，不需要重新制作大问题包或上传原始行情/全文。

## 第一组：现役身份与同日期公告

记录实际启动配置中的 app root、Python、release/source identity、Manager state root、API base。只导出相关路径与源码 SHA，不导出整个环境或认证信息。

使用同一原 API 读取 `date=20261009&publication_date=20261008` 的公告 analysis，保留下列字段及原响应 SHA：

| 类别 | 字段 |
|---|---|
| 请求/产品 | target_trade_date、publication_date、status、product_sha256、source_manifest_sha256 |
| 来源 | catalog run、catalog product SHA、readback_status、正文 terminal counts/gaps |
| 原审核与注册 | evidence_run_id、handoff SHA、reader/reviewer output SHA、judgment receipt SHA、decision_status |
| 原 owner | receipt SHA、available_at、parent/run 绑定 |
| 消费 | consumption_validation、workspace 中该日期的 product_checks、research_cutoff |
| 结果核对 | selected/watch/not_selected/not_assessed 的原决策数、去重证券数及逐条原因的本地文件 SHA |

原文件位置由当前 service 的 `store.root` 决定。源码中 analysis 路径位于 `workspace_announcements/20261009/eastmoney_date_catalog/20261008/`，registered handoff 位于 `announcement_agent_runs/<原 evidence_run_id>/evidence/`。文件名与 run 以原函数和已有目录记录为准；不要猜一个新的 run id。

若只读 `readback` 拒绝，保存明确错误码；再区分没有产品、没有 review、没有 handoff、没有 owner receipt、身份不匹配、未在 cutoff 前可用。旧日期 `20261008 / 2026-10-07` 的成功不解决这些当前缺口。

## 第二组：港股通的两个 authority 根与既存 D-1 绑定

按 `HK_CONNECT_LOCAL_REUSE_RECIPE.md` 从包内已指明的本机保存 body 导出原 `plan_context`。该 body 必须核对 16,410,447 bytes 与 SHA `6c0fe13667f5872a10cb83608bd29c1f4a7acdfa3c12e10af75cae2d7e40bdbc`；它不同于未持久化的独立 GET 响应。

从实际服务和原 HK job 配置取得：

- `V4_MANAGER_UNIVERSE_ROOT`、`V4_MANAGER_UNIVERSE_OWNER_ROOT`、`V4_MANAGER_UNIVERSE_OWNER_SHA256`。
- 原 HK job 实际 `--hk-asset-root`。
- 若配置了 D-1 fallback，则原 `V4_MANAGER_HK_CAPTURE_RECEIPT_ROOT`、`V4_MANAGER_HK_DISPATCH_RECEIPT_ROOT`；未配置也如实保留。

运行包内 `tools/inspect_connect_metadata.py`，它复用原 reader，比较当前绑定 authority root 与由原 job 参数推导的一个 producer root；目标失败时保留原 D-1 只读分支和相关来源检查。输出只包含受限元数据，不产生 authority 或选股。

有判别力的结果是：当前 root 缺失、原 producer root 对同一目标/owner/cutoff 返回 `OWNER_VERIFIED`。出现这种证据后才有依据修正错误的服务 root 绑定。两边都缺失或 publication/PIT 失败时，继续找原 producer 执行回执；不要现在补写历史 availability。

## 第三组：超跌原 panel 与单位证据

记录实际 `_workspace_screen_authority_root` / `_workspace_security_master_root` 的绑定来源，以及原 HK02 updater 的 source SHA。不要假设包中一个历史绝对路径仍是当前进程绑定。

从原 reader 输出导出 panel target/market_session、manifest/panel SHA、parent/recovery 身份、原 security master SHA、每项 session coverage 的计数与原因、`native_observation` 的 owner/source/单位/尺度字段。完整逐行数据留在本机。

已检查的旧 owner 导出仅证明 `NEW_INCREMENT_ONLY`，volume unit 保留 `NOT_PROVEN`，没有覆盖继承历史的可比较尺度。**如果原 owner 没有六个比较日的真实 unit/scale 证据，这一项是输入合同缺口，重复运行现有 exporter 不会自动补齐。** 应先取得原 provider/owner 的可验证证据，再在同一 owner 和 reader 上接入；不能由 scale=1、lot size、数值相近或单位“会相消”替代证明。

## 第四组：正式 Stage 原不可变证据

从现役 `observation_reader` 绑定追到原 `SelectionStore` root，读取 `selection_latest.json` 的 `20261009/STAGE_0935_0940/HK_CONNECT` 条目，以及该 entry 指向的 artifact、manifest、receipt。保留每个原文件的 SHA、run、market、date、算法身份及原 `read_verified` 的结果/错误。

分别核验原输入：A 股完整同日 `a_all_pool_rows`；HK 精确前一交易日 canonical D-1 Top100，包含完整 pool identity 和来源 SHA。不要用 Manager 的 HK 显示上限、全市场 universe、generic list 或别日名单替代 Stage 固定池。

`SELECTION_ARTIFACT_UNAVAILABLE_OR_INVALID` 同时涵盖缺文件和校验失败。原 reader 的元数据才能区分两者；页面的空列表和 Manager 的 formal count 不能作结论。

## 返回什么即可继续

优先返回：上述现役身份摘要、当前公告消费校验的元数据、HK helper 输出、超跌原单位/尺度证明状态、Stage 精确 entry 与原 reader 结果。每组均保留来源文件 SHA 和原时间；失败也有定位价值。

完整真实数据留在原 owner 上。后续修复依这些结果收敛到已有入口和具体绑定；最终仍以真实决策/产物、原 API 与实际重载页面一致为验收，不用状态标签或测试替代业务输出。
