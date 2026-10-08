# Issue #31：Mac 实际验收与回滚交接

本文件是待执行的验收协议，不是 Mac 通过回执。当前候选在 Linux 的隔离环境中验证；实际 Mac runner、外部 intake collector、Vision、冻结包与 Drive 完整链路均须另行提供实际执行证据。文章 10.8 已恢复这一事实不能替代本协议，也不能据此关闭 issue。

## 1. 先绑定当前运行树

由 Mac 上同一位 Luna Max Writer 读取当前公众号根及其继承的 `AGENTS.md`，记录实际文件路径和 SHA-256：

- `scripts/wechat_pipeline_runner.py`。
- `scripts/wechat_article_fetch.py`。
- `scripts/wechat_common.py`、`scripts/wechat_chat_handoff.py`（候选复用的正文解析和 OCR 工件校验）。
- `scripts/wechat_macos_ocr.py`、`scripts/wechat_prepare_ocr.py`。
- `scripts/wechat_yesterday_performance.py`。
- adapter 实际解析到的外部 `wechat_article_intake.py`。

同时记录 macOS 版本、架构、Python 路径和版本。将本交付的 `SOURCE_MANIFEST.json` 中 before SHA 与实际待修改文件逐一比较。采集 adapter 的基线来自固定原审查快照；附录生成器来自已验收 R1 增量。它们不能与更早的附录版本互换。

SHA 不一致时，应先检查现有差异，再由唯一 Writer 将补丁移植到隔离候选，交给同一独立 Reviewer 复核。不要用快照的整棵 `source/` 覆盖 Mac 运行树。原审查快照的部分公共路径与文档经过导出脱敏；这不是实际机器配置。

当前远程固定快照没有包含上述 runner 和外部 collector 的当前源码。2026-09-24 历史 runner 仅用于理解已有入口，不纳入补丁，也不证明当前入口行为。

## 2. 在隔离候选中复核默认入口

保留现有运行树及 R1。先使用实际 runner 的当前 CLI 和配置，在隔离候选输出根执行测试；最终命令、工作目录、解释器、运行文件 SHA、子进程实际 argv 和退出码必须进入回执。

需要证明的是默认日常入口实际经过现有 runner，并最终调用 adapter。Mac 分支应在真实调用的 argv 中出现 `--skip-ocr`，随后进入现有 prepare/Vision。只调用 `build_fetch_command` 辅助函数，或者临时添加一个没有接入日常流程的入口，均不足以通过这一项。

不得以安装 EasyOCR 作为默认处理，也不得另建第二采集 producer。对当前 runner/collector 的路径格式、checkpoint 名称与结构、退出码和 source-only continuation 状态做实际兼容检查。若不兼容，只能对已识别的真实调用点提出限定修订，并重新提供 actual diff 与独立复核。

## 3. 采集失败与中断验收

先使用离线 fixture，不反复请求微信制造故障。至少保留以下证据：

| 场景 | 必须观察到的结果 |
| --- | --- |
| 有效 BODY、50 张有效图片已保存，随后 OCR 依赖失败 | 独立 attempt 留存原始输出；正式来源保有身份、BODY、有序 manifest、原图及 checkpoint；状态只指向缺失的 OCR 阶段。 |
| 相同 run 再次调用 fetch，下一次预设响应为验证页、空正文或 HTTP 失败 | 已验证来源使 fetch 复用缓存，不进行第二次 BODY/原图请求；不能覆写成功来源或 OCR。没有成功来源的失败请求只留 attempt 证据。 |
| 真实 prepare/Vision 后再次调用 fetch | 正文、图片、合法 manifest 来源字段及 OCR 结果保持其已记录字节/SHA；prepare 添加的 OCR 字段不能被当成整篇来源失效。 |
| promotion 中断 | 重启后从同一已验证 attempt 完成缺失写入；不能再次抓取正文或混合不同 attempt。对具体中断位置记录实际异常与恢复结果。 |
| 使用显式 `--html-file` | 验证输入文件 SHA 与保存来源的绑定；已有有效来源可复用，不能仅凭 summary 自报字段放行。 |
| 已有来源损坏或身份冲突 | 明确拒绝采用，保留已有证据并说明缺失阶段，不自动覆盖或改用另一来源。 |

真实 Vision 验收必须检查实际 OCR 结果/manifest/checkpoint 的绑定。一个自报 `OCR_OK` 的 JSON 字段不能单独证明 OCR 已完成。

## 4. 附录失败披露验收

在合成或冻结的只读输入上运行真实附录 CLI，校验输出 JSON 与 Markdown 两者：

- 108 条去重上市线全部保留，A81/BJ3/HK24；拒绝行情的行仍为 `null` / `CANNOT_CONFIRM`。
- PARTIAL receipt 的状态、5137/5800、coverage_rate、REBUILD_REQUIRED、receipt row_count、路径及 SHA 仍作为已读取的回执事实披露。它们不意味着面板绑定通过，不是 108 条代码的匹配率。
- exact-date row_count 不匹配时，价格不进入结果，不能出现“逐行精确匹配可用”等成功断言。
- HK 缺前一交易日 receipt 时，明确显示缺口；不得伪造 receipt 或换第二行情源。
- 零条有效价格观察不被渲染成 0% 收益。一次附录批次对同一失败 probe 不重复读取整表。

Issue 中“实际表 5125 行”是此前任务的观察。本候选的离线合成测试不构成对该真实大表的再次测量，不能把该数字写成本轮独立复测结论。本批不重建市场面板，不改 scheduler/pointer 或消费门禁。

## 5. 一次有界的完整恢复与交付

基于当前运行树确认可执行入口后，进行一次有界恢复。保留分层结果：源抓取、浏览器读取、prepare/Vision、冻结包、Drive 交接。某一层失败时，依据已验证 artifact 继续或报告该层缺口，不能将所有层标成不可用。

必须记录：实际命令和最终 argv、run/attempt 标识、每个阶段的开始与结束、重用/新请求计数、源/图片/OCR 的前后 SHA、冻结 package_id/input_digest/ZIP SHA，以及独立 Reviewer 结果。

Drive 交接需由真实 provider 读回文件 metadata，记录文件 ID、父目录和可获得的 revision/修改标识；验证 START_HERE 指向同一冻结 package。下载已交付 ZIP 的原始字节，复算 SHA 并与本地冻结 ZIP 一致。单有一个可打开的链接不足以证明上传内容和版本正确。所需工具不可用的步骤记 `CANNOT_CONFIRM`，保留本地冻结包并报告具体交付缺口；不因此重新抓取 BODY/原图。工具超时不写成读取成功。

对外发布、服务重启、实际部署、共享面板替换、latest/正式池、BUY gate 和交易均不在本 issue 授权内。本协议先在隔离候选中完成可审查的验证；若后续动作触及这些边界，按真实所需权限另行处理。

## 6. 回滚与关闭条件

候选只修改 `SOURCE_MANIFEST.json` 列出的文件。测试前保存实际 before 字节及 SHA；隔离候选回滚使用这些 before 文件或经过验证的反向补丁。回滚后复算 SHA，不能通过整目录覆盖回退已验收 R1。保留所有 attempt、失败回执和独立复核证据。

最终状态分别填写 `IMPLEMENTED`、`TESTED`、`REVIEWED`、`BEHAVIOR_VERIFIED`。只有真实 Mac 入口、实际 collector/Vision 与有界完整交付都具备独立验收证据后，才可讨论缺陷是否关闭；本交付和 10.8 单篇恢复均不自动满足该条件。
