# 证据索引与检查点

最终源码身份以 [SOURCE_MANIFEST.json](SOURCE_MANIFEST.json) 为准，最终整包测试以 [TEST_RESULTS.json](TEST_RESULTS.json) 为准，独立结论以 [最终审查](evidence/independent_final/final_review.md) 为准。旧失败和作者报告保留当时结论，不回写历史。

| 路径 | 含义与使用方式 |
| --- | --- |
| `original/issue30/`、`evidence/input/` | 原九文件问题包、Issue 正文和远端字节校验，固定输入提交为 `a0a0b88d…` |
| `original/r2_app/`、`original/two_hunk_reference/` | 精确 R2 app 单文件前像、既有两处修复参考；不构成完整现役依赖闭包 |
| `after/`、`patches/`、`change_sets/` | 最终八个产品后像、对原输入的差异及三个预选池文件的 change set；尚未安装到 Mac |
| `evidence/core_initial/`、`core_revision/`、`builder_prepare/`、`builder_revision/`、`policy_revision/` | 各阶段复现与源码回归，历史测试数不与最终套件重复相加 |
| `evidence/preselection_initial/`、`preselection_revision/` | 来源、历史依赖身份、非预选代码保留，以及旧 SHA/行身份修复的失败和通过记录 |
| `evidence/independent_initial/` | 初审五项 Important 与七个失败执行；原 `CHANGES_REQUESTED` 不改写 |
| `evidence/independent_revision/` | R5 版本 `1f41…` 的 63 PASS，及新增 R6/R7 的两个独立失败；对应源码与原始探针保留 |
| `evidence/cutover/` | 作者恢复修订过程，初始 21、R5 阶段 63、最终 76 分开。作者报告的 `PENDING_INDEPENDENT_FINAL_REVIEW` 是报告冻结时状态；最终独立结论见下一行。`PACKAGE_MAPPING.json` 将作者工作区路径映射到本包实际文件 |
| `evidence/independent_final/` | 最终独立源码审查、精确 SHA、原始探针复验、app 保留证明与补丁往返核验 |
| `evidence/portable_final/` | 根目录 runner 从新目录实际执行 112 + 76 + 30 = 218 项；含输入、布局、环境、依赖、命令、日志、收集事件和 JUnit |
| `evidence/portable_controls/` | runner 自身 24 项控制检查，以及文档审计和修订记录；不属于新增产品用例 |

`TEST_INPUTS.json` 绑定 64 个运行输入；`FILE_MANIFEST.json` 绑定同步至 GitHub 的全部交付文件（自身除外）。源码包中的 mode 是 Git 文件合同，实际 Mac 文件元数据须在本机核验。ZIP 内另附的 `GITHUB_SYNC_RECEIPT.json` 在远端提交与读回完成后生成，不参与其所记录的提交，避免自引用。

所有实际服务、生产 API/UI、自然时段、当前完整 R2 启动和真实来源 canary 的状态仍分别为 NOT_RUN / CANNOT_CONFIRM；合成测试结果不能提升这些状态。
