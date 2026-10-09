# 本次前像状态

**本次补丁所需前像已齐；required_now = []。** 不再要求 Mac 回传已提供的 App/runtime，也不把明确新增的组件当作缺失旧文件。

依据固定反馈 `3112c1ee8ed2826c5d77b5d0a4f1e2cd5fc95e45`：

| 范围 | 已有证据 | R3 操作 |
|---|---|---|
| 实际 Stage 16 文件 | Mac prepare 逐项 BEFORE_MATCH，原 after SHA 全匹配 | 保留 R2 的完整业务 after；候选准备工具适配链接。 |
| 实际 API 2 文件 | Mac prepare 逐项 BEFORE_MATCH；0555/0444 的 lstat 与 Errno13 原始错误 | 保留 R2 的完整业务 after；只修新副本写入权限。 |
| 当前 App.vue | 完整原字节；SHA `ffbfcde222175c7849dfd5a1089cafe6c104dea2a1760b18645d95bc48780530` | 以此为唯一 before，最小适配。 |
| 当前 runtime.ts | 完整原字节；SHA `6d66ae53d26a6c48110d040ad0440bb023e88d49924a697d6671c6da51176d92` | 保留原类型，只增必要类型。 |
| StageExecutionEvidencePanel.vue | Mac 明确记录 ABSENT | `operation: add`，before path/SHA 为 null，accepted_before 为空。 |

完整逐文件前后 SHA 与实际来源身份在 `SOURCE_MAP.json`。Stage/API 的“当前已核验”来自固定 Mac 回执，不代表 Chat 能访问 Mac。准备时仍重新读全部前像，防止反馈之后发生变更；未知占位组件与未知源 SHA 会一次列出具体不匹配，不覆盖它们。

## 保留为运行验收边界的未改依赖

`useAppShell.ts`、其 `types.ts/formatters.ts`、当前 web package/lock、实际 API factory/启动配置、真实 `pytdx_exhq.py` 均不在本次修改清单。准备工具复制明确源集合内现有文件并记录身份。已查到的 10/7 shell 仅用于理解接口，不冒充当前 shell；它把 Stage HTTP payload 原样赋给 stageWorkbench。

这不会新增前像请求或阻止本次三个已知阻断的代码交付。只有实际 canary/构建/同 run HTTP 明确报出这些未改接口不兼容时，返回报错对应的完整文件、当前 SHA256 和已生成收据，由 Chat 继续给出对应代码。不得用历史片段整文件覆盖 dirty canonical。

外部 `upstreams/v3.5` 的内容未提供也未读取；是否为动态依赖仍标 CANNOT_CONFIRM。准备工具记录精确链接身份并隔离，不复制未知 release。若最终有效配置实际指到这个隔离目标，驱动会给出具体冲突，不能把它误写成行情为空。
