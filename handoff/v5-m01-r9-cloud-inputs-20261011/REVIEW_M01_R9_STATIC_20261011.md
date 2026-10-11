# M01 R9 实物增量审查、云端复现重点与明确返修范围

## 结论

R9 不能接纳。新增日期正则错误会拒绝所有正常 YYYYMMDD，连自带 test_ok 的 20261011 也无法通过；同时 FileNotFoundError 捕获范围实际没改、relative 仅做 identity 子串检查，root/source 安全边界仍完全缺少。

保留真实已修的全 11 字段 identity、existing 与本次 b 比较、真正 bool strict、四 SHA、磁盘独立验证及 require_absent；不要重新从这些问题开始讨论。新增 JSON 解码错误包装与绝对路径外形检查可保留，但它们不能代替完整 parser/root 边界。

本轮仅静态核验：未 import/执行候选、未运行测试、未改产品、未操作 Mac、未向原 Chat/GitHub 外发。云端真实测试由父任务另行创建，结果尚未发生，不能写入本报告。

## 1. 实物身份与范围

- 父任务已核实：2026-10-11 02:25:27 原 Chat 的反馈消息 41aeaded 已发；02:25:55 作者回复 b84a87cd-1ee3-4116-b127-c2c144232951 交 R9。此通信事实来自父任务，本审查没有重发。
- 文件名：V5_M01_A_SOURCE_R9_CANDIDATE.zip
- Library ID：libfile_2a803101b5b481919122537e31a087d2
- file_id：file_00000000a458820c88844c3a1fdecc56
- 本地 ZIP：/workspace/shared/m01_r9_static_review/V5_M01_A_SOURCE_R9_CANDIDATE.zip
- 5,481 bytes；SHA256 48a0d8aa99ef710003aa7c09e5330e6e9ffa99af001c0302ec63079ae60f5d48，与作者值一致。
- 6 个普通文件，11,284 解压 bytes；无不安全 ZIP 成员，CRC 通过；SHA256.txt 五项全部匹配。
- runtime.patch hunk 与两份 after 字节一致，AST 解析通过。不等于 import、运行、补丁实际应用或 pytest 通过。
- 两 patch 同为 ABSENT→新文件正向补丁；reverse.patch 与 runtime.patch 同字节。回滚可明确使用 git apply -R runtime.patch；本轮未执行，不把 R6 的实机往返证据转给 R9。

源码 after：
- V5/src/v5_shadow/a_source_daily.py，2,776 bytes，46 行
- SHA256 6ee3796c9a75b95d431e2dccb3fe67e0c561481af58204ea89f0856faeae9676
- Git blob 172617820a5be63542550953db675f4fb9ecfe36

测试 after：
- V5/tests/test_a_source_daily.py，511 bytes，8 行
- SHA256 311f239fea1d81bfa742003bf8a425e563a283bfab1987a2eac424f0a816a0c3
- Git blob f7edb7b2198373face1983abc5f263d02f21b677

runtime.patch / reverse.patch：
- 各 3,733 bytes
- SHA256 2e338fc786d595d1771b49b4f1fede4e5e09999702dcd6cbdeb8e14fb80bed8c

静态证据：
- /workspace/shared/m01_r9_static_review/ZIP_VERIFICATION.json
- /workspace/shared/m01_r9_static_review/STATIC_CHECK_RESULTS.json
- 解包根：/workspace/shared/m01_r9_static_review/unpacked/V5_M01_A_SOURCE_R9_CANDIDATE/

## 2. 第一阻断：project 的日期正则写错

R9 a_source_daily.py:17 原样是：

    re.fullmatch(r"\\d{8}", r["target_date"])

raw string 中两条反斜线使正则把反斜线本身当成字面量，然后匹配重复的 d；它不是八位数字匹配。20261011 不会匹配。AST 读取的 source_literal 也确认源文件确为双反斜线，不是展示层转义造成的误读。

所以：
- 自带 tests:5 的 test_ok 在正确导入后会因 M01BindingError("date") 而失败。
- 原 read_formula_generation 在给定合法 expected_target_date 时返回正常数字日期，create_binding :36 / read_and_verify :32 都会被 project 拒绝。
- 这是确定的静态控制流结论，本轮尚无 pytest exit code。
- strict=1 测试在 :14 先拒绝，因而它通过也不能证明日期路径正常。
- 不能据未执行结果报“1 passed / 1 failed”；由另一个云端任务实际记录。

最小修法：用清楚的 [0-9]{8} 形状校验，加真实日历日期校验；不要只换正则后继续允许 20260230 等不存在日期。这个 validator 同时服务请求参数、reader 投影、磁盘 parser，避免只把错误移到另一个入口。

## 3. 第二阻断：捕获仍覆盖完整原 reader，而非 raw bytes

R9 :40–41：

    try: old=read_and_verify_binding(private_root,rel,reader)
    except FileNotFoundError: old=None

read_and_verify_binding 内：
- :30 读目标 binding bytes；
- :31 解析；
- :32 调来源 reader；
- :33 比较。

虽然 :30 把 raw bytes 独立写成一行，外层 try 的范围仍是整个函数。来源 reader 的 FileNotFoundError 一样会被视为目标 binding 缺失并进入 :45 写入。不得把“raw 是单独变量”描述成捕获边界已修。

保留 require_absent 后旧 bytes 通常不会被覆盖，但错误原因仍可能被 FileExistsError 遮蔽。原 reader 的 stat/open/receipt read 窄窗口会真实产生 FileNotFoundError；其位置已在固定原 formula_generation.py:141、:157、:318 核实。

必须改的函数范围：
- create_binding：try/except 只包含 private_root.read_bytes(rel,max_bytes=65536)。
- 新增或抽出 _verify_binding_bytes：接受已经取得的 raw，完成 parse、严格位置/source 校验、原 reader 与投影比较，不吞 reader 异常。
- read_and_verify_binding：读 bytes 后调用同一验证 helper。
- 已有 bytes 的 parse/reader 出错绝不走 write。
- 只有目标文件确实不存在才 require_absent 新写；新写后在同一锁域独立读回并对本次 b。
- R9 :46 又将最后读回移到锁外，R8 :100 已在锁内；请恢复而非反复改动已修锁域。

不要在完整 read_and_verify 外再换一种 except 形式；必须改变被保护语句的边界。

## 4. 第三阻断：identity 子串存在并非精确 binding 路径

R9 :33：

    identity(b) not in relative

这只查字符串子串。假设 d=identity(b)，以下都包含 d，但都不是正确存储位置：

- other/{d}/binding.json
- m01/a_source/19000101/{d}/binding.json
- m01/a_source/{b.target_date}/prefix-{d}-suffix/binding.json
- m01/a_source/{b.target_date}/{d}/other.json
- m01/a_source/{b.target_date}/{d}/extra/binding.json

原 SafeRoot 可能接受这些合法相对路径；它不负责判断 M01 语义位置。当前日期 bug 会更早阻断正常完整读回，所以这里是“错误表达式与放宽后的可接受集合”的静态证明，不是声称上述完整正常链路已在未改 R9 实测通过。

必须改：
- 抽出 binding_relative(b)，唯一返回 m01/a_source/{b.target_date}/{identity(b)}/binding.json。
- 创建和读取共用该函数。
- read-and-verify 在 reader 前要求 type(relative) is str 且 relative == binding_relative(b)；同时拒绝非规范路径，不用 substring、endswith 或只比较某个路径段。
- 输出目录、日期目录、identity 整段与文件名必须全部精确一致。
- 不要否定 identity(b) 本身：:19–20 对全 11 字段求摘要的实现已具备，继续保留。

## 5. 第四阻断：root/source 边界还是没有代码

R9 全文件没有：
- .v5-shadow-root 检查与准确 marker 内容；
- 指定 source_root；
- source_root 与 private_root 相等或互相包含的拒绝；
- 原请求 pointer、磁盘 generation_path、reader 返回定位属于 source_root 的校验；
- 真实 SafeRoot 与原 reader 的模块内薄构造入口；
- 可定位的已做这些校验的实际调用方。

:16 的 startswith("/") 只判断绝对路径外形，既不限定授权 source_root，也不拒绝 ..、symlink、NUL 等。它不能关闭 R6 Mac 实测的“缺 marker”“源输出同根”“超出指定来源根仍接受”三个缺陷。

REPORT.md 只有“R8 remaining narrow parser/FileNotFound boundary update. Runtime tests NOT_RUN”。NOT_RUN 能说明测试没运行；不能把不存在的 root/adapter 实现归类为“已有实现，等真实运行”。

本轮明确不要求采集、公式 producer、活动 Mac 路径、预览接线或真实自然运行。要求的是纯本模块、对显式路径参数的 fail-closed 边界，已有原 API 足以实现。

## 6. Parser 剩余与 R8 回退

必须修正，但不再重复要求已经存在的 schema/strict/四 SHA：

- parse_binding :21–28 没有对 target_date、generation_path、generation_id 做严格类型/值校验，仍先把磁盘输入给 reader :32。
- project :18 将 generation_id 直接放进 binding；R8 :44–46 的真 str + 64 位小写 SHA 检查被删掉，需恢复。
- parse_binding :25 的 dataclass 构造会拒绝缺/多字段，但抛 TypeError；不要误说缺字段“被接受”。R8 的显式确切 keys 检查已不在，恢复它可保持统一错误合同。
- JSON duplicate keys 仍默认后值覆盖，严格 parser 应拒绝。
- :22–23 对 JSON 解码异常包装为 M01BindingError("json")，这是新增真实改进；建议限于实际 decode/JSON 类型异常，不需 catch 任意业务异常。
- Path 类型可明确接受后序列化，不能对任意对象 str；规范化应在拒绝 symlink/.. 等原始输入之后，避免先消除坏路径证据。
- :26 的 schema/status/strict/cutoff 常量与 :27 的四 SHA 继续保留，不重写来源数据验证算法。

另有 API 变化：
- R8 参数名 read_formula_generation 改成 R9 reader（:29、:35）。
- 已核 R6 Mac harness 使用 read_formula_generation=... 关键字，直接拿它验 R9 会先报 unexpected keyword，而不是业务边界结果。
- 未来测试须显式记录接口适配；最好保持原关键字兼容，或在清单里给准确迁移。不能悄悄修改 harness 后将旧结果套到新版本。

## 7. 已修内容保留清单

- 全投影 identity :19–20，创建目录使用 b.target_date :37。
- existing != 本次 b 拒绝 :42–44。
- reader READY、真正 bool True :14；schema/status/strict/cutoff :26；四 SHA :27。
- 从 SafeRoot 读取磁盘 bytes、重新调原 reader require_source=True、全字段比较 :29–34。
- write_bytes(require_absent=True) :45。
- 测试使用同一个 x 改 strict=1，tests:6–8；正确 import v5_shadow.a_source_daily。
- 新增 JSON 解码包装和绝对路径外形检查可保留。
- 正常日期回归、generation_id 校验删减、最终读回移出锁则是 R9 新退步，不能拿“继续最小修”忽略。

## 8. 精确的下一轮模块内接口合同

以下是给原 Chat 的实现范围合同，不是已存在实现，也不是让静态审查代写产品。名称可与工程风格对齐，但每项必须有实际调用链，不能只写未接入 helper。

### A. 纯校验/helper

1. validate_target_date(value) -> str
   - 真 str、[0-9]{8}、真实日历日期；失败在任何 reader/写入之前。
2. validate_binding_fields(mapping) -> ASourceBinding
   - 确切字段集合、所有字段类型、schema/status、date、generation_id SHA、四 SHA、strict is True、cutoff UNVERIFIED、绝对规范 path。
3. identity(binding) -> str
   - 保留全投影确定摘要；不改为若干 SHA 拼接。
4. binding_relative(binding) -> str
   - 唯一规范位置；读写两端精确相等验证。
5. verify_binding_bytes(raw, relative, bounded_reader, expected_binding=None)
   - 解析→精确路径→来源边界→原 reader→投影全等→可选本次 expected 对比；
   - 原 reader 的 FileNotFoundError 不转成 binding 不存在。

### B. 输出/来源根上下文构造

新增本模块内真实入口，例如 open_binding_context(*, private_root, source_root)，返回经过验证的同一个 SafeRoot 实例和受限 reader。它必须实际被公开 create/read 两条路径调用：

- 只接受显式绝对根，无 HOME/V4/猜测 Mac 默认路径。
- 先核原始路径合法、no_symlinks 与 source/root 存在性。
- 使用原 SafeRoot(private_root)，在取锁/写入前用该实例读 .v5-shadow-root；必须精确等于 b"v5.shadow-root.v1\n"。
- marker 缺失/坏值拒绝，不自动初始化或“修 marker”。
- 拒绝根相同及双向包含。
- reader 封装只做授权 source_root containment 与原始路径安全校验，然后调用原 read_formula_generation；不重新实现面板或公式校验。
- 文件/目录 pointer 都先定位为真实文件并限制在指定 source_root，reader 返回的规范 path 再核一次；磁盘 binding 的绝对 path 也走同一路径。
- 原 SafeRoot 做 dir-fd/relative I/O，来源根边界不靠 SafeRoot 自动推断。

### C. 两条公开路径

- create：验证上下文/date/pointer→原 reader 投影 b→规范 relative→锁内只捕获目标 read_bytes 缺失→验证已有 raw 并比较本次 b，或 require_absent 新写→锁内独立读回。
- read：验证上下文→读 raw→严格字段与精确 relative→受限原 reader→全等返回。
- 不可只新增一个 guarded wrapper 却在实际消费者里继续调用能绕过 guard 的旧公开入口。注入接缝可保留为私有或显式测试层，生产调用必须定位到 guarded entry。
- 测试用临时目录建立 marker 是 fixture 准备；产品入口自行创建 marker 不是修复。

仅改 V5/src/v5_shadow/a_source_daily.py、V5/tests/test_a_source_daily.py 和本模块文档/fixture。原 V4、canonical donor、共享 composition/contracts/UI/API/调度与其他模块仍只读。

## 9. 必要原 API 与已给材料

不重下载旧包，不索取整库、不要求 Chat 连 Mac。原 SOURCE、R6 Mac 固定原件及 SHA 已核：

- canonical 根：handoff/v4-running-source-20261005/canonical。
- infrastructure.owned_io.SafeRoot
  - 文件 owned_io.py:27；构造 SafeRoot(root: Path | str)，实例 .root。
  - read_bytes(relative, *, max_bytes=...) :103。
  - write_bytes(relative, raw, *, require_absent=False) :120。
  - kernel_lock(relative, *, timeout=10.0, poll=0.02) :182。
  - SHA256 9a74731287ca7c9667643557d4ae42f63453a025665ba28f5b65fdbff7d54ee0。
- infrastructure.formula_generation.read_formula_generation
  - 文件 formula_generation.py:202。
  - pointer: Path | str；keyword-only expected_target_date: str | int | None=None；require_source: bool=False。
  - M01 必须显式 require_source=True。
  - FORMULA_GENERATION_POINTER_NAME 定义原文件名，目录输入按该常量定位；不得猜文件名或活动路径。
  - SHA256 0904603912d6257cb02f41dfaf66c080e2f682e690b1c1901a86a7bafe1e74f0。
- v5_shadow.composition.no_symlinks / shadow_root
  - V5/src/v5_shadow/composition.py:22–36；双向 overlap 规则 :39–46。
  - 只读调用或在本模块适配，不改共享原件。
- v5_shadow.digests.canonical_bytes / sha256_json
  - V5/src/v5_shadow/digests.py:6–13。
  - 可复用作统一 identity 序列化；若沿用现有 identity，也必须读写同算法。
- 把完整既有 V5/src/v5_shadow 包和新增模块放在同一个隔离 package；V5/src 与 canonical 两根进入局部 import path。
- SafeRoot 用标准库/POSIX 能力；原 reader 审 parquet 日期使用 pyarrow。这一只读 binding 切片不导入四个 producer parts 的 _namespace，也不调用任何采集/公式 producer。

## 10. 为什么可能反复漏写，以及怎样一次消除范围歧义

能从交付文本直接观察到的事实：R9 REPORT 又将范围写成“narrow parser/FileNotFound boundary update”，但上一轮明确列出的 root/source/薄装配没有进入源码。不能臆测作者动机或断言内部过程；更合理的处理是取消“生产装配”这个容易被当成部署工作的模糊标签。

下一轮范围应明确写成：

“本轮必须交付本模块参数级 root/source guard 与两条实际调用它的 create/read 入口。这属于源码实现，不是 Mac 部署、真实采集或预览接线。source_root/private_root 都由调用者显式传入；没有活动路径也能写完并用临时 fixture 验证。NOT_RUN 仅用于运行证据，未交代码须写 NOT_IMPLEMENTED，不能混列。”

用逐函数完成表代替长篇宣称：
- 函数名、文件/行号；
- 哪条公开入口实际调用；
- 对应坏输入在 reader/写入前如何拒绝；
- 相关测试名；
- RUN/PASS/FAIL/NOT_RUN 与命令证据分栏。

作者必须完整交本轮清单，或逐条说哪项 NOT_IMPLEMENTED 与确切原因，不能自行只选 parser 两项并将剩余归为环境。已有实现要保留，禁止为压缩代码重写后丢 generation_id 校验/锁域/接口。使用正常多行代码和小函数也便于下一轮审核具体 catch 与缩进，而不是压成单行后声称“形状已修”。

## 11. 给云端任务的测试重点与记账方式

用户已另行要求云端真实测试；这部分是交接建议，本审查不执行：

1. 消费环境自行用 Library 当前流程物化上述准确 ID，核 ZIP/源码 SHA，不假定本云工作区路径在另一保存环境可见。
2. 不修改原 R9，先跑其两个原测试并留 command/cwd/PYTHONPATH/解释器/退出码/原始日志。test_ok 的日期错误是第一预期失败；不要先修后只报绿色。
3. 严格区分无法导入、原测试失败、parser 单元失败与完整真实 reader 边界。R9 API 改名为 reader，任何 harness 适配只改测试装配并记录。
4. 可以对未修改 R9 的 parse_binding 独立输入坏 date/id/path 检查：它们目前可在 parser 层构造成功，说明缺少前置校验；不要把这说成真实 reader 最终接受。
5. 正常完整 create/read 会被日期正则更早阻断；root/深层错误路径无法到达时记录 BLOCKED_BY_DATE_VALIDATION，不是 PASS，也不是“R6 缺陷消失”。
6. 如需单独证明 catch 或 substring 的控制流，mock/monkeypatch 属于测试隔离，必须明确“结构单元证据，不是原源码完整 reader 通过”。未经另行授权不改候选后冒充原 R9。
7. 原 R6 回执继续作为历史证据：原 pytest 2 passed/exit0；边界2 PASS+7缺陷复现；独立复跑最后写结果目录失败 exit1。均不转记 R9。

## 12. 可直接发原 Chat 的精简返修文字

已按实物核 R9 ZIP，SHA48a0d8aa99ef710003aa7c09e5330e6e9ffa99af001c0302ec63079ae60f5d48一致。R9 仍有以下明确代码问题，请一次交全，不再以“生产runtime NOT_RUN”代替缺少实现：

1. project :17 写的是 raw r"\\d{8}"，不是八位数字；正常20261011和自带test_ok都会被拒。请用[0-9]{8}+真实日期校验，并复用于请求/磁盘parser。恢复R8已有generation_id的真str+64位SHA检查。
2. create_binding :40–41仍catch完整read_and_verify，reader FileNotFoundError照样会被当目标缺失。try内只允许private_root.read_bytes；parse/来源reader置于外部共用verify_binding_bytes；已有bytes失败绝不write。
3. read_and_verify :33的identity(b) in relative只是子串。请共用binding_relative(b)，完整要求relative等于m01/a_source/{date}/{identity}/binding.json，reader之前核，错日期目录、前后缀、错文件名均拒。
4. root/source guard仍零实现。必须在M01白名单模块补真实SafeRoot/原reader构造与公开create/read入口：显式private_root/source_root，先核marker精确b"v5.shadow-root.v1\n"、no_symlinks、两根不相等/不互含；初始pointer、磁盘generation_path、reader返回path都限定source_root。不要自动创建marker，不默认Mac活动路径，不改共享文件。此为参数级源码边界，不是要求你部署或采集。
5. parse_binding先核全字段类型、date/id/path后再调用reader；保留现有strict/schema/status/cutoff/四SHA/JSON包装。恢复锁内最终读回；说明read_formula_generation关键字改成reader的接口兼容，不能让原harness默默失配。
6. 保留R8已经修好的全投影identity、本次b比较、require_absent与磁盘独立读回。下一版按“函数/行号→公开调用方→对应测试→运行状态”交清单。代码未写标NOT_IMPLEMENTED，只有代码存在但未执行才标NOT_RUN。不要只重做parser再漏root入口。

原接口已在SOURCE：canonical/infrastructure/owned_io.py::SafeRoot，read_bytes(:103)、write_bytes(require_absent)(:120)、kernel_lock(:182)；canonical/infrastructure/formula_generation.py::read_formula_generation(:202)；V5/src/v5_shadow/composition.py::no_symlinks/shadow_root(:22–36)及双向overlap(:39–46)。均只读复用，不需要再索要整库或连接Mac。云端独立测试的真实结果会另附，当前这些是源码确定问题，未冒充运行日志。

