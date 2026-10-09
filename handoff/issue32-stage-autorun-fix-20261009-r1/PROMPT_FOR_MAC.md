# 给本机接手者：完成 Issue #32 的实际恢复

目标为 **20261009**，价格日与 HK Connect 资格日均为 **20261008**。先读本包 README、SOURCE_MANIFEST、TEST_RESULTS 和独立审查，再处理真实数据及候选。用户已授权本目标必要、可回退的本地研究服务发布；完成具体候选和独立验收后按已有授权衔接，不重复询问是否可以读源码或构建候选。

## 1. 核身份并按 owner 集成

当前报告的源码根如下，必须用接手时实际运行信息复核：

| Owner | 报告的根 |
|---|---|
| 预选 scheduler | `/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/20260929-manager-1555-pytdx-r1/app` |
| HK shared | `/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/20260923-hk02-owner-rebase-r2/app/upstreams/v3_shared_data` |
| Stage | `/Users/lexi/Desktop/学习/agents调试/V4_HK_STAGE_RECOVERY_20261003/issue23_runner_helper_r3/stage_r1_binding_candidate_r3/app` |
| canonical | `/Users/lexi/Desktop/学习/v4_app`，已有并行修改 |
| API | 读取 `/Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist`；报告 release 为 `manager-workbench-r1-mac-20261008-api-r2` |

在完整当前源码的隔离候选中应用对应 `patches/`，先检查 SOURCE_MANIFEST 的前像 SHA 和补丁适用性，再修改。不要直接改运行中的 release，也不要把 actual 的旧单文件覆盖 canonical 的拆分模块。shared master、scheduler ensure 和 executor 新参数属于同一组集成；旧 ensure 收到 `--prepare-exact-date` 会拒绝参数，不能混装。

保留本机其他会话工作树；记录源码字节，不能只记录 git HEAD。测试边界模块留在测试目录，不写入应用。先运行本包定向回归，再在本机当前完整依赖闭包复验。当前实际 facade/materializer 的 authoritative gate 合同必须先核实；新代码在缺少该合同且没有已验证 formal pair 时会明确拒绝成功，不能把这组源码不加适配地直接切入未知现役版本。源码目录、测试支持、应用候选和实际运行版本分别记录。

### 便携源码测试

使用本机已有 pytest 环境，在包根执行；这些命令只写测试临时目录。完整命令与历史失败见 TEST_RESULTS。

```bash
cd "$ISSUE32_PACKAGE"
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 \
  "$ISSUE32_TEST_PYTHON" -B -m pytest -q --confcutdir="$ISSUE32_PACKAGE"
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 \
  "$ISSUE32_TEST_PYTHON" -B -m pytest -q \
  evidence/independent_review/test_existing_capture_review.py \
  evidence/independent_review/test_scheduler_handoff_review.py \
  evidence/independent_review/test_local_hk_gate_review.py \
  evidence/independent_review/test_api_provenance_review.py
```

组合 API 回归复用固定 Issue #30 包，避免混用现役依赖：

```bash
"$ISSUE32_TEST_PYTHON" -B "$ISSUE32_PACKAGE/replay_api_regression.py" \
  --issue30-package "$ISSUE30_PACKAGE" \
  --output-root "$ISSUE32_NEW_API_TEST_ROOT" \
  --python "$ISSUE32_TEST_PYTHON"
```

预期 72；仅对一个旧例修正日期夹具，原包不变。

预期分别 150 和 17；测试源码选择变量 ISSUE32_HK_PREPARE_TREE、ISSUE32_SCHEDULER_SOURCE_ROOT、ISSUE32_API_SERVICE_SOURCE 应保持未设置，以运行交付后像。日历夹具只用于测试。

## 2. 找到合法的 10/8 原始输入

先只读核现役 shared store 的 `assets/hk_security_master/latest.json`、10/8 exact entry 与它指向的 artifact／manifest／receipt。不能只看 latest 的最大日期。沿既有 owner 和已有归档查找真正 10/8 采集的 master；记录原始 run、三件套 SHA、capture 日期、universe digest 和行覆盖。不要假定包中提供了一个真实归档目录。

若原 owner 有可验证的 10/8 历史 store，可使用已配对的新入口恢复。以下变量全部由本机当前配置解析；不是可以照抄的默认路径。先在隔离数据副本演练；正式恢复应在原 owner 无并发写入的受控窗口执行，保留目标索引的精确备份，不关闭无关服务：

```bash
cd "$ISSUE32_SCHEDULER_APP"
"$ISSUE32_SCHEDULER_PYTHON" -B -m ops.ensure_hk_security_master \
  --store-root "$ISSUE32_SHARED_STORE" \
  --universe-root "$ISSUE32_HK_UNIVERSE" \
  --shared-package-root "$ISSUE32_SHARED_PACKAGE" \
  --trade-date 20261008 \
  --futu-python "$ISSUE32_FUTU_PYTHON" \
  --reuse-only \
  --verified-source-store-root "$ISSUE32_VERIFIED_ORIGINAL_STORE"
```

`--reuse-only` 在这里不调用实时采集。恢复失败时保留失败原因；不手工造 entry、不重标旧 snapshot、不改 capture。没有真实来源时维持 HK BLOCKED。新 `--prepare-exact-date` 供原自动执行链使用：只对真实采集当天允许原 Futu 收集，10/9 对 10/8 缺失输入应明确报 `HK_SECURITY_MASTER_NEEDS_VERIFIED_SOURCE`。

然后通过原 HK panel 更新入口核 `through-date=20261008`，读回面板 manifest 与对应 SHA、日期覆盖。原评分入口由 executor 以 `--signal-date 20261008 --target-date 20261009` 调用；保留原 frozen 模型与 asset 验证。还需通过原 `ops.materialize_scheduled_preselection` 消费并生成本地 JSON／manifest／receipt。不能把 shared CSV 成功当作本地池成功，也不能把一个本地 SHA 填进上游来源字段。

## 3. 查清调度失败并验证真实重试

读取 10/8 17:30、18:00 原回执的 `workload_results`、exit code、模块、reason/stderr、failure_class、attempt/retry_after；脱敏保留失败层级。旧 `started_workload_ids=[]` 不足以判定未调用。需要当前 `executor_registry.py` facade、ledger、catalog 和原启动入口，具体清单见 MISSING_CURRENT_INPUTS。

使用原调度器的受支持入口产生新恢复尝试，核新回执 invoked／succeeded、`first_gate`、lane degradation、汇总结果及最终 failure_class。A 的有效池必须仍可独立消费；HK 未就绪不能掩盖成整体成功。不要删除或重置已保存的历史 settled slot，也不要修改旧 receipt 让状态看似通过。

## 4. API 复用原工具，生成新的最小 delta

Issue #30 的 app/router 和发布工具继续复用；本包 service 有局部日期合同变更，须使用本包 changeset 的 after SHA。`after/source/actual_api` 仅含本批三个业务文件，不是完整 app。

```bash
"$ISSUE32_API_PYTHON" -B "$ISSUE30_PACKAGE/after/ops/create_api_module_delta.py" \
  --active-api-plist /Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist \
  --after-root "$ISSUE32_PACKAGE/after/source/actual_api" \
  --change-set "$ISSUE32_PACKAGE/change_sets/preselection.json" \
  --output "$ISSUE32_NEW_EVIDENCE/preselection-delta.json"
```

当前 app 前像必须仍为 `90a2bf6390c6c0e219aa3d9bb22bc3b3630ecb2d447df494ae69425933424ed7`，router/service 的新增前提也需检查。若已变化，基于新的 active 制作最小集成并重新审查，不放宽哈希门禁。完整候选从当前 active 取非 delta 字节，核 manager 保留、完整库存及真实 calendar。继续使用 Issue #30 已修复工具、formal V4 release root 和已有保护入口；不直接执行旧 R2 plan，不重写发布框架。

在独立 API 候选上做真实来源只读 canary：10/9 A 37／186 的 SHA、来源角色和合并结果逐项核验，216 只是原始键数参考；确认 HK 空占位被隔离，真实合格 HK 可读取；分页不截断 Stage 全量输入。验证完整 app 启动以及 manager 公告、日期隔离、workspace 的联合行为。

## 5. Stage、部署与自然验收

Stage 实际 runner 是 facade，所附文件没有可执行 CLI。按真实 launch argv 找到既有入口；核其 helper、config、source root 和解释器，不编造 `python -m stage_center.runner` 参数。隔离 canary 使用真实 10/9 输入，独立 raw／selection／receipt 输出根，不改已结算 slot。若所选阶段需要尚未发生的 09:20／09:25 行情，不能预造未来采集或把 NOT_DUE 算成功。

核 Stage 的本地池 raw SHA、上游 run/trio SHA、100 唯一 HK 代码、精确日历日期与最终选择 run/artifact。有效筛选后的空选允许；输入拒绝、占位或缺结果 artifact 不允许。

完成独立审查后按已有授权发布必要研究服务，记录切换前后完整身份及回退方案。回退源码不能伪装成已回退业务数据；已生成新产物仍保留真实 provenance。若必须恢复某个索引，依据该原 owner 既有事务/备份协议逐项核验，不用本包做通用数据回写。

对实际 8873 检查以下只读接口，原响应留本机：

```bash
curl --fail --silent --show-error 'http://127.0.0.1:8873/api/v3/preselection-pools?date=20261009&limit=200&offset=0'
curl --fail --silent --show-error 'http://127.0.0.1:8873/api/v3/preselection-pools?date=20261009&limit=200&offset=200'
curl --fail --silent --show-error 'http://127.0.0.1:8873/api/v3/stage-center/selection?date=20261009&stage=STAGE_0925&limit=200'
```

按返回的 next_offset 继续翻页，核全量计数、source_digests、input_fingerprint 与同日期物理源一致；重载 UI，核经理页面。自然计划 09:15、09:25、09:35、09:40、09:45、10:30、13:15、15:00、15:50、15:55 各以实际自然 receipt 为准，包含实际加载代码版本、输入 run/SHA 和结果。手工补跑与自然结果分别报告。

最后逐项报告 SOURCE_TESTED、INDEPENDENT_REVIEWED、MAC_INTEGRATED、INPUT_READY、DEPLOYED、API_VERIFIED、UI_VERIFIED、NATURAL_VERIFIED；失败保留 FAIL／BLOCKED，未做保留 NOT_RUN。保持研究安全 flags 和 A/HK 分离，Vibe 8910 不变。
