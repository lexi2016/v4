# PR14 R3 — 安全闭锁修正，HK共存执行仍阻断

固定输入 `e865206c492dcb7505e72892ebf430d7746488c8`。只改一个产品文件 `ops/_run_stage_center_nodes_parts/stage_dispatch.py`，另增一份公开入口合成回归。没有修改runner接口、A guard常量、行情、collector/provider、原数据、服务或市场架构；未生成真实批准、补跑、合并或部署。PR保持Draft，Issue保持Open。

## 已核事实

评论 https://github.com/lexi2016/v4/pull/14#issuecomment-5910047929 报告 Mac Python3.14.6 新测试10/10、exit0、REVIEWED_WITH_P2_CONTRACT_CONFLICT。机器JSON只有SHA，未取得原件；不称重读，不与旧58+1相加。独立回执SHA `a649908305eb37d50aada8e8e814f4ba30018904add0e32c579936a12f0a59b7`；Writer SHA `ef6c2db4b58c6ff6a63872362202ba2e76cf1ae59a359af36d6ac322716af680`。

原dispatch的A consumed marker先于HK判定return；带A授权的HK settled-partial之后又被非transient检查拒绝。新测试实际复现两条错误短路。

## 不能只挪return的接口限制

冻结 `StageCenterRunner._run_one(decision, *, historical_backfill=False, backfill_run_id=None)` 没有HK-only或preserve-A参数。`_runner_parts/slot_execution.py`第15行绑定整阶段markets，约306行遍历A/HK；已有A产物仅在身份匹配时复用。第624行的selection复用是正常路径；667行整阶段receipt写入及668—691行异常分支会重建全部lane_failures并替换共享receipt，不能保证A分支字节不变。`runner_receipts.py`也是共享date/stage receipt原子替换，不是独立市场receipt写接口。

共享node_attempt_count不是独立HK预算台账。A真实3+1消费后的4不能重置；“marker存在且旧partial receipt显示1”不能据此确认HK独立剩余两次。

本批在A短路之前识别该共存形态，返回 `CANNOT_CONFIRM / HK_RETRY_A_PRESERVATION_UNSUPPORTED`；跨日、未来时间或unsafe配置返回 `HK_COEXISTENCE_SCOPE_UNSAFE`。不调用runner、不授予或消费A额度、不写旧receipt/attempt/marker。`hk_recorded_remaining_attempts`仅是旧共享计数的读数，不是批准额度。双方耗尽保持拒绝。原A一次额外额度及第二次拒绝不变。

**这修正的是拒绝路径及保全合同，不是HK重试成功。HK共存业务缺口仍未关闭。** 按用户要求，不新增市场执行架构来绕过接口限制。

## 身份

- dispatch before：`955630c90ee8f7836597d8acf515eca2b2dcd240632823c6f552acfdafa76231`
- dispatch after：`4bde6fea8236f4112116fe79b8399a3002f78d00580f78fec40a006e3d28ae8d`
- node_entry保持：`e8707873a23284626f5af44aa7ede9b273e464f1d66bf79dd608099abf451dba`

只对已集成PR14的955630…前像应用。本patch不能直接套旧现场dcb478…或旧PR12版本，更不能两份叠加。collector/provider/slot_execution保留已验现场版本，不回装GitHub旧字节。

## 红绿证据

同一新增文件 `tests/test_pr14_ah_coexistence_contract.py`：RED 4 passed/7 failed/0 error/0 skipped、exit1；GREEN 11 passed/0 failed/0 error/0 skipped、exit0。

命令：`python -m pytest -o addopts='-W error' tests/test_pr14_ah_coexistence_contract.py -q --junitxml=<output>`。

覆盖公开run_nodes的授权并存、A-marker存在而HK记录仍有原预算、双方耗尽、共享receipt及原attempt/marker保全、跨日/未来/unsafe、A一次及第二次拒绝、code-SHA不符不授额。无私有sentinel植入。HK用例是“接口不满足时明确拒绝”，不冒称行为恢复。

全部输入/批准/加载身份/业务runner为合成替身；公开nodes/dispatch及文件审计/锁路径执行原实现。原日志及JUnit在可下载交付包，不补造原Mac机器JSON。未重跑旧10或58+1。作者载体的runner.py与冻结提交有未纳入产品差异，测试不执行真实runner业务；其冻结接口及slot_execution从GitHub独立核对。不是全1312文件或Mac运行环境等价认证。

## 205代码身份：保持阻断

固定证据 `a60fbd8c55aa1fad637d8706ceada0db251ffb97/.../candidate_205_metadata.json` 明确codes_list_exported=false。80f5…仅有PR12声明，未附生成它的原序数组。最新评论报告reader算得 `ed7370dd8a81ddc621d606c61b8df95095cdc2c9def7909ab8be5e02b214b073`；独立Reviewer未重算current/artifact/attempt。

reader strict路径直接 `tuple(artifact['codes'])`，legacy也保留原序；guard用同一紧凑UTF-8 JSON算法，没有排序。预期 `80f5a1c0bbed293b637d1a2bb25585de932ce5b235dd3ff0236fcb9a99d8eb69` 不改，不重排凑SHA，不要求current字节SHA、artifact canonical SHA和codes SHA相等。

最小缺件一次列清：生成80f5…的原始205有序数组及来源路径/run/绑定artifact；当前reader的原序数组与reader SHA、current/完整artifact各自相对路径及字节/canonical SHA、schema/digest_mode/run/commit；六个已知attempt路径对应SHA的独立重算摘要。行情/凭证及完整原件留Mac。没有预期数组原件即EXPECTED_CODES_PREIMAGE_UNAVAILABLE，不能猜。

只读步骤：在现有服务解释器下调用原read_candidate_input获取上述字段；list(candidate.codes)原序紧凑JSON计算SHA并输出数组到隔离审核目录。按原件分别复算current、artifact和六个attempt；取得两数组后比较首个不同索引/集合/顺序。若完整artifact canonical SHA确实相同且直接提取数组，不能把codes变化轻率归因排序；先追声明来源。不调用run_nodes、collector或publish。

## Work一次接续

在非活动worktree核前像、应用本patch；以当前服务解释器只跑新增11项（Mac使用原pytest配置），引用旧10/10回执、不累计。确认HK仍为接口阻断，再做上述一次只读身份核查。未独立审查本新组合、未部署、未验真实API/UI；不生成APPROVED、不真实补跑、不延长20260930授权、不重跑五个A阶段。

回退只对本批after在隔离目录检查并应用rollback.patch；不回退数据、不删consumed marker、不清预算。A1445_1500另留待诊断：原receipt/首拒因、raw/selection、归档source witness/cutoff、API读取根；不归因PR6/7，不借0925额度。撤回HK ZIP不重做，经理/F5不混入。
