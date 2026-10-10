# Issue #30 — 8873 同一服务内的业务模块发布候选

**交付状态：隔离实现与测试可供复核；真实 Mac 发布验收尚未完成。没有部署、启停服务或修改 owner 数据。**

本包对应 [lexi2016/v4#30](https://github.com/lexi2016/v4/issues/30)，输入固定为 `f615f4edcf4eb57aa6cf9ab407f2c2c2ed329a9b` 的问题包，历史原生 publisher 参考来自 `a0a0b88dc133d14ee5763569272c174bcd7cc445`。原问题包的 114 份源码快照和全部校验材料随 `input/` 保留。

## 本次真正实现的行为

在现有 `build_release_candidate.py → api_release_integration.py → prepare_api_only_cutover.py` 链中增加业务 `module_id`，仍使用 gateway / `com.lexi.v35.api-only` / `127.0.0.1:8873`。模块发布继续构建完整 app 快照，但只应用经批准 owner 契约允许的精确文件 delta；其余内容来自锁内重新核验的当前 active。

- **A 后 B 累积保留，反序也成立。** 同一个 G 上构建的第二个候选，在 A 发布后被拒绝；必须用当前 G' 重建，不能悄悄覆盖 A。
- **回滚 A 从当前 active 生成 A 的 reverse delta。** B 的最新源文件、shared/config/static bytes 保持；A 当次新增的文件可反向删除。若 A 后来再次更新、后续模块依赖 A、目标不在祖先链或任一证据过期，则拒绝。
- **业务 owner 权威在 active LaunchAgent 的外部 SHA 绑定中。** delta 不能自行选择或批准自己的 owner 契约。精确文件归属、重复/重叠路径、共享文件、路由冲突、依赖环、基线及 generation 都有检查。
- **写入边界覆盖候选、成功/失败 receipt、回滚材料和 staged config。** 保护当前及全部保留的历史 release、两种 plist 环境定义中的已绑定绝对路径，以及契约显式列明的外部数据根；拒绝 symlink/alias 越界。
- **历史真实切换脚本的调用点已补保护。** 复用同一跨进程 lease，在 bootout 前、原子替换前和候选 readback 时调用共用校验；公开整包旧回滚入口拒绝，改走 reverse-delta 候选。五个保护依赖固定 SHA，47 个原历史部署常量保持不变。

这里没有建立第二个 publisher、服务或端口。Stage、Vibe、BUY/交易门禁、业务路由实现和 owner state 均没有修改。

## 验证结果和它的含义

最终环境为全新 Python 3.14.6 venv，19 个已安装测试依赖均与输入 `uv.lock` 精确一致，依赖检查通过。实际执行：

```bash
python -m pytest -q -p no:cacheprovider
```

**106 passed，0 failed，6.35 秒。** 其中原有 20 项断言保留，新增业务模块用例 65 项、原生入口隔离用例 21 项。完整命令、时间、平台、退出码在 `logs/final-locked-suite-r2.json`，输出在同名 `.log`。早期 RED、中间失败和环境修正均保留；不要把旧文件名中的 green/final 当作成功判据，应读取其 exit code。

独立 Reviewer 与实现者不同。审查实际发现并复现了 4 个 P1 输出边界问题及 1 个 P2 共享路径契约问题，均经修复和重新验证；详见 `review/independent_review.md` 与复现证据。测试通过证明上述隔离机制的当前实现，不能转换为 live 发布批准。

## 必须保留的未完成项

1. **当前 Mac 原生 publisher 与最终 immutable release staging 入口：`CANNOT_CONFIRM`。** 修改的是任务指定历史真实入口的参考副本；它的旧 release/审核/路径 pins 没有伪装成新现场绑定，不能直接拿去执行正式 switch。
2. **真实业务 owner、完整 route/dependency/state 兼容闭包：`CANNOT_CONFIRM`。** 五个中文工作区目录没有被臆测映射到 module_id。唯一启用的 alpha/beta owner 属于合成测试。`examples/` 中的真实契约模板保持 `PROPOSED`。
3. **共享/前端独立构建：本候选拒绝。** `app.py`、router registry、整个 `apps/web/`（含 dist/HTML/Vite 输入）、公共 contracts/config 等都不能由单模块修改。已批准联合集成的执行流程不在本候选中实现；这部分仍需真实 owner 和构建输出图证据。
4. **失败恢复矩阵：部分闭环。** 可辨认候选上的指定替换、bootstrap 和健康失败，在隔离 native fixture 中恢复立即前像。`LOADED_UNVERIFIED`（已加载但未运行/身份不足）分支保守返回 `ROLLBACK_INCOMPLETE`，不能宣称旧版本已恢复健康，也不满足完整服务连续性验收。
5. **Mac/API/UI/natural/live：均未运行。** 文件系统大小写/Unicode 行为、真实 launcher、真实路由健康、真实 state 兼容和动态消费者闭包仍需现场证据。

这些限制意味着 **Issue #30 不应关闭，也不应标记为“所有模块已经独立发布完成”**。下一步所需最窄证据见 `docs/MAC_EVIDENCE_REQUEST.md`。

## 包内导航

| 路径 | 内容 |
| --- | --- |
| `full-after/` | 可复核的完整源码闭包：26 个文件，含必要且未改的依赖和原有测试；不是可直接启动的完整 V4 app |
| `before/` | 精确的 23 文件开发基线；来源是所供已复制/部分脱敏的快照 |
| `runtime.patch` | 现有构建/校验/计划代码、新 owner 策略与业务测试的前向变更 |
| `native-reference.patch` | 历史原生 publisher 参考及其隔离测试的前向变更 |
| `reverse.patch` | 一次撤销以上两组源码变更，恢复包内 before 的完整反向补丁；不是服务整包回滚命令 |
| `CODE_SHA256.json` | before/after 每文件 SHA、大小、修改类型与来源 |
| `evidence/` | 实际合成运行的 candidate manifests、base/delta/rollback receipts、完整 inventory 和保留性判据 |
| `logs/` | RED→GREEN、独立复核与最终完整测试收据 |
| `review/` | 独立审查、owner/publisher/外部绑定审计和实际复现结果 |
| `docs/` | 架构、验收矩阵、使用/回滚步骤、现场证据请求与执行记录 |
| `tools/verify_delivery.py` | 校验所有交付字节，前向补丁应用后逐文件比对，再用反向补丁恢复 |
| `tools/generate_synthetic_evidence.py` | 重新生成独立临时场景；不触碰真实服务 |

## 先做离线复核

```bash
python3 tools/verify_delivery.py
```

测试环境按照 `docs/USAGE_AND_ROLLBACK.md` 在隔离位置建立，然后在 `full-after/` 运行完整 pytest。所有补丁必须先在 **包内 before** 或逐字节匹配的独立副本上核验，禁止强行应用到现场。

输入说明写“10 份/89 处”，但当前保留清单实际列出 6 份/82 处本机路径脱敏；这项描述计数差异已单独记录，逐文件 SHA 校验通过。`copied_sha256` 是本包实际前像，`source_sha256` 是输入记录的原 Mac 前像；两者不能混用。详情见 `docs/PROVENANCE.md`。安全状态始终为 `RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。
