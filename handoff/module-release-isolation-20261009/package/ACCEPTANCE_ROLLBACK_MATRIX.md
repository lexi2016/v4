# 独立发布验收与回退矩阵

在首次迁移前冻结每项身份：gateway/Stage/Manager 的 plist、PID、release root、manifest SHA、关键 source SHA、binding SHA、静态 bundle SHA、Stage selection/shared data roots、当前 readback 和安全旗标。首次平台迁移单独记录；后续模块发布不得借迁移窗口掩盖对另一角色的改动。

| 场景 | 可变对象 | 必须不变 | 必须读取/验证 | 回退范围 |
|---|---|---|---|---|
| Stage 独立升级或重启 | Stage release root/manifest/PID/Stage API source SHA | Manager PID、manifest/source SHA、API readback、binding、run；8873 gateway plist/PID/manifest/source/static SHA；shared data/state owner | Stage 固定同 date/stage/run 读回；所有 Stage route；Manager routes smoke；阶段产物仍符合 Manager 只读 consumer 合同 | 仅 Stage 回本角色上一 manifest/root；8873 继续 dispatcher |
| Stage 独立冷回滚 | Stage 当前角色指针 | Manager 与 gateway 全部身份和行为，含 binding/run | Stage route 返回原角色版本；没有旧 handler 暴露；其他模块同 baseline | 只切 Stage role previous release |
| Manager 独立升级或重启 | Manager release root/manifest/PID/Manager API source SHA | Stage PID、manifest/source SHA、Stage API 同输入读取；8873 gateway/static SHA；Stage selection state/readers/writers | 完整 Manager route table；`/api/v3/manager/stage-selection` 只读；Stage routes 同 baseline；binding/run 不因发布变化 | 仅 Manager 回本角色上一 manifest/root |
| Manager 独立冷回滚 | Manager 当前角色指针 | Stage 和 gateway 全部身份与行为 | Manager route 返回原 Manager role 版本；Stage readback 不变；无旧 gateway handler fallback | 只切 Manager role previous release |
| Stage backend 离线 / 错 role | 目标模块错误状态 | 另一模块、平台静态资源、其他合法平台 route | 分流路由按 503/504；错 role 拒绝；不调用旧 handler；已知 route 错方法 405 | 修复本角色或按角色回退；不重启另一角色 |
| Manager backend 离线 / 错 role | 目标模块错误状态 | Stage、平台静态资源和 Stage selection state | 同上；Manager 请求不被误送至 Stage；POST 不自动 retry | 修复本角色或按角色回退；不重启另一角色 |
| 独立锁与候选拒绝 | 本角色固定 role profile | 其他锁、plist、manifest 和候选目录 | 两个 module lock 可独立取得；错 plist/manifest/delta/静态路径/角色 identity 被拒绝；gateway 原有安全链仍有效 | 候选失败时保留未切换指针；无共享根旁路 |
| 平台静态页面发布 | 仅 platform-owned bundle/dispatcher，经平台独立窗口 | Stage、Manager API manifests/PIDs/bindings/runs | 8873 页面保持原 URL；读取页面资源 SHA；两个 API 的 route contract 回归 | 回平台前一兼容 dispatcher/bundle；仍保留 dispatcher，不暴露旧 API handler |

## 唯一 PASS 条件

Stage 与 Manager 分别完成一次候选升级、重启和 role-only rollback；每一步均证明未发布模块的 PID、manifest/source SHA、binding、run、API 行为和 8873 静态 SHA 不变。验证固定路由/方法、离线 503/504、错 role 拒绝、无 fallback、独立锁、共享数据/state owner 不变、A/HK 及安全 flags 不变。首次迁移另列证据，不可借其允许的整体变化放宽后续模块矩阵。

本问题包阶段以上均 `NOT_RUN`。实现候选 pass 也只代表工程候选；不会自动成为 deployed、API/UI behavior、自然时段或选股结果验收。

## 回退规则

- 初次迁移失败按迁移前冻结的整体回退流程恢复，恢复仍能服务请求的受控 gateway。
- 拆分完成后的冷回滚只能切回本模块前一 role version；gateway 回滚只能回仍带 dispatcher 的兼容版本。不能用模块日常发布静默暴露旧 handler。
- 回到未拆架构必须是显式整体迁移回退，不得成为模块发布选项。回退演练需验证另一模块和平台字节未变。
