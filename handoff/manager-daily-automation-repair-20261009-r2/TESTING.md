# R2 测试、环境与复验

本轮按冻结问题包使用一名单写入者 Luna Max Writer，并由另一身份的 Luna Max Reviewer 独立验收。主控分别核最终 SHA、来源范围和补丁重建，未代写独立审查结论。

## 实际结果

| 执行者 / 范围 | 实际结果 | 证据 |
| --- | --- | --- |
| Writer：默认 auto、精确绑定回归 | 2 passed；已包含在下行 59 项内 | [日志](evidence/writer/default_auto_api_green.log) |
| Writer：workspace/history 原组合 | 59 passed / 1 failed；失败在冻结 R1 原样重现 | [未筛选组合](evidence/writer/workspace_history_regression_green.log)、[原基线重现](evidence/writer/hk_history_failure_baseline.log) |
| Writer：上述组合明确排除已证基线失败 | 59 passed / 1 deselected | [限定组合](evidence/writer/workspace_history_scoped_green.log) |
| Writer：完整原父组件经理研究区 | 5 passed，包括生成按钮和默认 GET | [完整父组件日志](evidence/writer/full_parent_green.log) |
| Writer：真实经理生产 import 闭包类型检查 | PASS，exit 0 | [实际配置](evidence/writer/manager_page_typecheck.tsconfig.json)、[日志](evidence/writer/manager_page_typecheck.log)、[命令与 exit](evidence/writer/writer_final_report.json) |
| 独立 Reviewer：新写 API / owner 合同 | 4 passed | [独立测试](independent_tests/test_workspace_auto_readback_contract.py)、[日志](evidence/independent/independent_api_regression_final.log) |
| 独立 Reviewer：原历史分支边界 | 2 passed | [日志](evidence/independent/selected_history_regression.log) |
| 独立 Reviewer：复跑并审查完整父组件经理研究区 | 5 passed | [日志](evidence/independent/full_parent_sfc_daily_integration.log) |
| 主控：有限补丁重建 / 范围检查 | 5 个 delta 正向应用、精确 after 集合和逆向恢复；API/web/tests 三 profile before/after 均通过；1,024 个 R1 基线文件原字节保留 | [补丁核验](evidence/package/patch_verification.json)、[范围](evidence/package/source_scope_audit.json) |

**以上测试数不累加。** Writer 的 2 项属于 59 项内，按钮单例属于 5 个父组件场景内；Reviewer 的 5 项是独立环境执行和代码审查同一 Writer SFC 测试。新增独立编写的 4 项 API 测试另列，两个历史边界用例来自原 R1。

完整原始作者报告分别是 [Writer](evidence/writer/writer_final_report.json)、[独立 Reviewer](independent_tests/final_review.json) 和 [独立审查说明](evidence/independent/R2_INDEPENDENT_REVIEW.md)。报告内绝对路径是实际执行记录；复验时按下方变量绑定当前隔离根。

## RED → GREEN 和断言内容

默认路由 [API RED](evidence/writer/default_auto_api_tdd_red.log) 与 [父组件 RED](evidence/writer/full_parent_tdd_red_confirmed.log) 均实际返回了保存后 `STALE_INPUTS_CHANGED`。默认 GET 恢复封存上下文后，测试确认同 run、同 cutoff、真实新 read_at，以及错误日期/真实新来源仍拒绝。

生成按钮 [RED](evidence/writer/explicit_refresh_tdd_red.log) 实际没有发出 POST；日期变量修复后，原路由收到 target/selection/publication，随后默认 GET 和当前 DOM 返回同 run。测试在独立临时 store 中执行，避免污染其他只读用例。

父组件的日期竞态测试真正挂起旧响应，在日期改变后释放，等待 JSON 被消费和下一次事件循环再检查新日期 DOM。刷新检查重新查询当前 DOM，不使用脱离页面的旧节点。US 缺输入由原 owner 实际保存 `INPUT_MISSING` 和 run/readback receipt，页面仍显示公告 READY 与原合成理由，未知数量保持未知。

独立测试还验证下一交易日 evening 计划的 auto 读回、合法 source-owner 替换使旧计划过期、晚到 scheduled/LATE_CATCHUP 的真实原 owner 临时产物留在旧 cutoff 外，以及 `include_saved=False` 使用新评估时刻。所有 market/review/dispatch 数据均明确合成，`natural_run_verified=false`。

## 保留的失败和未执行范围

完整 `npm run typecheck` 的实际结果为 **exit 2**：缺原 `issue8R2.ownerObservations.json`，其派生类型诊断，以及原 `ManagerSelectionView.spec.ts` 两条已有 unused `@ts-expect-error`。本轮修复的 `selection_date` 诊断已经消失。[原日志](evidence/writer/web_typecheck.log) 保留，没有造真实 owner observations 的替身。

完整 `npm run build` 实际 **exit 1**，在原 `daily-research-command/index.html` 缺失处停止；另一个原 `manager-selection/index.html` 也尚未提供。[原日志](evidence/writer/web_build_closure.log) 保留。限定生产入口类型检查不替代完整应用构建。

HK 原历史用例 `test_exact_panel_selected_without_latest_substitution` 对故意损坏的 `panel_latest.json` 期望与当前原 reader 拒绝不符，返回 `PLAN_HK_02_PANEL_LATEST_MANIFEST_UNREADABLE`。同一测试和 `workspace_plan.py` 在候选/冻结 R1 哈希相同，R1 原样复现失败；本轮不修改它或超跌门槛。

Reviewer 最早两次 harness 断言不符合原返回合同，已由其更正并保留迭代日志：[首次](evidence/independent/independent_api_regression.log)、[中间](evidence/independent/independent_api_regression_fixed.log)。最终四项完整合同通过；没有为这些错误修改生产源码。

父组件测试只对经理研究区的原请求执行真实 TestClient 传输，无关页面请求明确返回 404，整体页面可能为 ERROR。没有启动正式应用服务或操作 Mac；真实 10/8、现场 API/浏览器、部署/启用、共享 #28 联合保留和连续自然交易日均 **NOT_RUN**。

## 环境与依赖

[实际环境记录](evidence/runtime_identity.json)：Python 3.14.6、pytest 9.1.1、FastAPI 0.141.1、Starlette 1.6.0、httpx 0.28.1；Node 24.19.0、Vue 3.5.40、Vitest 4.1.10、TypeScript 5.9.3、vue-tsc 3.3.8、Vite 7.3.6、jsdom 28.1.0。

临时依赖链接已清理；venv、node_modules、dist 未入包。两件恢复的原 TS 依赖按 [固定来源](required_dependencies.json) 核 SHA 后用于隔离测试；其他原 Python fixture/test 的固定 commit/path/SHA 在 [测试依赖来源](evidence/test_dependency_lineage.json)。这些来源清单不是一个完整可部署应用。

## 复验命令

先按 R1 源码根映射装配隔离测试树，再应用本包 5 个源码/测试 delta，并按 SHA 接入两件原 web 依赖。不要覆盖实际服务目录。以下 `manager_r2_root` 是本包绝对目录；`V4_TEST_SOURCE_ROOT` 是该隔离树，`V4_TEST_PYTHON` 是其 Python 3.14 解释器。前后源码核验使用本包原 `verify_delivery.py`。

```bash
export V4_TEST_SOURCE_ROOT="/absolute/isolated/manager-source"
export V4_TEST_PYTHON="/absolute/python314/bin/python"
export PYTHONPATH="$V4_TEST_SOURCE_ROOT:$V4_TEST_SOURCE_ROOT/upstreams:$V4_TEST_SOURCE_ROOT/tests"

"$V4_TEST_PYTHON" -m pytest -q -p no:cacheprovider \
  "$manager_r2_root/independent_tests/test_workspace_auto_readback_contract.py"

"$V4_TEST_PYTHON" -m pytest -q \
  "$V4_TEST_SOURCE_ROOT/tests/test_manager_workspace_exact_page_binding_20261008.py"

cd "$V4_TEST_SOURCE_ROOT/apps/web"
./node_modules/.bin/vitest run src/views/ManagerSelectionView.dailyIntegration.spec.ts
```

限定生产入口类型检查复用实际配置的相同结构，生成到源码之外的证据目录；`types=[]` 仅去掉全局测试类型，原 strict/module 等编译设置从原 `tsconfig.json` 继承。

```bash
export MANAGER_R2_TYPECHECK_CONFIG="$manager_evidence_root/r2-manager-page-typecheck.json"
"$V4_TEST_PYTHON" - <<'PY'
import json, os
from pathlib import Path
source = Path(os.environ['V4_TEST_SOURCE_ROOT']).resolve()
output = Path(os.environ['MANAGER_R2_TYPECHECK_CONFIG'])
config = {
    'extends': str(source / 'apps/web/tsconfig.json'),
    'compilerOptions': {'types': []},
    'include': [str(source / 'apps/web/src/manager-selection/main.ts'),
                str(source / 'apps/web/src/views/ManagerSelectionView.vue')],
}
with output.open('x', encoding='utf-8') as stream:
    stream.write(json.dumps(config, indent=2) + '\n')
PY
./node_modules/.bin/vue-tsc --noEmit --project "$MANAGER_R2_TYPECHECK_CONFIG"
```

重新取得现场完整源码闭包时，再独立执行完整构建及实际浏览器验收；本包的限定测试证据不自动升级。
