# 可复现测试、准确环境与已知未通过项

## 本轮真实环境

- 平台：Linux；解释器 CPython 3.12.14。
- 解释器：`/workspace/scratch/0e089a11ee60/four_function_gaps/runtime_locked/bin/python`。
- 项目声明：Python `>=3.14`。未伪装版本，原入口 `PYTHON_314_REQUIRED` 保留为 1 项 FAIL。
- 依赖：与冻结 `uv.lock` 一致的 31 项版本，详见 `evidence/environment/runtime_locked_identity.json` 和 `test_locked_requirements.txt`。先前重复 dist-info 的临时环境未作为最终测试环境；最终使用新建的 runtime_locked。
- 所有最终 pytest 进程使用 `PYTHONDONTWRITEBYTECODE=1`、`-B`、`-p no:cacheprovider`，每组/每树独立新 basetemp。
- 源码根：`/workspace/scratch/0e089a11ee60/four_function_gaps/work/{baseline,repaired}/app`。

## 实际执行的准确命令

每次 pytest 的完整 argv、cwd、时间、exit code、test SHA、失败 node 和 log/XML SHA 已保存在 `evidence/final/{baseline,repaired}/<group>.json`。运行方式为：

```bash
PYTHONDONTWRITEBYTECODE=1 \
/workspace/scratch/0e089a11ee60/four_function_gaps/runtime_locked/bin/python -B -m pytest \
  -q --tb=short --color=no -p no:cacheprovider \
  --basetemp=/workspace/scratch/0e089a11ee60/four_function_gaps/work/verification/repaired/app_wiring_tmp \
  --junitxml=/workspace/scratch/0e089a11ee60/four_function_gaps/work/verification/repaired/app_wiring.xml \
  tests/test_manager_app_announcement_chain_20261009.py \
  tests/test_manager_hk_authority_app_wiring_20261009.py \
  tests/test_manager_app_plan_identity_20261009.py
```

以上 cwd 是候选 app root；baseline 使用独立 baseline 路径，不能把一棵树的模块缓存复用到另一棵树。重跑应换新的 basetemp，保留原日志。

Mac 在已核验的新完整源码副本中，使用其正式 Python 3.14 与已锁依赖运行同样三个相对测试文件。该 Mac 命令本轮为 NOT_RUN。测试期望是业务真实函数处理明确合成的原 owner 工件；测试中的人工时钟、证券代码、capture/Reader/Reviewer identity 不可复制到业务 state。

### 四组测试文件

| 组 | 文件 |
|---|---|
| app_wiring，20 项（12 create_app + 8 native consumer） | 三个本轮新增 `test_manager_app_announcement_chain_20261009.py`、`test_manager_hk_authority_app_wiring_20261009.py`、`test_manager_app_plan_identity_20261009.py` |
| adjacent_owner_contracts，113 项 | `test_manager_three_channel_hk_reader.py`、`test_manager_daily_channels_20261008.py`、`test_manager_workspace_exact_page_binding_20261008.py`、`test_manager_workspace_owner_20261008.py`、`test_manager_daily_dispatch_20261008.py`、`test_manager_daily_automation_20261008.py`、`test_manager_input_contracts_20261008.py` |
| supplied_regressions，103 项 | `test_issue8_selection_gaps.py`、`test_manager_announcement_date_catalog.py`、`test_manager_announcement_supervisor.py`、`test_manager_plan_readback_issue24.py` |
| existing_announcement，59 项 | `test_manager_announcement_parity_20261008.py`、`test_manager_announcement_handoff_20261009.py` |

包内另有两个被原测试导入的 US mapping fixture 模块；它们的整文件测试未另外计入 295 项。所有复制的原测试保持原 SHA，不覆盖它们的旧 fixture 以求全绿。

新增公告测试复用原 handoff source_lane；HK 测试复用原 HK master/panel fixture。计划七项测试自包含，不依赖上传 ZIP 或审查目录。运行完整 app 仍需要原项目依赖，本包不宣称只有两份源码即可独立启动整个 API。

## 测试支撑与生产补丁分开

请求包只含 51 份源码快照，其中 20 份控制本轮 R2 前像，不能独立构成完整发布。为运行实际 create_app，隔离环境从冻结父 commit 逐 blob 取回已有依赖；来源见 `support_provenance.json`。

还发生了以下已记录的支撑对齐：

1. 使用原 `ops/daily_materialize.py`，补齐 import 闭包。
2. 将冻结 Git 中原有的 527 字节通用 namespace helper 逐字节放入 30 个遗漏的 fragment helper 路径。原 SHA 是 `45da791482883c7c371268a99056960c577f299b43a5629394b3178fbea9f8b1`，路径清单见 `import_support_adaptation.json`。
3. 使用已确认的 API review_router（接受 hk_close_root）、API research_attention、原 package initializer，以及 API announcement_observation（保留原 positive_observations 投影）。四项前后 SHA、Git 路径和 blob 在 `api_support_alignment.json`。

这些不是本轮生产改动，不包含在 `runtime.patch`、`after/` 或应用步骤。它们不能证明现役采用同一完整组合，也不能覆盖 Mac 已确认的其它支撑版本。`apps/__init__.py` 没有已确认的原字节，未伪造空文件；13 项 supervisor 的目标 binding 断言因此仍 NOT_RUN，原 pytest 结果是 FAIL。

## 不隐去失败

最终合计为候选 268 PASS / 27 FAIL，基线 265 PASS / 30 FAIL。27 项逐类与逐 node 解释见 `RESULTS_AND_BOUNDARIES.md`、`review/baseline_triage/TRIAGE_REPORT.md`；不能将“没有新增失败”写成“全部通过”。最初 55/48、对齐后 76/27 等支撑诊断日志，以及最终 78/25 原 103 项日志，均保留为不同环境阶段，不相互覆盖或混算。

`evidence/initial/LOG_INDEX.json` 记录初始原日志 SHA/bytes。较大的一个导入失败日志只附带明确标记的 tail 摘录，完整原日志仍在本轮工作目录，不能把摘录称为完整日志。最终四组完整 raw logs 均在 `evidence/final`。

独立 reviewer 额外 5 PASS / 2 FAIL 的跨 cutoff 探针和 4 PASS 的语义分类不重复计入主统计。历史 baseline triage 的诊断脚本含“当时 canonical support 缺 positive 字段”的断言，不应在最终 API support 上整文件当正式回归重跑。

### 历史 CLI 命令字段勘误

原 `review/announcement/reference_readback_compatibility_result.json` 的 command 使用相对简称 `runtime_locked/...`、`review/...`，但其 cwd 是 baseline app；按字面拼接不能复执行。该原记录保留，没有改写其历史字段。终审后已用绝对 argv 在最终 API 支撑上重新运行，仍得到旧 CLI 的预期 handoff-binding 错误、新 CLI 的 OWNER_READBACK_VERIFIED、GET 字节不变。准确新记录为 `reference_readback_compatibility_final.json`，不计入 295 项。

可复现的原工作区命令（cwd 为 baseline app）是：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:tests \
  /workspace/scratch/0e089a11ee60/four_function_gaps/runtime_locked/bin/python -B \
  /workspace/scratch/0e089a11ee60/four_function_gaps/review/announcement/reference_readback_compatibility.py
```

此历史对比脚本还依赖原上传请求中的 `input/package/code/actual_owner_runner_20261009/ops/run_manager_daily_announcement.py`。包内审查副本是证据源码，不是可脱离原请求目录直接运行的入口；Mac 日常验收应使用实际已绑定的原 CLI，不执行该历史比较脚本。

本轮没有执行完整仓库测试、真实公告/行情任务、Mac 运行/部署、8873 UI 或自然时段验收。没有用离线绿灯替代它们。
