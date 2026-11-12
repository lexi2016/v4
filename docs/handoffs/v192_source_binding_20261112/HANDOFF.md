本冻结已包含 R3 独审 P2 的一次兼容返修：缺省可选 manifest/receipt SHA 的旧有效非空 native 池，经原 reader 已验证共享三件套及精确 run/artifact/path 复用；存在的 SHA（包括 None）仍须精确相等。不写回旧缓存。旧失败冻结与原 manifest 在 `r3_review_failed/`；增量差异 `INCREMENTAL_REVIEW_R4.patch`、测试 `TEST_RESULTS_R4.json`。候选仍沿用同一未激活 R3 目录，当前身份只以 INACTIVE_CANDIDATES_R3.json 和新 FROZEN_HANDOFF.json 为准。

本批是原预选池链路的来源绑定修复，模型版本、公式、角色、评分、rows 与 BUY 门禁均未变。

源码工作树：`/Users/lexi/.codex/worktrees/v192-source-binding-20261112/v4_app`；分支 `codex/v192-source-binding-20261112`；基线 `57c381d120a45e0f61687bfac01f26efd350da5e`。业务源码唯一 Writer：`/root/v192_pool_writer`。待主控唯一独审；Writer 未提交、推送、部署、发布共享数据。

最终候选：`/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/v4-v192-source-binding-20261112-r3`。以 `INACTIVE_CANDIDATES_R3.json` 为唯一准备身份，R1/R2 均为本批未激活中间版，不得使用。Main 六文件、Stage 仅 owner 身份 config、原共享 package 两文件；完整库存匹配。新 main-control 复用旧 policy 限制和所有保护，更新新 Main/Stage reader 源身份及 Stage prepared plist SHA。API 8873 保持现役独立候选，原 reader SHA `3654d9dd77887714fefb9a938a00277e0ab8215fbebf367436a0a6710205e008` 已对新 source_id 元数据 fixture 通过兼容读取。

根因和修复：当前 selector 为 ARROW_BLOCKS 逻辑锚，旧 resolver 只认物理 Parquet，跳到旧代。恢复逻辑 reader，核同日 QFQ generation/输入/receipt/snapshot/selector SHA，坏逻辑来源明确失败不 fallback。wrapper 始终核实际输入 SHA 后复用。源码及现役各自的非空提前复用都加精确身份检查。共享 producer 沿原 SafeRootStore 的锁与 historical_backfill/expected_previous CAS；原 store 补 READY_EMPTY 同分支兼容。V192 SourceSpec.source_id 加完整 panel SHA，防不同 selector 的相同空 CSV 幂等碰撞；owner、role、源语义、CSV、oracle SHAs 不变，旧 run reader 仍兼容。

原生主池维护入口仅允许 D11/O12、D12/O13 的 A/a_d1_premarket_pool，完整原始 artifact/receipt/manifest SHA CAS。原 builder 新增已有合同允许的 source_manifest/receipt SHA。旧 native 缺这两项时，维护入口重验它明确引用的旧 shared run，逐项匹配新 shared receipt 的完整七字段 supersedes 和 native 的旧 run/artifact/path；按原存档、journal、提交 owner 恢复单池，其他 A/HK 池不动。正常 materialize 的不可覆盖规则保持。

验证汇总见 TEST_RESULTS.json、TEST_RESULTS_R3.json。已复用先前空状态兼容独审 PASS。本次分组通过：原 6 项逻辑输入/oracle/CAS/wrapper；旧 generation/date/int64 3 项；最终额外 3 项非空复用/native 维护/现役非空复用。实际 inactive Main 导入与源维护方法 AST 对照、库存完整性已通过。维护分支本身存在无关 `infrastructure.runtime_graph.notifications` 导入缺口，未改；源码 split body 用明确作用域独立加载，实际 Main registry 全模块导入另行 PASS。不是全库或自然时段验收。

独审范围：源码差异、RUNTIME_DELTA_R3.patch、source_id 同空 CSV 冲突、READY_EMPTY CAS、精确来源/非空复用、native 来源维护与旧原件保留、inactive Main/Stage/control 身份、以下两日恢复/激活操作。精确冻结在 FROZEN_HANDOFF.json。独审 receipt 应包含 `{"verdict":"REVIEWED/PASS","frozen_scope_sha256":"<FROZEN_HANDOFF.json SHA>"}`，只有真实独审完成才可写这两项。

独审通过后，主控按顺序执行（PANEL_PYTHON 必须使用已验证绝对路径 `/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python`）：

```sh
"$PANEL_PYTHON" -B /Users/lexi/Desktop/学习/agents调试/v192_source_binding_20261112/activate_reviewed_candidates.py --execute --review-file <真实独审receipt>
"$PANEL_PYTHON" -B /Users/lexi/Desktop/学习/agents调试/v192_source_binding_20261112/recover_v192_two_days.py --day 20261111 --execute --review-file <真实独审receipt>
"$PANEL_PYTHON" -B /Users/lexi/Desktop/学习/agents调试/v192_source_binding_20261112/recover_v192_two_days.py --day 20261112 --execute --review-file <真实独审receipt>
```

激活脚本默认只读，执行时 fresh plist/manifest/policy CAS；复用原 registry owner_state，只要有 RUNNING/VALIDATING 的活/未知 owner、健康子进程或 Stage 正运行就停止，不强杀。主控等待健康任务完成再执行。Main/Stage 协调卸载、原子 plists 替换、Stage/Main bootstrap，核 loaded identity/新 Main configured_policy/API healthz；任何半切失败按保存的原 plists 回退。API 不切换。

恢复脚本默认只读预检、仅两日固定源/完整 SHA。顺序一次运行原 oracle 日切片，observer 只记录本次已算 day 的标量并原样返回 role result；不重复计算原公式或全历史。共享发布成功才调用原 builder 与 native owner：D11 正常补缺；D12 走严格维护 CAS。若共享已完成而 native 后续失败，保留失败，核清状态后使用同命令加 `--native-only`，只复用已验共享 run 补 native，不重跑 oracle。脚本不自动改旧 preimage，不扫其他日期。

两日源精确身份见 SOURCE_IDENTITIES.json，native 原像见 `20261111_NATIVE_PREIMAGE.json`（MISSING）和 `20261112_NATIVE_PREIMAGE.json`（PRESENT），共享旧原像见 D12_EXPECTED_PREVIOUS.json。

CANNOT_CONFIRM / NOT_RUN：真实两日 source/native 发布、激活、新数据 API/UI、自然调度、完整源分支 scheduler facade、对比研究结论。主控恢复后才能核真实集合和原因；旧 D10 非空 31 与当前原公式不是同源对比。本修复不执行 D10 或全历史恢复。

清理：独审后确认无依赖，删除仅本批未激活 R1/R2 整套候选及本证据目录下 `pytest-*`、`shared_candidate` 临时 fixture；保留 R3、源码、patch、失败与 PASS 回执、两个原数据 run/旧 native 修订。不得删除其他聊天候选/现役/历史 release/worktree。同步由主控沿用户既有 lexi2016/v4 工作分支执行，source 根保持隔离，不合并或部署到 canonical。
