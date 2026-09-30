# R3-B 实际测试结果

作者环境：Linux / Python 3.13.5。仅本批 10 个测试，不重复未变化的 R1 47 项/R2 27 项；它们仍引用 cf306997… 中已有独立回执。

1. 相同新测试在适用前像上：**5 failed, 5 passed, exit 1**。五个实际断言失败是旧pin、旧witness、旧root、退回release-local仍显示显式绑定、失败authority仍显示旧pin。无收集/setup错误。
2. 精确修复后：**10 passed, 0 skipped, exit 0**。完整新测试一次执行，不拆运行拼结果。
3. `tools/run_tests.py --app-root … --output-dir …` 在作者环境实际执行成功，导入路径和源码SHA见 logs/run_receipt.json。
4. `runtime.patch` 与 `tests.patch` 在临时目录正向应用、与完整后像比对、逆向恢复均由 tools/verify_delivery.py 核验。没有改活动路径。

## 验证不是纯函数或内存假store

`refresh_workspace_plan → get_workspace/_compute_workspace → gate_workspace/selection_diagnostics → ManagerResearchStore._transaction/_write_atomic → _read_plan/_readback_plan` 全部运行原方法。写入临时磁盘的按run文件/latest以及attempt journal都实际存在；随后新建一个同路径Store实例做读回。原writer、存储方法、workspace组装/保存/读回均未被mock。

替换的是资格reader返回值、公告/资讯/价格等上游边界，以及测试进程时钟。资格与股票全部合成；原资格producer、原MaterialStore实际公告链、Futu、HTTP API/UI不在本批验证范围。作者环境依赖来自既有R1交付的reference/source_handoff+R1 after及R2 after，**不是Mac完整R2候选的拷贝**；核心前像和scope已按冻结身份核对，不能将整个reference树部署。Work在其完整已验R2候选上运行相同10项做独立验收。

## 用例

- changed-pin：同日、同membership/artifact/input_identity，返回新pin，原run/product SHA/磁盘字节不变；至少一只合成allowed股实际保留，另一只合成非资格股仍拒绝。
- binding不变：正常复用，只更新本次reader witness，不回填采集时钟。
- root变化、切回release-local：旧绑定字段不能残留。
- authority失败：仍为空名单并返回当前失败诊断。
- deepcopy：修改响应不污染当前输入或保存产物。
- membership失效：原STALE_INPUTS_CHANGED与fail-closed保留，名单不扩大。
- 保存文件破坏、较早cutoff、无保存产物：仍分别失败、拒绝消费、只读预览。

所有用例有网络阻断；安全标志/股票qualified/正式推荐数同时校验。

evidence/changed_pin_witness.json 是本次测试产物；pin为合成111…/222…，run_id由原writer在测试执行时实际产生。它不是独立Mac/Luna或真实经理API回执。

R3-A/F0、独立Mac审查、部署、API/UI和自然运行均未完成。
