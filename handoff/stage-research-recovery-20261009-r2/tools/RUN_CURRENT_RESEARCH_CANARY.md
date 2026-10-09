# 当前研究 Canary 驱动

`run_current_research_canary.py` 为已经准备好的完整独立 Stage app 建立新输出目录，并可调用其中原有的 `build_production_config → StageCenterRunner.tick`。它使用现有选择器、采集路由、Raw/SelectionStore 和 owner writer。

## 使用条件

`--stage-app` 必须是经过 `prepare_canary.py` 准备的完整 app；包内 `after/stage` 只有变更文件，不能单独充当完整 app。`--package` 指向包含 `SOURCE_MAP.json`、`CURRENT_DAY_RESEARCH_PIN.json`、`after/stage` 的 R2 包。`--config` 是现有 tick JSON 配置；`--hk-input` 是四份原始输入所在目录。

每次调用的 `--output-root` 都必须尚不存在，且其父目录已存在。该目录不能位于 package、Stage app、原 HK 输入或原 shared data 树内。

```bash
python -B run_current_research_canary.py \
  --package /absolute/R2_PACKAGE \
  --stage-app /absolute/PREPARED_STAGE_APP \
  --config /absolute/current_tick_config.json \
  --hk-input /absolute/ORIGINAL_HK_INPUT \
  --output-root /absolute/NEW_PREPARATION \
  --stage-id STAGE_0930_0935
```

默认只准备配置和输入。执行时使用另一个尚不存在的输出目录，并加 `--execute`：

```bash
python -B run_current_research_canary.py \
  --package /absolute/R2_PACKAGE \
  --stage-app /absolute/PREPARED_STAGE_APP \
  --config /absolute/current_tick_config.json \
  --hk-input /absolute/ORIGINAL_HK_INPUT \
  --output-root /absolute/NEW_EXECUTION \
  --stage-id STAGE_0930_0935 \
  --execute
```

支持 `STAGE_0930_0935`、`STAGE_0935_0940`、`STAGE_0940_0945`、`STAGE_0945_1030`、`STAGE_1300_1315`、`STAGE_1445_1500`。日期来自固定 pin；评估时间取 app 原 `STAGE_BY_ID` 中对应阶段的 cutoff。

## 执行顺序与证据

创建输出目录前，工具检查 SOURCE_MAP 的 stage 后像与候选 app 中对应文件；候选 app 必须已经是 after SHA。四个原输入必须逐字节匹配包中固定 pin 的 SHA，pin 的日期、市场、研究标记和安全标志也必须通过。

若原配置的 `shared_data_root` 已指向候选 app 的 `upstreams/v3_shared_data`，它必须包含已核验 HQ 后像。若原配置使用另一个 shared root，工具先检查其 `scripts/live_acquisition/pytdx_hq.py` 命中该文件已接受的 before/after SHA，再复制完整依赖树到新目录的 `shared_data`，仅将副本的这个文件替换为包内 after。复制忽略 git、venv、node_modules 和常见 cache 目录。manifest 单独记录实际共享代码路径及 HQ SHA；这补充了原动态模块 loader 清理 `scripts.*` 后，owner 模块观察可能未列出该文件的范围。

原配置所有既有读取项都会保留，包括 `candidate_acquisition_root`、研究及晨间数据 roots 和 `python_path`。`python_path` 保留原词法 venv 路径。写出 roots 改到新目录，HK 研究输入指向新目录的 `hk_input`。配置副本权限为 `0600`；标准输出不展开配置值。

`--execute` 在新 Python 进程中导入指定 app 的原 runner，设 `CURRENT_DAY_RESEARCH_REPLAY`，调用原 `tick(..., historical_backfill=True, _skip_precapture=True)`。owner 因而写入其既有 backfill namespace；六分钟调用跳过 Stage8 pre-capture。实际 owner 写入时钟仍由原 writer 产生，阶段 cutoff 是回放评估时间。

## 输出与状态

| 文件/状态 | 含义 |
|---|---|
| `config.json` | 保留读取配置并分离输出后的配置副本。 |
| `hk_input/` | 四份逐字节复制的输入，以及包内固定 pin。 |
| `shared_data/` | 仅原 shared root 与候选 app shared root 不同时生成。 |
| `result.json` | `--execute` 时原 owner 返回的完整结果。 |
| `run_manifest.json` | source 路径/SHA、执行方式、原输入字节检查及实际输出位置。 |
| `PREPARED` | 已准备，没有调用行情采集；退出码 0。 |
| `RESEARCH_ROWS_WRITTEN` | HK 有选中结果，且已核对同一 owner 回执、不可变归档与 selection trio 的字节 SHA；退出码 0。 |
| `EXECUTED_NO_HK_SELECTION` | 原 owner 已执行，HK 没有选中结果；退出码 3。 |
| `PREFLIGHT_FAILED` | 门禁失败，输出目录尚未创建；退出码 3。 |
| `CANNOT_CONFIRM` | 准备或执行后的错误，保留新目录内已有证据；退出码 3。 |

读取执行结果时使用 `run_manifest.json.output_paths` 的实际 `raw_root`、`selection_root`、`receipt_root`、`owner_receipt`、`owner_history_receipt`。历史 backfill 会在基础输出 root 下再增加 run 子目录；API 应按这些实际路径与 `selection_run_id` 回读。工具不把基础目录中的空白状态当成运行结果。

所有工具与 owner 证据保持 `RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。文件与 pin 的校验只证明该包指定字节被使用；当前证券元数据仍不认证历史 Connect 成员资格、供应商身份或 PIT。

## 可重复的本地回归

测试构造合成 pin/包，调用真实文件读写和原 owner；仅共享 PyTDX 外部桥接使用模拟输入。它们检查准备模式、共享依赖复制与直接使用、哈希/日期错误在写出前失败、限制阶段、CLI 不泄漏配置、真实 owner 有行情与无行情分支。合成测试不能替代真实四文件与正式包的门禁。

在包目录运行：

```bash
python -B tools/run_checks.py --output /absolute/NEW_CHECK_OUTPUT --ui-runtime /absolute/EXISTING_WEB_RUNTIME
```

复制测试到其他位置后，可以显式给出测试依赖：

```bash
CANARY_TEST_PACKAGE=/absolute/R2_PACKAGE \
CANARY_TEST_STAGE_APP=/absolute/COMPLETE_STAGE_TEST_APP \
CANARY_TEST_DRIVER=/absolute/run_current_research_canary.py \
PYTHONDONTWRITEBYTECODE=1 \
python -m pytest -q /absolute/test_run_current_research_canary.py
```

测试会将完整 app 和 shared tree 复制到临时目录，不会调用真实市场数据服务。
