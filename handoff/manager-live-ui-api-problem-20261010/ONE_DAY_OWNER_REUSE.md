# 既有单日 owner 链路：Chat 接入参考

## 日期和事实必须分开

- 已证公告子链：target 2026-10-08 / publication 2026-10-07；独立 review 记录 613 Reader 行、613 个由不同身份给出的 Reviewer disposition、33 selected，owner import receipt 为 VERIFIED。这证明该日期对的 owner/import 链可复用，不代表目标 2026-10-09 已完成。
- 目标工作台日期：target/selection 2026-10-09 / publication 2026-10-08。当前真实发布接口把 ANNOUNCEMENT 报为 CANNOT_CONFIRM / ANNOUNCEMENT_ANALYSIS_NOT_IMPORTED；修正隔离 run 的该日公告 owner 为 NOT_RUN。
- 用户提到的 2026-09-30 单日成功：receipt 在当前限定 evidence 中 NOT_FOUND，结论仍 CANNOT_CONFIRM。该日期的 09:53 workspace plan 只是 PARTIAL 的受限计划记录，不作为用户所述独立成功 run 的反证或证明。
- 2026-10-10 owner readback：手动 retrospective，不是 10/09 natural run。fused live deployment 的 POST + 2 GET 与稍后的 independent GET 状态不同；另一个修正 root 的隔离 owner run ID 1165ef2326614d83be4acaaa0c7ca27a 为 PARTIAL / 0 stocks，仅有两次同进程函数读回 CURRENT，不能当部署 API 或页面验收。

## 包内代码入口

- code/current_fused_app/ops/run_manager_daily_announcement.py 是现役 fused release CLI，SHA 在 SOURCE_SNAPSHOT_MANIFEST.json。其 capture、prepare、build-reviewed、register-handoff、import、readback 子命令绑定及参数可直接查源码末尾。
- code/previous_reference/actual_owner_runner_20261009/ops/run_manager_daily_announcement.py 是已有真实单日 owner workflow 的原代码快照（reference-only）。配套 service/store/reader、US mapping、plan runner 和 readback checker 都在同目录；每个快照有源文件 SHA。
- code/previous_reference/r3_20260930_reference/ 保存已有 announcement original-owner capture/material/Reader/Reviewer 注册和计划接口。
- code/previous_reference/r1_20261007_announcement_consumer/ 保存已消费的 announcement reader/consumer 代码版本。

这是源代码和命令接口参考，不是可脱离原 owner inputs 独立运行的离线 producer。Chat 可以在 snapshot 上实现/测试最小 reader/consumer 修复，但无 Mac 真实 owner roots、输入和运行权限；不能直接执行 capture/import 或说真实链路已闭环。

## 已有调用顺序和数据合同

### Announcement

1. 用原 owner CLI 的 capture --target-date ... --publication-date ... 建立精确日期 owner catalog readback 与 body capture；capture 会访问原 API/来源并产生输入工件，不能由 Chat 离线冒充。
2. prepare 校验同日期 catalog、semantic catalog、body corpus 与 capture evidence，不写业务产品。
3. 由原流程产生 Reader decisions 与独立 Reviewer dispositions；两者身份不同并绑定同一个 evidence run/date pair。
4. register-handoff 校验 Reader/Reviewer 文件与 SHA、日期和 identity；import 经过原 owner API 导入；readback 对相同目标日和 publication 日校验 product 与 import receipt。
5. Workspace/plan consumer 应基于已导入、hash 校验的产物显示 channel 状态；没有 VERIFIED import receipt 时保持 NOT_RUN/CANNOT_CONFIRM。

CLI 参数和解析代码都在包内快照；不要从 Chat 新建 scraper、classifier、reviewer 或 parallel producer。

### US mapping

复用 ResearchPeripheralStore/external_finance 的已绑定输入与 ManagerResearchJobService.refresh_us_mapping_research；再让同一 owner/store 的 plan 引用该 run/product/input identity。当前部署的 VALID_EMPTY 是 4 个已审 relationship 的局部范围结果，0 match 不表示 full US market 无匹配。修正隔离 run 的外部 finance owner payload 显示 READY，但缺 market_snapshot，所以该 run 没有可用完整市场 snapshot。两种结果来自不同 run，必须标出对应来源。

### HK Connect 与 oversold

target-day membership 继续读取现有 V2 authority owner root；已确认 V3.5 shared root 下的 exact-date HK02 panel 不替代 V2 universe membership artifact。对 screen，正确 V3.5 root 下 exact 20261008 HK02 panel 存在；exact-date security-master entry/supplement pointer 缺失。六 session volume unit/scale 未证实且 provider finality 未认证前，保留 NOT_PROVEN 和 pending。不要把早先错误 V4-root 绑定产生的 panel-missing 诊断沿用，也不要在 cutoff 之后通过重新采集回填历史 PIT。

### Plan 与页面

consumer 需要比较保存计划的 input identity 与同日期当前投影；API 读取不能改写 owner run。日期、semantic、cutoff 和产品 sha 的相同情况要与 input identity 分开报告。页面首屏应直观显示三路摘要、current/stale/consumed 和差异线索；raw observations 完整保留到可展开区，不要当成主要结果。

## 本地可复核命令

从解压后的 package 根目录：

    python3 tools/verify_package.py
    python3 tests/check_evidence_contract.py

这些离线命令只校验复制源码/证据 SHA 和上述真实 receipt 的关键断言，不运行 original owner CLI、不访问服务或网络。原 CLI 源码引用环境参数，但为了安全，本包不提供真实状态、行情或凭证。
