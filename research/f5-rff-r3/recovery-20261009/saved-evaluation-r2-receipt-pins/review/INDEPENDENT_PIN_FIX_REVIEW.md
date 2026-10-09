# Issue #33 receipt 文件 SHA / 事件 SHA 修复独立复核

当前状态：`PASS_PIN_FIX_STATIC_WITH_AUTHOR_LOG_REVIEW`。

复核者：`/root/saved_eval_review`。本复核者未编写本次 contracts 修复或其回归测试；只读检查源码与元数据，报告本身是唯一由复核者修改的交付文件。

## 范围与证据

- 基线交付提交：`3764032a16f3cd9db88ec0d0ca122fd5d01c167b`。
- 基线 contracts 文件 SHA256：`35b9f88b8183f8980333bfe4e06f37b3ef3e2acbea7a0fc6904b1d130ef058b7`。
- 基线 contracts tests 文件 SHA256：`6d1f0c904caa36cdad219ac609c0a13077ac41796fcf4225b8e972dda1abf3a7`。
- 输入：`inputs/feedback/ISSUE33_SUPPLEMENT.json`、原始 start/terminal receipt 完整附件、独立本机 blocker receipt，以及 `before/candidate` 中的冻结源码/测试。
- 本次复核没有运行真实 `prepare` 或 evaluation，没有读取真实 scores、truth、labels、model 或 registry，没有重跑 PR #5 的旧测试。

复核者自行读取并 SHA256 计算两份原始 receipt 附件，所得结果与补充问题包一致：

| 身份 | Start receipt | Terminal receipt |
|---|---|---|
| 完整文件大小 | 1510 字节 | 897 字节 |
| 完整文件 SHA256 | `0292f37c00181b3447d0cda65f0b24096e9100ace35fb024ff5f579248e64a03` | `c8dc367a7acf7196c4951074759e8c8015c071d6c2d7e6cf8b3afd3bf01f6ca1` |
| JSON 事件字段 | `start_event_sha256` | `terminal_event_sha256` |
| 事件 SHA256 | `69a41b317075cfcb21c26133401e19b8af7a435185c87d5f4cf76f7b2e24d9af` | `5fe5704e4fb63a00e1802a14ba7e09f41985342a89e4f0c301793991b80ff0cf` |

原 terminal receipt 的 `start_receipt_sha256` 等于上表完整 start 文件 SHA；`previous_event_sha256` 等于 start 的事件 SHA。原始元数据链在这两个不同的身份层面均一致，没有证据表明这两份 receipt 已损坏。

## 已独立确认的根因

基线 `PINS["candidate_start"]` 和 `PINS["candidate_terminal"]` 误填上表的事件 SHA。`file_record` 实际对完整文件字节计算 SHA256，因此即使收到完好的原始 receipt 也必然拒绝。

复核者仅导入无执行副作用的基线 contracts，并对两份本地附件分别调用 `file_record(path, PINS[name])`，两者均复现 `BOUND_FILE_SHA_MISMATCH`。该窄复现没有调用 `prepare`，也没有沿 receipt 内路径读取任何其他工件。

错误常量同时被以下三个路径使用：

1. `prepare` 为 `candidate_start` / `candidate_terminal` 建立文件记录时的 `file_record` 校验；
2. `load_documents` 对 `metadata_files` 的 `PINS` 检查；
3. `_validate_frozen_dependencies` 对原始 metadata 路径与 SHA 的 `_require_reference` 检查。

因此只修 prepare 的调用现场或绕过 file SHA 校验均不足。应改正公共文件 pin，让三条路径继续使用同一完整文件身份，同时把事件身份明确放入独立常量与 JSON 字段校验。

基线合成测试的缺口也得到确认：`SyntheticPreparation.record_json` 将生成文件的当前 SHA 写入 `self.pins`，`active()` 再临时替换 `contracts.PINS`。这些测试验证生成元数据内部一致性，但不验证发布常量能绑定原始 receipt，故本机 142 个合成测试通过不能排除此 P1。

## 初审认可的最小修复边界

- 仅将两个 receipt 文件 pin 改为上表完整文件 SHA；不改原 receipt 字节。
- 独立保留两个事件 SHA，并校验 `start.start_event_sha256` 与 `terminal.terminal_event_sha256`。
- 保留原有 execution、route、run-spec SHA、input-binding SHA、source-code SHA、terminal → start 文件 SHA 的 receipt 链校验，以及 source / path / binding 守卫。
- 新回归必须直接使用发布常量与两份原始 receipt 元数据，不通过替换 `PINS` 消除真实身份差异。全生成 fixture 为适配独立事件常量而进行的显式合成配置，与上述发布常量回归应保持可区分。
- 不顺带重命名历史 schema。附件 start/terminal 原 schema 确为 `F5_FULL64_XENDCG_CANDIDATE_*_RECEIPT_V1`；terminal 原文件没有 `route_id` 字段，不能为此次 pin 修复强加不存在的字段。
- 不改变训练、预测、模型加载、truth 读取、评价指标、阈值、资源上限、旧 fit 额度、official registry 生命周期或 PR #5 accepted helper。

## 已核对的最终产品 delta

当前 contracts SHA256 为 `e41ab4b41c8386875b14515e34c7609e108db17b538ed43eebe7f76fc3394ba6`。复核者独立重新计算该 SHA，并逐项检查与 `before/candidate` 的差异：仅 `+11/-2`，由两个文件 pin 更正、一个说明注释、独立的 `CANDIDATE_EVENT_SHA256` 字典及两个事件字段检查组成。

- `src/rff_saved_eval_contracts.py:41`、`:42` 的 `PINS` 使用原始文件完整字节 SHA。
- `:57` 的独立字典保留原始 start / terminal 事件身份。
- `:381` 原 receipt 链条件及错误码逐字保留；`:388`、`:390` 分别新增 `ORIGINAL_START_EVENT_SHA_MISMATCH` 与 `ORIGINAL_TERMINAL_EVENT_SHA_MISMATCH`。
- `file_record`、`checked_read`、路径绑定、source 闭包、prepare / load 调用流程均未修改。两类身份经由原有认证路径共同校验，没有跳过文件校验的特例。

另外四个产品源文件与基线逐字相同：

| 文件 | SHA256 |
|---|---|
| `rff_saved_eval_frames.py` | `0931cf63d5f779d02025ce5e41ca984aa9541686709b58e2d2367782200e203b` |
| `rff_saved_eval_registration.py` | `e25f3312332547f71f9edab2b76a49e20921ca1fb3c29d0c0face7211fd03ce0` |
| `rff_saved_eval_worker.py` | `c015246b4b3a21bcb69a1745e41516a9c19f694bf923dfb39553a920a96dfdd8` |
| `run_rff_saved_evaluation.py` | `115f84e85777a3f002e01c441f62f0fe179adbac72e3c2ecdfaa91adbc5802ba` |

## 新回归的有效覆盖与界限

已逐项审读 `tests/test_rff_saved_eval_contracts.py`，当前 SHA256 为 `95b1baa54699bd6a791f03f67a9f1f54acc98866783c16db0077ef8b429db4b6`。新增 `FrozenReceiptPinsTest` 共 8 个 test 方法，内部有额外子例。复核者未运行这组或其他完整测试套件；以下执行结果来自独立读取并核对的作者日志。

测试 fixture 中两份 receipt 与反馈附件逐字一致，大小及 SHA 见前表；`ISSUE33_SUPPLEMENT.json` fixture 同样与输入逐字一致，7708 字节，SHA256 为 `fc5fe74dc5c36cb4bc254d043a2151da2402e4a3acb1a95323a56aa377cda704`。

正式 pin 回归直接使用发布 `PINS` 与 `CANDIDATE_EVENT_SHA256`，不替换这两个映射，并在每例结束核对对象身份与内容均未改变。它覆盖原始 receipt 文件认证、文件身份与事件身份分别固定、prepare / load 的 receipt 认证成功、receipt 字节变更被拒绝、事件字段错误被专门 guard 拒绝，以及原有 execution / route / run-spec / binding / source / terminal→start 文件身份 guard。

prepare / load 用例的周边 old binding、spec、seal、helper 等元数据不是本机原件；`OriginalReceiptPreparation` 仅为明确列出的临时路径设置合成替身，允许这些合成字节声明原有身份。两份 receipt 路径被明确排除在替身白名单之外，其 `file_record` / `checked_read` 始终执行实际字节校验；完整 dependency validator、路径与 reference 守卫及 prepare / load 实际控制流未被替换。fixture registry 是临时生成的合成文件。测试还禁止读取真实 registry、data/model 路径及导入 helper。

事件与旧链的语义错误用例在原始 receipt 字节已认证后，才修改解码对象的一个内存字段；这是专门检查语义 guard 可达性的故障注入，不代表变更后的 receipt 文件可以通过原文件 SHA。字节损坏拒绝另有独立用例。旧的全合成 fixture 只把生成事件值改为新固定事件常量，以满足新增约束；这与不替换正式 pin 的原始 receipt 回归保持区分。

已读取的日志：

| 日志 | 结果 | 日志 SHA256 |
|---|---|---|
| `analysis/formal_receipt_pins_red.log` | 基线运行 8 个方法失败；9 failures / 15 errors 为子例累计。包含原始文件 SHA 与错误事件 pin 不相等的直接证据。 | `edba53b7f6dafcf6dda885e9a2ae2a1792d824c38d196f7cc5dbd83ba4c04c31` |
| `analysis/formal_receipt_pins_green.log` | 修复后 8/8 通过 | `f3637426bc1be99cfc16e05ae1f0d41dd183b65f65d5043a0f4beb0c2cdd238b` |
| `analysis/contracts_module_green.log` | 新回归及保留 contracts 测试共 38/38 通过 | `59195a7f756dd76cf23ccec34b95a5a0902c1adeca1f81690519367cd96c10fb` |

## 限定结论

对上述精确 contracts 源 SHA 所代表的窄修复，已确认反馈 P1 的根因被修正，原文件身份与独立事件身份均被保留，未发现本次 delta 新增的确定 P0/P1。正式 pin 回归没有以修改发布常量来掩盖问题，所使用的真实 receipt 与合成周边元数据边界明确。

本报告不把合成周边元数据下的 prepare / load 通过当作本机真实 preparation PASS，也不构成 execution release、Mac/L04 或真实命中率提升结论。由于 source 字节变化，真实执行前仍须由本机主控按既有流程生成新的 spec / binding、提交相应独立验收并取得新 release；旧审批或旧 binding 不能直接授权新源。该后续流程未由本复核者执行。

实现者已确认上述产品与测试 SHA 封版。本报告完成该冻结版本的独立静态复核，并核对作者执行的 8/8 与 38/38 日志。最终全套合成测试及 CLI help 如由主控另行执行，应作为额外证据单列；它们不改变本报告的原始 receipt / 合成周边元数据范围，也不扩大为真实本机执行结论。
