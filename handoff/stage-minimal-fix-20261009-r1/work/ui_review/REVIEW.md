# UI 独立审查：条件式源码 / Vue SSR 通过

最终结论：**PASS_CONDITIONAL_UI_SOURCE_SSR**。源码范围内没有剩余阻断发现；本次独立发现的一项 P2 已修复并复验。未执行浏览器、完整 App TypeScript 构建、8873 现役页面、部署或自然时段验收。

## 输入身份

审查 3 份前后像：`App.vue`、`StageExecutionEvidencePanel.vue`、`contracts/runtime.ts`。前像分别与固定 `28ab2d35020adf031f10f38c1040514fc81b6d66` 下 10/5 历史 API UI 路径的 Git blob、SHA256、字节数相符。20 文件问题包没有提供当前 frontend asset 身份；因此这是条件式 UI 候选，不能把历史前像当 10/9 现役包。

最终冻结 SHA256：

| 路径 | SHA256 |
|---|---|
| `apps/web/src/App.vue` | `e13a92e7f990ef18de0909edf0d2644410ba55194b21b583d43b76d648801dc5` |
| `apps/web/src/components/review/StageExecutionEvidencePanel.vue` | `6cb4aecf34fe69a0b95af9075bfabbcd0c504dc29026cb31edd17ef83f764a6a` |
| `apps/web/src/contracts/runtime.ts` | `c440de3ff964daa01994cbcd04d9b3ce1f417737a39034520c478ef83448bebe` |

测试后重新读取三份文件，SHA 均保持冻结值。

## 独立发现与闭环

**UI-P2-001：新响应缺少某市场摘要时错误回退旧回执。** 初版以 `selection_results` 是否具有某市场键判断新旧合同。明确存在新版摘要对象，但缺 `A_SHARE` 键时，组件依然把旧 bound receipt 的计数显示为「已计算 10 只，行情 206 / 216」。这混淆了旧响应没有新字段和新响应缺市场摘要两种状态。

初版作者 21 项独立复跑全部通过；独立 25 项探针为 **24 PASS / 1 FAIL**，原失败日志保留。作者只改一个判断：只有 evidence 顶层完全没有 `selection_results` 字段，才允许旧回执分支。明确的新摘要缺市场、空 map 或空市场对象保持待核。作者补两例后套件为 **23 / 23 PASS**；原独立 25 项逐项复跑为 **25 / 25 PASS**。两组最终均无失败、跳过或取消。

## 核实的行为

- 已验证选股摘要先显示计算结果；执行回执缺失、未绑定或仅声明 NATURAL，不抹去已有 A 股结果。
- 新 `NO_VERIFIED_RESULT`、null 摘要或缺市场摘要不能由旧回执计数补成已计算。旧兼容分支只接受精确 `BOUND_TO_VERIFIED_SELECTION`，行情数量清楚标为回执记录计数。
- null、负数、非整数、布尔、字符串及超出安全整数范围的数量保持未知／待核；合法空结果明确显示 0。行情来源行数超过请求数或缺口数冲突显示待核对。
- A 与 HK 单独显示；已有 HK 真结果不会被旧 HK「预选池未就绪」覆盖，后者另列为当前回执声明。HK-only 尾盘不会渲染 A 市场。
- `OWNER_HISTORY_SHA_BOUND` 与 NATURAL 字样只显示 owner 历史核对及声明的模式，自然时段验收仍为尚未验证。没有从日期、阶段或当前时钟补写历史时间。
- Vue SSR 对诊断文本转义；原技术详情保留在默认关闭的 details 中。

## App 最小变更核对

以字节比较证明，`App.vue` 后像严格等于前像的一次提示文案替换，除此之外完全一致。日期／阶段初始化、选择控件、按钮及事件、组件挂载条件、结果列表、分页上限、历史导航均无变化。

`runtime.ts` 仅追加可选的 execution readback 字段，删除这一新增块后与前像逐字节一致；没有改原已有类型。

## 测试真实性与限制

环境：Linux、Node **v24.19.0**，Vue / compiler-sfc / server-renderer 均 **3.5.13**。作者套件由独立执行者重新运行。独立 harness 另行读取冻结 SFC，通过真实 Vue compiler 产生 SSR 代码、去除 TypeScript 类型后使用真实 Vue server-renderer 渲染；测试断言实际生成的 HTML 文本，没有把组件逻辑替成字符串 mock。

Node `stripTypeScriptTypes` 有 ExperimentalWarning，原日志保留。这不构成 TypeScript 全项目类型检查；没有执行完整现役 App 构建或浏览器交互验收。

复跑命令（工作目录为仓库 scratch 根）：

```sh
STAGE_UI_PHASE=after node --test stage_minimal/work/ui_presentation/tests/presentation.test.mjs
node --test stage_minimal/work/ui_review/tests/independent_presentation.test.mjs
```

`REVIEW.json`、`evidence/INITIAL_SOURCE_IDENTITY.json`、`FINAL_SOURCE_IDENTITY.json`、前像 blob 核验、App 差分核验、初始 RED 和最终原始 stdout 一并保存。该结论仅覆盖可审查的候选源码；本机必须核当前实际 UI 前像，匹配后再按原应用流程构建、发布及读回。
