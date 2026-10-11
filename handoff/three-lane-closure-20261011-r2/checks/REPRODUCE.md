# 复验范围与运行方式

本目录保留实际正向、负向、独立复跑、control 对照与源 SHA。时间和路径是原执行记录，不改写成 Mac 身份。API JSON fixture 来自合成原证据经原完整应用门禁后的返回，未删字段；不是真实 55 条或行情证据。

## 根 Python 命令

实际 cwd 是 `/workspace/scratch/90a399518fca/candidate`，解释器 `/workspace/scratch/90a399518fca/test_env/bin/python`。测试环境设置 PYTHONDONTWRITEBYTECODE=1 与 PYTHONPATH 为 candidate、candidate/upstreams、candidate/tests，命令为：

```bash
python -B -m pytest -p no:cacheprovider -q \
  tests/test_manager_three_lane_history_r1.py \
  tests/test_manager_three_lane_history_r2.py \
  tests/test_manager_three_lane_channels_r1.py \
  tests/test_manager_three_lane_channels_r2.py \
  tests/test_manager_three_lane_rebound_diagnostics_r1.py \
  tests/test_manager_three_lane_rebound_recovery_r2.py \
  tests/test_manager_three_lane_owner_readback_r2.py \
  tests/test_manager_research_selection_ledger.py
```

结果见 root/targeted_final.log 与 XML，106 passed / 1 skipped。独立原 owner/store/API 六项与独立省略 view 四项另见 frontend 的报告与执行记录。

原五套件为 manager_plan_identity_r2、manager_plan_readback_issue24、manager_workspace_targeted_r2、manager_business_completion_a/b。附件控制组与候选用同一测试支持目录运行，同 133 IDs、95 passed / 38 failed。比较摘要列出完整 failed ID，没有清除或归零失败。

测试支持的 r3_scoped_loader 仅为旧部分源码导出建立 namespace，避免缺失 __init__ 的副作用，不提供虚假业务函数；完整 Mac 必须不依赖这个助手。原 fixture `three_lane_announcement_original_fixture.py` 字节完全复用原 39 项公告 fixture，新增 owner 测试使用它的真实原应用入口。H5354 的合成输入只在 fixture 生成时替换代码常量，所有原证据/receipt/hash 在其后按原实现生成，没有放宽原导入门禁。

## 独立前端

frontend/FINAL_FRONTEND_REVIEW.md 记录最终 Node/Vitest/typecheck 命令、镜像角色及完整结果。最终 53 项为 50 passed / 3 原 runtime failed；两个统一最新测试/fixtures 的镜像均保留同 6 条类型错误。新增 5 项 Readback、8 项日期、11 项独立边界均通过。

root/r2_unmapped_risk_red.log 保留新增断言失败，green 对应 Writer 修复；frontend/independent_boundary_vitest.log 是独立的修复前 RED，最终候选 JSON/log 和 report 是复验 GREEN。风险文字含 HTML 标签的输入仍为纯文本，不生成 script 元素。

## 原依赖与 Reviewer 脚本

HK 完整 Stage 的已证明范围是原选择器、原 SelectionStore、完整 consumer 加精确原 execution_evidence 的 review-only import overlay。membership/D1/Stage execution 上游输入均明确为 synthetic；不是原 authority 已恢复的证据。14 个 sidecar cases 使用原 reader 的完整文件校验，1 个完整 READY、12 个错误拒绝、1 个合法 partial 保持 pending。

hk_rebound/traceability/original_o_owner_save_trace_r2.json 是单独补做的原 refresh_workspace_plan → 原磁盘 store → service readback → FastAPI GET 同次追溯；其上游 screen 为合成输入，保存/attempt 门禁原样保留。其他“readback archive”纯边界探针如果用了内存 store fixture，只证明读回绑定，不能混称原 owner 已保存。

Review 脚本为原检查代码和复现证据，部分路径/默认值来自本轮工作目录。移植时按实际完整候选、原依赖和 fixture 位置调整调用参数/外部路径；不得改业务门禁以使环境通过。大临时 stores 已清理，未打进交付。recovered_dependencies 的原 role manifest 和完整读回 SHA 是判断是否可在现场恢复的依据。

## 包与差异核验

package_roundtrip.json 记录在全新隔离目录核 before → apply → after → reverse → before，22 项字节都匹配，额外并行文件不变。只读助手还拒绝符号链接根和 5 类越界/非规范相对路径。该检查不部署、不运行 owner、不证明 API/UI 或自然运行。

源码完整前后 SHA 见根 BEFORE_AFTER_SHA256.json；原附件未修改文件 SHA 见 attachment_and_protected_sources.json。最终 GIT_DELIVERY.json 记录已同步字节的远端读回，DELIVERY_MANIFEST.json 核本包文件。若现场合并产生新字节，必须更新身份并重新验证。
