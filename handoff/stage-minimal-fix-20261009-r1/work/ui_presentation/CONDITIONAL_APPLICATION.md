# 应用条件与回退

## 1. 先确定当前前端身份

本包前像是固定提交 `28ab2d35020adf031f10f38c1040514fc81b6d66` 中 10 月 5 日的历史 API/UI 参考。应用者应沿现有 Mac 发布链确认：当前 API 的启动目录与版本、页面实际静态资源目录、构建入口、浏览器加载的资源及其构建身份。仅有工作树修改或 API 返回新字段，不足以说明浏览器已加载新组件。

三个目标文件必须逐一匹配 `SOURCE_CHANGES.json` 的 `before.sha256` 和字节数：

| 目标相对路径 | 必须匹配的前像 SHA256 |
|---|---|
| `apps/web/src/App.vue` | `995a680995cc42feadeaa8d2bdd44294c8ec782a908d664c698faf69d4cf02a1` |
| `apps/web/src/components/review/StageExecutionEvidencePanel.vue` | `07188178bbcd5ae2b01b9d6c1ef9dffd7b94f1b27f0211501cc2464566c5bc8b` |
| `apps/web/src/contracts/runtime.ts` | `9a882a174b433488684b05781ade00beb665706e962f753700960a4250d13419` |

如果当前发布链的源码以 `src/` 为根而非 `apps/web/src/`，应先核对它确实对应这些文件并确定路径映射，不能因文件同名就认为身份相同。任一前像不匹配时，不直接套用本包完整文件或补丁；取得现役前像后，仅移植组件呈现、可选字段和一处提示文字的改动，并重新核对 App 差异、构建和页面。

## 2. 仅在匹配的隔离源码目录应用

在确认三个 SHA 后，以包含 `apps/web/src/` 的源码目录为工作目录，用本包补丁执行现有代码变更流程：

```bash
git apply --check /absolute/path/to/ui_presentation/runtime_ui_presentation.patch
git apply /absolute/path/to/ui_presentation/runtime_ui_presentation.patch
```

`git apply --check` 只能证明补丁上下文可用，不能替代前像 SHA 核对。应用后再次核三个文件，必须匹配 `SOURCE_CHANGES.json` 的 `after.sha256`。不要因为本包含有完整 `App.vue` 而覆盖其他模块已集成的修改。

API reader 的新增 `selection_results` 必须来自已核产物摘要；UI 不会自行认证选股 JSON。顶层 `selection_results` 存在时，该协议优先，即使某市场摘要缺失也不退回旧回执。整个顶层字段不存在时才启用旧 response 兼容，且“已计算”必须有 `BOUND_TO_VERIFIED_SELECTION`。API 候选合同的本次读取身份在 `API_CONTRACT_REFERENCE.json`，该文件也不是现役 API 身份证明。

## 3. 在现有构建链完成页面验收

复跑本包测试后，使用当前项目既有依赖、构建及发布流程完成全 App 验证，并核对实际被服务的静态产物。这个子包没有创建第二个前端、第二个静态服务或新的发布通道。

应以各自证据层分别验收：

1. 当前 API 日期与阶段正确。A 股有已核 10 行时显示已计算，行情 205/216 时显示缺 11，206/216 时显示缺 10；空值保持未知。
2. HK 正式预选池未绪时说明未进入算法；不能让 HK 的失败掩盖 A 的真结果，也不能让旧 HK 失败声明覆盖已有核实的 HK 结果。
3. 无运行回执时仍能显示独立核实的选股产物。声明 `NATURAL`、owner 历史绑定和自然验收分别呈现；缺失记录时间不补造。
4. 新摘要缺市场键、明确 `NO_VERIFIED_RESULT` 或身份冲突时不升级为运行已核实。原技术记录仍可展开查看。
5. 现有日期、阶段切换、按钮与 StageSummary 行为不变；核对浏览器真正加载了对应新静态资源。

自然阶段运行证据和业务数据是否恢复，仍由真实任务和其独立验收决定。UI 显示正确不能代替这些验收。

## 4. 回退

逆向操作前先确认目标文件仍精确匹配本包 after SHA；如果后续又有修改，不直接逆向覆盖。对精确匹配的隔离源码可用 `git apply --reverse --check` 后再 `git apply --reverse` 恢复源码，并按现有发布流程处理实际静态产物。仅逆向源码不表示正在服务的页面自动回退。历史前像完整保留在 `before/`，本地补丁往返字节验证见 `evidence/PATCH_ROUNDTRIP.json`。
