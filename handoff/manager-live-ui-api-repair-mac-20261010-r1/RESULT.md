# Mac 现场修复与验收 · 2026-10-10

代码修复已发布到本地 8873；20261009 实际选股验收未通过，当前没有已核候选。

## 已验证行为

- 原有三路结果接入真实页面，显示日期、状态、owner、运行编号、产物身份和具体缺件；未知数量保留未知。
- 原有 owner 从页面手动生成研究计划，随后页面读取更新和独立 API GET 均返回 CURRENT、consumed=true、MATCH、changed_components=[]。
- run_id：bf2a84ea17874cc397a2f337199b8c5a；产物 SHA：b214575cdcd0a5afbe0522a6be05f646871f74f4dbe4061172f3121250617e38。
- 修复收窄已验证 V3.5 binding 的全局 manifest 哈希耦合；原 payload、receipt、日期和语义输入身份仍生效。独立回归验证新纳入材料仍触发 stale。
- 每日有限 US-HK 已审映射与完整美股评估分开显示；原始审计默认折叠，输入未截断。
- 发布回读验证 12 个静态文件、19 日的 113 个历史日期/阶段组合未改变；新服务 PID 54741。

## 实际选股缺口

| 路径 | 实际结果 | 具体阻塞 |
| --- | --- | --- |
| 公告，publication 20261008 | CANNOT_CONFIRM | ANNOUNCEMENT_EXACT_DATE_PRODUCT_NOT_CONSUMED；页面公告解析尚未导入，不能挪用前一日成果 |
| 港股通，target 20261009 | CANNOT_CONFIRM | HK_UNIVERSE_V2_ARTIFACT_MISSING；TARGET_HK_CONNECT_MEMBERSHIP_UNVERIFIED |
| 超跌反弹 | PARTIAL，693 只全部待核，695 项缺口 | 成交量单位未证明、历史/成交量输入不完整；无已核入选 |
| 正式 Stage | DUE_RECEIPT_UNKNOWN | SELECTION_ARTIFACT_UNAVAILABLE_OR_INVALID；页面显示 0 不代表成功扫描后为空 |
| US-HK 已审映射 | 4 项关系，VALID_EMPTY，匹配 0 | 仅已审关系范围；完整美股关系评估仍未完成 |

## 验证边界

本次是手动事后研究，未验证自然时段。BUY 未更新、未发送订单。浏览器确实请求新 managerSelection-BLWLswkk.js，发布器验证了服务端静态字节；CDP 响应内容已被缓存清理，不能声明浏览器响应体 SHA 已复核。

独立代码验证：候选后端 21 项、canonical 身份 9 项、cutoff admission probe、前端 daily channels 2 项通过；runtime 对照 14/15，唯一失败在冻结基线同样失败。最终独立 live/canonical 验收见 evidence/reviewer/live_acceptance.json。

独立 Reviewer 最终复跑：22 Vitest 通过、Vite 构建通过。全量 vue-tsc 未通过，四项诊断在未修改的测试文件，未扩范围修复。canonical API 可发送和校验显式子日期，但既有 router 未增加其支持，故非默认子日期可能失败关闭；默认页面 URL 已现场验证。canonical 与冻结运行源不同，交付中分别保存，不能互称。

## 证据与同步范围

ACCEPTANCE_SUMMARY.json 记录源码根、基线、实际运行根、run/product、关键 SHA 和安全标志。deployment/execution_receipt.json 为发布结果；ui/after-dynamic.png 和 ui/after-dynamic.txt 为内置浏览器实际页面；ui/owner-readback.json 为独立 GET 原始响应，仅本地留存。

远端仅同步本批必要源码、测试、文件 SHA 清单、独立验收和本摘要；不上传原始行情、完整 API 响应、计划、服务配置或认证。新独立分支 codex/manager-live-ui-api-repair-mac-20261010-r1，未合并。最终远端读回见 GIT_SYNC_RECEIPT.json。
