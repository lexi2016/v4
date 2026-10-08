# Issue #30：集成核心独立复跑与修订记录

## 交付身份

本目录仅处理发布集成核心。冻结候选是 `candidate/ops/api_release_integration.py`，SHA256 为 `0b9d3b678dc7e875b9514bd8b66b7e8fc69229759c366ef0df776126746180bf`，51,657 bytes。基线草稿 SHA256 为 `579bb0986404232bb497027705d9d7a0f18ee74ad663a44e8ce0befd0f9cb24a`。源码位于隔离工作目录，未写 Mac canonical 或实际运行目录。

输入包固定于 GitHub commit `a0a0b88dc133d14ee5763569272c174bcd7cc445`；本轮结束重核输入 9 个文件均未变化，见 `BASELINE_UNCHANGED.json`。基线作者声明的 canonical HEAD 不能代替这些逐文件 SHA，也不能代替现役 API 身份。

## 独立复跑结果

| 对象 | 结果 | 原始证据 |
|---|---|---|
| 原始交接文件，不补依赖 | collection ERROR：缺 `release_candidate_audit.py` | `bare_original18.json/.log/.xml` |
| 同一份原始两测试，补真实固定依赖 | 18 passed | `original18.json/.log/.xml` |
| 原草稿的 9 个隔离拒绝断言 | 9 failed，均为应拒绝却未拒绝，无 collection error | `adversarial_red.json/.log/.xml` |
| 第一版 v2 严格回归 | 34 passed / 1 failed；发现 build 在最后一次 delta 检查后才建立 candidate 快照 | `strict_first.json/.log/.xml` |
| 冻结 v2 核心回归 | 52 passed / 2 prepare 用例暂未选择 | `core_frozen.json/.log/.xml` |
| 冻结核心加主控已修 prepare | 54 passed，0 skipped，0 deselected | `core_full.json/.log/.xml` |

所有测试在 Linux `6.18.44-x86_64-with-glibc2.39`、Python `3.14.7`、pytest `9.1.1` 执行。解释器为 `/workspace/scratch/25c09a595aec/issue28/references/work/test-venv/bin/python`；完整 argv、cwd、退出码、时刻和文件身份在对应 JSON 中。测试禁用自动第三方 pytest 插件和字节码写入，使用明确 `--basetemp`。真实子进程只竞争临时目录中的发布锁，没有运行业务服务。

原始 18 个测试未被改写后冒充复跑通过。新的 v2 integration fixture 只迁移 base 指针绑定、mode 字段和 module scope；对应迁移身份见 `V2_TEST_MIGRATION.json`。9 个对抗测试的断言代码在 RED 与候选测试中相同，使用的 fixture 合同版本有明确变化。

原始草稿缺少的真实依赖来自已固定 GitHub 源码树与 Issue #28 已核字节，全部核对 Git blob SHA1、字节数和 SHA256，见 `SUPPORT_IDENTITY.json`。它们只支持原始 builder/lock 测试，不代表现役运行依赖。候选核心仅使用 Python 标准库，不再从 `sys.path` 导入未固定的 infrastructure 锁实现。

## 已复现的根因

1. `read_active_release` 从第一次读取的 plist 解析旧 release，却从第二次读取计算 SHA，可能返回“旧 release + 新 plist SHA”的混合身份。
2. build 与 verify 的最后一次 delta 校验之后没有完整复核。测试在该时点替换 active 指针、修改 candidate 非 delta 文件或替换同字节 candidate 根，旧 guard 仍返回 PASS。
3. base 只绑定 release 目录、manifest 和 app inventory，没有绑定构建时 active plist 的确切字节。只变数据根等配置但保持 release 身份时，旧 guard 无法要求重新集成。
4. receipt 只约束文件内容哈希，没有模块 ownership 或 before/after mode。测试把已列入 delta 的文件 chmod 为 `0777` 并重算自洽 candidate inventory，旧 guard 仍接受。
5. prepare 提前 `resolve`，吞掉传入 pointer alias；且 config 目录允许符号链接。隔离测试证实会把 staged plist/plan 写入 candidate 以外的临时目录。这两项修订由主控负责。

以上均来自合成临时目录及可重复的故障调度，不能表述为真实服务已经经历这些具体竞态。

## 核心修订合同

- integration 和 delta receipt 均升为 v2；旧 v1 integration 候选拒绝。已接受的 base release manifest 保持既有 `v4.release_candidate.v1`，因此不会要求历史已接受基线事后具有 v2 lineage。
- receipt 顶层、逐条 entry、base 与 module_scope 检查严格字段；JSON 重复键和非有限常量拒绝。SHA 必须是 64 位小写十六进制；mode 为四位八进制字符串，addition 的 before SHA/mode 为 null。
- base 在原七个 release 字段之外新增 `api_plist_path` 与 `api_plist_sha256`，base 模式核对完整记录；candidate 模式仍要求同一 pointer 路径，核对当前 candidate identity。
- 静态 ownership policy 与 hash 内置于核心字节。已核 preselection、manager、research_review 的有限路径可声明；共享 app/config/run 必须逐项声明，发布工具共享文件仅 api_platform 可声明。未知路径、未知 module、过期 policy hash、多余/遗漏 shared path 均拒绝。
- 文件按 before/after 内容与 mode 绑定，修改文件验证 unified diff SHA/hunk count；非 delta inventory 必须精确保留。允许显式、确实改变 mode 的同内容 delta，但不接受内容与 mode 均无变化的伪 delta。
- 从已验证 active inventory 复制条目，source 与 destination 使用逐祖先 `O_NOFOLLOW` 的 directory fd。delta 写入使用已核的 source bytes 和同一 destination parent fd，不再校验后重新调用 `copy2` 读取另一份 source 字节。candidate 与 active/source 根重叠先拒绝。
- 对目录根、文件 inode/元数据、manifest、receipt、inventory、active plist 做同次调用的快照与末尾复核；build 快照在最后一次 delta 检查之前建立，避免把检查后篡改当作基准。
- 共享锁由同一核心内的标准库 `fcntl` 实现，持久 lock inode 不 unlink、不按年龄回收。lease 必须为本进程、本线程、当前已注册对象，并核对 fd/inode/路径；verify 首尾都核锁。真实子进程测试验证持锁时拒绝竞争、释放后可以使用同一 inode 取得锁。

公开签名 `build_integrated_app`、`verify_api_release_candidate`、`shared_api_release_lock`、`assert_api_release_lock` 保留。新增 `module_scope(module, shared_paths=())` 生成政策绑定的 scope，新增 `verify_recorded_base(base_record)` 在不读取 active 指针的条件下核验记录中的旧 base，供受保护恢复使用。

## 验收范围与剩余边界

54/54 仅代表这份固定核心及固定 prepare 的隔离源码回归通过；本目录未完成独立第三方 review，主控正在另行组织。actual cutover 接线、builder 与 CLI 的回归由对应 owner 提供，不能从核心测试数推断它们通过。

保留非 delta symlink inventory 的历史语义：验证 link 文字与目标存在性，文件 mode 单独绑定；这不证明外部 symlink target 的实际内容。外部运行依赖仍需单独审计。delta 自身及其祖先不允许符号链接。

末尾快照复核不使之后任意文件系统操作具有原子性。正式发布者必须在同一个共享锁内、active 写入前重新验证。未迁移的旧脚本不会因为新增 guard 自动受保护，须由本机 owner 清点并停用其直接写入路径。

本轮没有读取真实 active release/plist，没有运行 launchctl，没有启停服务，没有修改业务状态或原始行情，没有部署，没有访问 API/UI，也没有自然时段验收。真实最新 R2 + 两处预选池修复的集成库存与业务 canary 仍待获授权本机阶段完成，保持 CANNOT_CONFIRM。`RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false` 边界不变。
