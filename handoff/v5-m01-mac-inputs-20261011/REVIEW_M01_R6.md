# M01 R6 独立增量静态审查

**结论：可送Mac做限定范围的隔离工程测试和缺陷复现；尚不能安装到活动来源root、接预览生产消费或计M01完成。** R6确已实现不可覆盖写入与磁盘起点读回，不再把它们列为缺失；剩余是完整identity复用错误、root边界及解析/装配契约。未运行真实工程只记NOT_RUN，不等同未实现。

## 实物与本轮验证

- ZIP：4,866 bytes，SHA256 `6e06e48ca55cf04c2122f114d043a4f05d5b25ff440a94b62f0c14782e1cfb08`，匹配；6件共10,348解压bytes，CRC及SHA256.txt全部匹配。R5摘要清单错误已修。
- runtime.patch隔离check/apply均exit 0，源码/测试与after逐字节一致，AST解析成功。未import/运行产品、reader、pytest或采集。
- 作者的reverse.patch与runtime.patch字节相同。直接apply reverse在after目录exit 1（文件已存在）；使用`git apply -R runtime.patch`的check/apply均exit 0并恢复两文件ABSENT。因为两文件相同，`git apply -R reverse.patch`等价可用。**同内容本身不强制重生成另一种diff；但包内REPORT、全文都没有-R使用说明，需补明确回滚命令。**不把这项表述为“不能回滚”。
- 静态日志：`/workspace/shared/m01_r6_static_review/STATIC_CHECK_RESULTS.json`。固定原source/history已提供，不需要再补整库或SafeRoot文件。

下列代码行号均指候选`V5/src/v5_shadow/a_source_daily.py`。

## 保留的真实修复

- :27-37在投影前明确核READY、strict=True和四项SHA；原字段映射正确，cutoff固定UNVERIFIED。
- :51按日期/generation_id分路径；:59使用`require_absent=True`。新失败不会再覆盖同路径旧文件，R5的覆盖型缺陷已修。
- :39-45已通过SafeRoot从磁盘读取binding，重调原reader并全字段比较；:60新写后调用该入口。不能再说“只有内存verify”。
- :53在原SafeRoot锁内执行创建/读回。传入**真实SafeRoot实例**及原`read_formula_generation`即可匹配当前调用签名；不是虚构safe_write_json方法，也没有证据说该helper无法执行。
- 现有2个测试源码保持有效的投影与strict=False负测；NOT_RUN诚实保留。

## 仍需最小代码返修

### 1. P1：generation_id不是完整来源identity，复用还忽略本次新结果

:49-50先取得本次b，:51仅用target_date/generation_id定位；:55-56直接返回磁盘记录的验证结果，**没有与本次b比较**。

固定原`handoff/v4-running-source-20261005/canonical/infrastructure/formula_generation.py:230-234`将generation_id定义为selector/backtest metadata的摘要，不覆盖source/receipt/input_manifest或pointer位置。相同面板可对应不同来源证明。

- 若已有记录指向仍有效的原pointer A，本次请求pointer B，二者同日期/同generation_id但来源/路径不同，:55读取A并验证A成功后直接返回A；本次B的身份被忽略。
- 若同一CURRENT的receipt/manifest改变而面板metadata不变，generation_id路径冲突；旧记录读回拒绝后又尝试require_absent写入，得到FileExistsError，无法把新输入存为新identity。

**修复**：路径包含完整绑定投影的稳定摘要（至少包括generation文件SHA、manifest两层SHA、receipt SHA及已绑定定位），而非仅generation_id；复用时仍必须将已验证磁盘binding与本次b全字段比较。原算法/reader不用改。

### 2. P1：不能将任何旧记录验证错误当成“文件不存在”

:54-58捕获所有Exception后继续写入。损坏JSON、原来源漂移、权限错误或其他reader失败都被掩盖；通常随后FileExistsError，丢失真正原因。原SafeRoot的require_absent保护了旧字节，但错误语义不正确。

**修复**：只在确认目标binding文件本身不存在时创建；已有记录的读取/校验失败原样拒绝，不尝试修复/覆盖。不能仅把整个read_and_verify调用改为捕获FileNotFoundError，因为该错误也可能来自其原来源reader。

### 3. P1：root边界缺代码；生产依赖装配需明确，不能混成NOT_RUN

R6的private_root实际要求是具有kernel_lock/read_bytes/write_bytes的对象；源码没有核`.v5-shadow-root`、声明的source根和output根不重叠，也不约束磁盘binding中的generation_path属于已授权source根。原SafeRoot负责抗symlink/相对路径越界，**不替调用者判断哪个root是M01或是否与源根重叠**。

- **已可执行的工程接缝**：Mac隔离测试可以直接传`SafeRoot(temp_private_root)`和真实原reader，不需要重写算法。没有真实Mac运行证据仅为NOT_RUN。
- **尚未交付/定位的生产装配**：包内没有具体原类/reader绑定入口，也没有指定“哪个既有调用者已经做了root guard”。若由统一runtime注入，只需提供准确调用位置、类型与前置校验契约；若不存在，则在M01白名单内补最薄适配。不能默认让Mac补这些约束。

**修复**：入口验证明确private/source根与marker，并把来源根作为独立读回边界，使用现有`V5/src/v5_shadow/composition.py:22-46`等价规则；原SafeRoot/reader只读复用，不猜Mac实际路径、不改共享文件。

### 4. 小范围解析补齐

:40直接dataclass构造并非独立严格schema parser；大部分错误会被后续原reader/全字段比较拒绝，已有保护应保留。但严格bool类型未验证，例如JSON的strict_source_verified=1与True在dataclass比较中相等；缺cutoff_status会取默认值。缺少明确字段/类型拒绝，也可能先按未经验证的generation_path调用reader。

**修复**：安全读JSON后，先核确切字段集合/schema/status、真实日期、path/id类型、四SHA、`strict_source_verified is True`、cutoff=UNVERIFIED，再进入受来源root限制的原reader。不要另写源行情或公式校验。

## 可立即交给Mac的隔离测试范围

只在新的临时checkout/fixture目录应用已核runtime.patch；使用固定原SafeRoot与原reader、合成或已授权隔离副本，不指向活动V4/V5数据根，不采集/计算/改共享/接预览。可以运行：

1. 已有2个定向测试，以及真实SafeRoot写入→磁盘read_and_verify的正常用例。
2. 同完整identity复用、不同source identity但同generation_id、请求不同pointer却复用旧记录的复现。
3. 已有记录损坏/来源漂移与第二次reader失败，确认旧文件不改且保留错误原因。
4. root重叠/未初始化marker、恶意generation_path、symlink/越界、strict=1等解析边界用例。
5. 正向产物SHA及明确`git apply -R`回滚到ABSENT。

这属于工程测试准入，**不是生产接纳**。上述失败用例应回同一Chat连同修复一次交付；不再以等待真实行情为由推迟源码/测试。真实自然运行、cutoff时点证明仍不在这个只读切片的本轮放行范围。

## after身份

- 源码2,378 bytes；SHA256 `922f1d3300ad94c5309964fb22d19b23f44b515fe3d2414cf04ad1220c527960`；Git blob `74d5e872219b542a12c2f5acbe30937fba15dcb6`。
- 测试581 bytes；SHA256 `e753bfb98ac7887d55532df2981806aeabbc87f5d1cdb243015404cf01128dc5`；Git blob `ae2d74bceb63958e09c8491142549d4136688275`。
