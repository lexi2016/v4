# 现场执行接续：先累计集成，再逐层验收

本轮 Chat 已交付的范围是代码、独立测试和本机执行交接。固定问题包明确不包含本轮 Mac 补采、POST、启停、启用或部署；此文件为唯一集成 owner 准备具体入口，不是执行回执。

## 1. 应用次序与精确前像

R1 固定交付：`008649895054cb24f1d1c3df37e215d307615db3`，目录 `handoff/manager-daily-automation-repair-20261008-r1`。先按其不同 profile、实际源码根和共享发布保护完成累计候选核验。两份曾验收的旧补丁与 R1 不能假定已经部署。

在累计候选中的经理 `workspace.py` 精确等于 R1 后像 `58a471c5ce7ece837c66948392ec2e6d73459343515225e19d694749c45ab1a4` 后，才应用本包 `source_manifest.json` 所列 R2 增量。若当前已有合法改动，先由唯一 owner 合并并重验，不能为满足前像回退新功能。

web 侧原 `catalystObservationPanel.ts` 的 R1 后像为 `516b20050a9c4911415f8d5d9b94e5f58aa74c6b01711ec728edbe7582b351c6`，单独在实际完整 web 根核前像并应用该文件增量。API 与 web 是不同 profile，不在一个混合根盲目执行全包覆盖。

原 `verify_delivery.py` 随包按 R1 完整原字节复用，核全部 after/patch 和所选实际根，不改业务源码。`manager_r2_root`、`manager_api_root`、`manager_evidence_root` 均由当前实际绑定确定为绝对路径；报告目录在源码根之外且预先存在。

```bash
python3 "$manager_r2_root/tools/verify_delivery.py" \
  --source-root "$manager_api_root" --profile api --against before \
  --report "$manager_evidence_root/r2-api-before.json"
```

由原集成流程应用本包一个 API 增量后，同命令改为 `--against after` 并使用新的报告文件名。对整个 R1 API 的后像验证，应先在应用 R2 前执行；R2 后这个文件的 SHA 合法变化，不能继续要求它等于 R1 的旧后像。其余 R1 文件与保留 gate 仍逐项核验。

web 使用同一只读验证工具，参数改为 `--source-root "$manager_web_root" --profile web`，分别生成 before/after 报告。R1 web 的完整后像核验同样在 R2 增量应用前完成，之后核本轮新后像及所有未改文件。

`dependencies/web_original/` 是从固定原来源恢复的测试依赖，不能作为盲目覆盖现场 web 的补丁。原 HTML 和实际应用依赖由现场完整根核对。本包前端生产 delta 只修正生成计划请求的一个日期变量引用。

## 2. 三项输入身份先读回

1. 原 V4 US 任务：当前非敏感 label/argv/解释器/app/data/ledger roots、原四槽策略、实际 executor 路径与 SHA；确认 data root 与 API reader 相同。保留已修复 `16f7895…` runner，不启用另一份 V35 US producer。
2. 原公告 06:30 heartbeat：实际执行入口和既定 Reader→独立 Reviewer 的调用/输出/恢复合同；取得真实 evidence run 后续产物。不能用一次 import 回执代替每日执行。
3. 原 HK child：实际 updater 命令、导入模块路径/SHA、同次 manifest 的 source SHA，与现有 actual shared owner `45a5091c…` 对齐。保留真实单位、六日尺度、资格与 PIT 未证明状态。

这些只需身份和来源事实，不要求上传凭据、原行情或研究 seed。来源不足时分别留阻断，不清空其他已验证通道。

## 3. 真实 10/8 补算与默认页面的两个验收口径

继续使用 R1 [HOST_EXECUTION.md](https://github.com/lexi2016/v4/blob/008649895054cb24f1d1c3df37e215d307615db3/handoff/manager-daily-automation-repair-20261008-r1/docs/HOST_EXECUTION.md) 的原 US owner、plan owner、精确三日绑定 GET 和失败恢复入口。两次 POST 不生产公告外部审核产品，也不执行 HK capture 链，不能当作三路供源已齐。

10/8 若在 10/9 或以后运行，记录服务器真实执行时间，标明事后研究，保留 target=10/8、US completed session=10/7 与每个来源 cutoff。能消费的合法通道保存逐股结果，缺失通道保留明确原因；不倒签盘前历史。

普通页面默认 `auto` 对过去日仍读取当时合格历史。真实 10/8 事后计划用原“现在回看（可能含后续消息）”显式 `dynamic` 核验；同时保留默认历史读回结果。R2 没有改变这项历史规则。

验证 R2 默认路径时，使用一个当前日或原晚间下一交易日目标的真实已保存计划，按精确相同 selection/publication/plan 绑定重载普通页，**不要切换成 dynamic 才测试**。核当前 DOM、当前网络 GET 与同一个 run/SHA/readback，刷新后重新取当前页面节点；确认真实 `read_at` 前进，封存研究 cutoff 不因单纯读取移动。

随后更改 selection、publication、plan 日期，并让一个旧请求晚到，确认旧股票和旧理由不混入新日期。US owner 缺输入/失败的真实回执应仍允许公告合法结果显示，unknown 数量不得被写成 0。

## 4. 跨日和连续自然验收

正式启用与自然观察由原共享流程执行。本包没有造第二 daemon、cron 或 ChatGPT 提醒代替业务调度。原日期合同和五个同日 catch-up、预算、幂等与恢复逻辑继续来自 R1。

至少两个连续适用 HK 交易日分别保留：原自然 dispatch/slot → 各路真实输入 → daily owner receipts → 同 target 不可变 run/attempt → 计划 → API GET → 重新加载普通页面。再验证第二日 latest 推进后第一日 exact 原件及旧计划仍可读，真实损坏仍拒绝。

若 10/9 未在原自然窗口完成部署启用，不能事后把它补算成自然第一日。按原日历选接下来真实发生的两个连续适用日期，并继续记录原 US 周末 POST_CLOSE 与 HK/Connect 日期的不同边界。

验收中必须区分：真实评估后的零入选、未评估/输入不足、事后补算、隔离日期测试和自然调度。当前自然状态保持 `NATURAL_SLOT_UNVERIFIED`。

## 5. 回滚

撤回 R2 时只逆向撤销本包精确 `workspace.py` 与 `catalystObservationPanel.ts` 增量，恢复 R1 对应前像并按当前累计基线重验。R1 是否回滚属于原受保护发布流程的独立决定。不可删除或改写历史 run/attempt，不可切回旧整包覆盖预选池和并行修复。
