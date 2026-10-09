# 实际验证、命令与保留失败

## 最终结果

| 检查 | 结果 | 对应证据 |
|---|---|---|
| 最终核心 Python | **43 passed, 1 既有 warning**, exit 0，9.00s | [log](evidence/final_core_python.log)、[receipt](evidence/final_core_python.json)、[JUnit](evidence/final_core_python.xml) |
| 前端相关用例 | **25 passed**, exit 0 | [log](evidence/final_web.log)、[receipt](evidence/final_web.json) |
| 独立定向兼容 Python | **174 passed, 1 failed**, exit 1，175 total | [log](independent_review/python_final_checks.log)、[receipt](independent_review/python_final_checks_receipt.json) |
| 独立边界探针 | **3 passed**, exit 0 | [log](independent_review/boundary_final_checks.log)、[receipt](independent_review/boundary_final_checks_receipt.json) |
| 独立前端复核 | **13 passed**, exit 0 | [log](independent_review/web_final_checks.log)、[receipt](independent_review/web_final_checks_receipt.json) |
| 未改基线同一失败复现 | **1 failed**, exit 1 | [log](independent_review/baseline_failure.log)、[receipt](independent_review/baseline_failure_receipt.json) |
| 三 profile 正向/回滚 | **PASS**，原始临时文件树完整恢复 | [receipt](evidence/final_patch_replay.json) |

核心 43 = 公告 20、美股 11、HK 12；它们已经包含于独立 174 passes。前端 25 = 新增 13、既有 dailyAutomation 12；独立前端 13 重复检查新增套件。3 个独立边界探针中美股探针与新 permanent 用例有覆盖重叠。不得累加这些数字。

最后公告原生字符串 guard 修改后，核心 43 已重跑，receipt 绑定最终全部 13 个运行/测试文件 SHA 和 source_manifest。此前根 43 结果保存在 `evidence/core_before_final_type_guard.*`，不能拿旧 receipt 代替最终身份。

## 范围与环境

全部业务验证为 isolated synthetic regression：使用 `TemporaryDirectory` 或独立 pytest 临时目录中的合成源、catalog、Reader/Reviewer、关系 registry 和主表。实际目标函数、owner、store、路由、持久化和消费 validator 均来自固定来源的真实源码。没有真实行情/公告/外部模型调用、共享 state 写入或真实 owner 运行。

环境：Linux 6.18.44 x86_64 glibc 2.39；Python 3.14.6、pytest 9.1.1、pandas 3.0.6、pyarrow 24.0.0、FastAPI 0.141.1、Starlette 1.6.0、httpx 0.28.1；Node v24.19.0、Vitest 4.1.10、Vite 7.3.6、Vue 3.5.40、TypeScript 5.9.3、jsdom 28.1.0。依赖来自已有测试环境，本轮未安装或修改依赖。[环境记录](evidence/test_environment.json)。

Python 使用原 `tests/r3_scoped_loader.py` 建立有限 namespace，再链接正常父包属性，避免范围外 eager initializer 引用未组装的 `ops.daily_materialize`。该辅助器不提供假业务实现。原始文件存在于固定远端其他源码快照，但本次没有扩大到整应用依赖闭包。因此上述结果不能等同于完整原生应用 import、完整服务启动或 Mac 原生验收。

前端使用既有依赖的测试用 symlink，未打包 node_modules。13 新增前端用例中有两项调用真实 Python HK reader 生成 DTO，再进入实际 TypeScript validator；其余覆盖严格 unknown、ready、旧 DTO 兼容及显示约束。jsdom 用例不能证明现役浏览器页面已经重载。

## 最终根命令（历史执行的确切路径）

```bash
PYTHONDONTWRITEBYTECODE=1 /workspace/scratch/a154a3323e32/test_env/bin/python \
  /workspace/scratch/21926b793c00/three_channel/tools/run_scoped_tests.py \
  --app-root /workspace/scratch/21926b793c00/three_channel/app \
  --junitxml /workspace/scratch/21926b793c00/three_channel/evidence/final_core_python.xml

(
cd /workspace/scratch/21926b793c00/three_channel/app/apps/web
V4_TEST_SOURCE_ROOT=/workspace/scratch/21926b793c00/three_channel/app \
V4_TEST_PYTHON=/workspace/scratch/a154a3323e32/test_env/bin/python \
PYTHONDONTWRITEBYTECODE=1 \
/opt/codex/runtimes/codex-primary-runtime/dependencies/node/bin/node \
  /workspace/scratch/a154a3323e32/candidate/apps/web/node_modules/vitest/vitest.mjs run \
  --config /workspace/scratch/21926b793c00/three_channel/tools/vitest.config.mjs \
  src/api/managerWorkspace.threeChannel.spec.ts \
  src/api/managerWorkspace.dailyAutomation.spec.ts
)

PYTHONDONTWRITEBYTECODE=1 /workspace/scratch/a154a3323e32/test_env/bin/python \
  /workspace/scratch/21926b793c00/three_channel/delivery/manager-three-channel-repair-20261009/tools/replay_delivery.py \
  --package /workspace/scratch/21926b793c00/three_channel/delivery/manager-three-channel-repair-20261009
```

确切 argv、cwd、环境、返回码和 source SHA 以链接的 JSON receipt 为准。本机可迁移命令见 [HOST_HANDOFF.md](HOST_HANDOFF.md)。独立 reviewer 的原始 runner 脚本记录云端绝对路径与审计捕获目录，用作证据而非可直接在 Mac 执行的安装脚本。

## 唯一保留的兼容测试失败

`tests/test_manager_announcement_parity_20261008.py::test_missing_original_archive_is_not_empty_connect_selection` 期望 `selection_diagnostics.status=READY`，实际为 `PARTIAL`，伴随公告与 US 输入未就绪缺口。reviewer 先逐文件核验 1,028 个未修改 baseline，再复现同一断言。最终候选同样失败。测试未改、未 skip/xfail；独立扩展 suite 不能标为全绿。

## 保留的 RED 与测试准备错误

- 公告：原 capture SHA 断裂和旧 readback 合同的 RED；空白身份 RED；独立缺失源身份 RED；数字身份转换仍通过的后续 RED。合法 legacy receipt 测试仍通过且保持原字节。
- 美股：未准备 daily mapping、晨间跨 slot 重放缺口、失败诊断、ImportError 隔离和 artifact/run 绑定的 RED 均保留。原 68-pass 结果在最终 artifact guard 之前，最终新增 11+独立探针 12-pass 日志单列。
- HK：原 12 项回归均为真实行为失败；初次兼容运行 46 pass/1 fail 是旧零计数断言，与新的显式 unknown 契约不符，随后只调整该契约断言。47 项定向组合通过。
- 测试准备错误也保留：范围外原生 import 缺依赖、namespace 父属性未链接、pytest 保留参数名、跨通道合成 registry 缺失、测试 helper bootstrap 次序、前端 read_context/as_of fixture 不一致。它们不是业务故障证明；修正 fixture/命令后才判断有效 RED/GREEN。
- 独立包审计另发现交接前端命令未指定 cwd，从包目录运行时 0 项收集且报找不到模块。原失败保留为 `independent_review/package_host_web_initial_failure.log`；命令现在用子 shell 显式进入临时副本 `apps/web`。修正 cwd 的同字节副本已得到 25 pass，完整最终流程记录见 [PACKAGE_AUDIT.md](independent_review/PACKAGE_AUDIT.md)。

通道逐次命令/退出码/完整日志见 [announcement](announcement)、[us_mapping](us_mapping)、[hk_screen](hk_screen)、[web](web)。独立审查 [FINAL_REVIEW.md](independent_review/FINAL_REVIEW.md) 对最终身份、红测和结果作了单独核对。

## 未运行

Mac 本地、完整原生 import、全量 typecheck/build、全仓 suite、真实外部 Reader/Reviewer/行情/导入、现役 API/UI 重载读回、服务发布/重启、调度/绑定修改、共享业务状态写入及自然时段验收均为 `NOT_RUN`。上述未运行项不影响本包对合成候选验证的准确记录，但不能被自动转换为现役通过。
