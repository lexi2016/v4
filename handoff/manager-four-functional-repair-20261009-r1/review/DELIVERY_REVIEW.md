# 交付包独立后续审查

## 1. 结论与实际范围

**结论：该四文件补丁的交付、限定工具合同和来源说明通过本轮离线后续审查。最终业务回归为 57/57；独立 11 个工具边界场景达到预期。没有将这些结果升级为完整项目、Mac 集成或真实四功能恢复通过。**

本轮没有重新执行 57 项或全仓 pytest。我独立执行的是：4 个 before/after 与原输入的字节核对、20 R2 目标加 1 个无关文件的小树正反补丁、11 个包工具边界场景、写 audit 的人工合成边界探针。主控执行的最终 package runner 57 项、原/执行源码身份和完整回滚，由我读原始日志/receipt/JUnit 后再计算文件 SHA 核实。

交付工具初审发现过 **1 项 P2：写 audit 的宽泛预防保证不成立**。这一项没有被隐藏，也没有表述为“已封堵所有 FD 写入”。最终按实际任务收紧为**固定测试字节、隔离 execution copy/OUT、登记源码内容前后零差异验收，加有限的绝对路径写 audit 和网络阻止**。过度阻止合法 FD 的中间版本失败记录完整保留，详见第 4 节。最终没有仍需修改本次四文件业务补丁的 P0/P1/P2。

| 核查对象 | 最终身份 |
|---|---|
| 固定仓库输入 | `lexi2016/v4@74478a0e62be215c8527ccc9a14b89b51042d014` |
| R2 原 snapshot | `a7f5d09fb19de10564925757207977aadc080cc1`，与离线组装 Git HEAD 分开 |
| 交付目录 | `manager-four-functional-repair-20261009-r1` |
| `runtime.patch` SHA-256 | `2ed523c30a0cd9af75b770fbd5c6daaa5376190f6498508e804144d769377fac` |
| `source_manifest.json` SHA-256 | `43d432f5d8ff4158b379069f712eed4850f65c0d023aaa128742f44003ec7ea0` |
| 最终 `tools/verify_delivery.py` SHA-256 | `acd4d43b21362aa2e9cb166700279594275857ccc292c53addc21a2e950a0381` |
| 最终 `tools/run_regression.py` SHA-256 | `7b74d1bc790becf40e3b8b1b3ff8a084187864f8c40a2ec891e1a050c6ac9d80` |

`CHECKSUMS.json` 是文件库存校验，不是独立签名；最终 ZIP/commit 身份须由外层交付记录核对。独立反例使用最终工具的完整包复制件，初始库存 62 项（不含 CHECKSUMS 自身），未在主包制造损坏。加入本报告和收据后应重新生成库存并运行 verifier；这一步不要求再跑业务测试。

## 2. 补丁、源码字节与回滚

- 包内 **4 before** 的 SHA/bytes 与固定问题包原 R2 逐字节一致；**4 after** 与前轮已独立审查的候选一致。
- **16 unchanged** 均与固定 R2 和候选一致，允许目标集合恰为这 20 项且不重叠。
- **4 新测试** 与已独立复跑版本逐字节一致；**2 test support** 的实际 SHA 与 manifest 相符。
- 我在独立小树中放入 20 个 R2 原始目标及无关 sentinel。正向 `git apply --check` / `git apply` exit 0，只有 4 个约定文件改变，且均等于 after；反向 check/apply exit 0，**全部 21 文件字节恢复**。
- 主控的完整离线树正向变更也仅为同四文件。最终回滚 check/apply/verify-before 均 exit 0。我重新计算现存回滚树的 **1089 个文件 SHA**，与 `before_tree_sha256.json` 全部相等，新增/删除/变动均为空。
- 主控完整回滚的前后 file-map SHA 同为 `3f2354f3a918a6d8c729de47767beca37c89664dd978aecc08842649fad94dad`。这代表登记的离线源文件恢复，不代表 Mac release 身份。

本轮没有改 `four_gaps/app` 生产源码，也没有覆盖冻结的 `FINAL_REVIEW.md` / `receipt.json`。没有替换原公告 CLI、前端、部署入口、服务或真实 owner state。

## 3. 文档与来源核查

README、HOST_HANDOFF、ACCEPTANCE_MATRIX、source/support/provenance manifests 经主审重点复核和独立只读文档交叉核查：

| 事项 | 结果 |
|---|---|
| `66 输入 / 51 source snapshots` | 本地固定输入 bytes、SHA256、Git blob 均匹配；51 来自原 source manifest，code 下另有一个 `REFERENCE_ONLY.md`。没有将 66 文件或 1089 assembly 称为完整 Mac release。 |
| assembly 1089 项 | 路径和角色自洽；核对时只为四 runtime 应用明确 after SHA 映射。940 冻结仓库支持、123 先前 Mac baseline 同 SHA 依赖、20 R2 原目标及其它专用支持角色分开记录。 |
| 公告 support CLI | 实际 SHA 为 `aee0e5c31f30b296864a7ad81263fbc748b65cb9b4d443f83a756019cbc94a38`，42910 bytes。文档和 manifest 明确它是既往交付的 **test-only reference**，不同于本输入原 runner `bfb853fb982e0b2da1024fa942ae9dc5d67fa88a8d112f46054608641129c1ee`，也不是本次 Mac ops 部署身份。它不进 runtime patch，不写入传入源码根。 |
| CLI 模板 | 静态对照 aee CLI 的 argparse，capture、prepare、register-handoff、import、readback 均无未知参数或遗漏必填项。没有运行任何真实 CLI。 |
| 前端 | 运行前端改动为空；restoration SHA `2c02d4cff38d749fcad91b892da83029c8269287fbb867a2216f09ef8aa2c43f` 明确保留。旧 assembly TypeScript 不能覆盖 restoration；本轮不据 Python 测试声称 UI/validator 通过。 |
| 日期/历史/覆盖 | target/selection 10/09 与 publication/master session 10/08 分开；9/30 独立成功入口未定位不等于不存在；历史 partial、full_market_coverage=false、oversold volume provenance 缺口保留。 |
| 状态和测试计数 | 57=6+8+30+13；同 57 的复跑不重复累加；独立 10 另列；旧 HK 组两侧相同 16 失败；全项目两侧 collection error 均保留。 |

初读的两个说明问题已修正并复核：README 输出变量统一为 `V4_FOUR_ACCEPTANCE_DIR/regression`；原独立 receipt 因包内重命名造成的定位问题以 `review/RECEIPT_PATH_MAP.json` 解决。映射 **10 项**已逐字节核验，原 receipt 的全部 9 个 review_artifacts 均有包路径，原报告/receipt 保留原执行身份和原 SHA。24 个主文档内部链接已检查，末项 DELIVERY_REVIEW 为本次补充文件。

## 4. 工具 P2 的发现、失败试修与有限闭环

### 初始发现

初始 runner `3d61f11380e703786b0cb488fb8a911e5ada894f61dcb0c42c5fc4555ea00b3c` 的 audit 把相对路径按 cwd 解释，无法从 `open` audit 事件取得 `dir_fd`。在人工临时根中，绝对原路径写被阻止，但 `os.open('sentinel.txt', ..., dir_fd=original_fd)` 可以改变同一合成原文件。这个行为与广泛“防止源修改”的描述不相符，记录为 P2。探针未使用真实源码或 state。

### 中间试修不能作为最终修复

`bcf93dec4824b96baadc63ba3ea389db5d70d1396bd2deb1cdd24eabb093ae16` 一度拒绝所有无法解析的相对/FD 写。针对小 guard 探针确实能阻止原反例，但真实原 owner 在 OUT 工件目录合法使用 dir_fd mkdir 与 fdopen，导致主控 `regression-02`：**17 passed、19 failed、21 errors，exit 1**。原/执行源码内容均未改变。这个试修被放弃，失败日志和 receipt 保留；不能只展示小探针绿色来声称完成。

### 最终合同

最终 runner `7b74d1bc…` 明确声明：

```text
write_audit_scope = ABSOLUTE_PATHS_ONLY
descriptor_write_prevention = false
general_security_sandbox = false
```

固定包测试在隔离 source copy 上运行；原 source root 的登记文件和 execution copy 的登记文件在结束后逐项比较 SHA256 与 byte count，任何新增/缺失/变化令 runner FAIL。source_identity 明列排除的依赖/state目录。能明确定位的绝对源写入和真实 socket 连接仍阻止，模块路径/SHA 与执行文件追踪保留。**这属于内容验收及辅助 audit，不是一般文件系统安全沙箱；不保证任意相对路径、FD、原生扩展或其它进程不能写文件，也不把未列入源码清单的目录纳入零差异结论。**

独立最终有限合同探针验证：绝对原路径写被阻止、绝对 OUT 写可用、FD 操作按声明可用；在人工 source 中故意通过 FD 改内容后，源码差异函数准确报告 `changed=['sentinel.txt']`。它证明的是差异可被验收门槛发现，**不是 FD 写已被预防**。最终正常 57 项则由真实源内容零差异证据补齐。

P2 因不成立的宽泛保证被移除、最终行为与有限合同一致而闭环；没有通过修改业务源码、削弱业务验证器或改测试来获得绿色结果。

## 5. 独立 11 个包工具边界场景

全部使用最终工具和主包复制件；主包只读。每次命令前后核对传入的合成 source 与复制包，均没有由所运行命令造成的文件内容变化。人为反例改动只发生在命令开始前的专用 fixture，或第 4 节明确标记的 guard 能力探针。

| # | 场景 | 预期且实测 |
|---:|---|---|
| 1 | 有效包库存及 20 个 after/unchanged 目标 | verifier PASS，exit 0 |
| 2 | after payload 增加字节、库存不变 | PACKAGE_CHECKSUM_MISMATCH，exit 1 |
| 3 | source runtime SHA 漂移 | SOURCE_AFTER_MISMATCH，exit 1 |
| 4 | runner 接收 runtime SHA 漂移 | 测试前 FAIL，pytest 未启动，source 不写 |
| 5 | 16 unchanged 中的 router 漂移 | UNCHANGED_R2_SOURCE_MISMATCH，exit 1 |
| 6 | 目标变成指向相同字节的 symlink | SYMLINK_REJECTED，exit 1 |
| 7 | CHECKSUMS 路径含 `../` | UNSAFE_RELATIVE_PATH，exit 1 |
| 8 | 包中增加未登记文件 | PACKAGE_INVENTORY_SET_MISMATCH，exit 1 |
| 9 | OUT 放入 original source 内 | 输出开始前拒绝，exit 1，source 不写 |
| 10 | source 内非目标路径存在意外 symlink | runner 拒绝复制，pytest 未启动 |
| 11 | 只有合法 20 目标却缺 `ops` 等完整依赖 | worker 明确 `No module named 'ops'`、FAIL；pytest 未启动，没有借 ambient app 业务模块凑成功 |

这 **11 个工具场景不是新增业务测试数量**。它们不替代完整 source dependency gate；byte verifier 校验四目标与 16 preserved target，无法单独证明其余依赖齐备，第 11 项专门证明后续 worker 不会将缺依赖假装成功。

## 6. 主控最终包入口与回滚证据的独立读回

最终主控运行 `patch_validation/regression-03`，我没有再运行该 57 项：

- `pytest_exit_code=worker_exit_code=runner_exit_code=0`；JUnit 独立解析为 **tests 57、failures 0、errors 0、skipped 0**；原日志 `57 passed in 10.72s`。Starlette 弃用提示仍保留在日志，未隐藏。
- 原 source 清单 **1089**、execution 清单 **1093**（只叠加四新测试）；两者前后差异均为空。
- 我重新读取 execution 清单的 **1093 个文件 SHA/bytes**，均匹配；并核对 **218 条具备文件路径的加载模块记录**的实际 SHA/bytes。这是模块记录数量，不是唯一源码文件数量。
- `guard_events=[]`、`module_identity_errors=[]`、`business_namespace_shims=false`。`sys.path[0]` 是此次 execution source；公告 CLI 和 US helper 单列为 test-only 支持，SHA 正确。
- 回滚 receipt 的三个命令均 exit 0；当前完整回滚树 **1089 个文件**再哈希后与原 map 相等。

包内最终执行证据为 `evidence/packaged_runner_environment.json`、`packaged_runner_source_identity.json`、`packaged_runner_57.log`、`packaged_runner_57.xml`、`packaged_runner_command.json`、`patch_forward_receipt.json`、`patch_rollback_receipt.json`；中间失败保留在 `tooling_regression02_failure.json` 与 `tooling_regression02_failure_excerpt.log`。其中六份最终环境/源码清单/日志/JUnit/正反收据已与执行时 `four_gaps/patch_validation/` 原文件逐字节核对。独立读取与再哈希结果见 `delivery_parent_proof_review.json`。交付包仅保留 metadata、日志、JUnit 和清单，不打包临时 source/pytest state。

**全项目门禁仍未通过**：候选与精确 R2 离线对照都在 `tests/test_hk_expected_missing_recovery.py` 收集时缺 `HK_EXPECTED_MISSING_SOURCE_SHA256`，exit 1。没有扩修、没有全项目通过结论。此前独立 57 和 10 项业务回归继续保持原冻结报告的范围，不能与工具场景或重跑次数累加。

## 7. 证据文件与仍未执行的事项

本后续阶段新增：

- `delivery_static_byte_receipt.json` / `delivery_static_byte.rawlog`：独立 20+1 小树正反字节证据。
- `delivery_tool_probe_receipt.json` / `delivery_tool_probes.rawlog` / `delivery_tool_probes.py`：最终工具 11 场景。
- `delivery_guard_probe.py` / `.rawlog`：初始 P2 复现。
- `delivery_guard_probe_fixed.py` / `.rawlog`：被弃用的过度防护试修探针，不能冒充最终合同。
- `delivery_guard_contract_probe.py` / `.rawlog`：最终有限合同及内容差异检测。
- `delivery_docs_review_receipt.json`：文档与原证据路径映射复核。
- `delivery_parent_proof_review.json`：最终主控 receipt/JUnit 的读回与独立文件再哈希。
- `delivery_receipt.json`：本后续审查的机器清单与 SHA。

主文档最后小改动也已核对：README 的57/1089/11结果与原证据一致，HOST_HANDOFF取消了隔离可逆回滚的额外批准措辞；LOCAL发布读回属于后续发布记录，不作为本独立审查已执行的动作。

主控可将本报告复制为包内 `review/DELIVERY_REVIEW.md` 并刷新 CHECKSUMS。原冻结报告及 receipt 的 SHA 未改变：`c4d183eb04d250942dfb2e81150a3ec2728747e2cfbc94f7b7ff2c659c2f6db4` / `0933b0f5f6ebb6eb35c419de85eedb95951099d2071a0c900cbace0393ff9eec`。

**NOT_RUN / CANNOT_CONFIRM 保持：**真实 Mac owner 数据与进程、部署、live API/UI、自然时段、完整 Mac release 重建、全市场结果与 BUY。交付验收没有执行真实抓取、改变服务、写 GitHub 或修改真实 state。
