# P1 R2 / P5 独立只读审查

## 审查结论

**工程边界审查 PASS；实际 Mac R/I 验收仍未完成。**

已独立审查 R2 的历史计划负向筛查。它只排除明确晚于 cutoff 的 canonical owner envelope；无法识别的前缀回落原完整正文校验及剩余预算。它没有把 header、自报 SHA、run_id、filename、mtime 或 latest 别名作为计划准入证明。

最终审查源码：`/workspace/scratch/90a399518fca/candidate/v4/manager_research/workspace_history.py`

最终 SHA-256：`9fe1b409c695a1fb057d45de8f6925d36487c17e4d7a5140de7dba011987de8a`

独立复跑前后源码 SHA 一致。Reviewer 未修改 candidate；新增测试、probe 与证据均在 review_history 下。

## 审查发现并已修复的问题

最初 R2 对整个 16 KiB 前缀直接调用严格 UTF-8 decode。合法中文正文恰好在第 16,384 字节截断一个多字节字符时，尽管 top-level envelope 已完整，解析仍返回 UNKNOWN，转入大正文读取并再次耗尽历史正文预算。

独立 RED：6 份合法 canonical JSON，每份 37,854 B、无 journal、前缀全部切在中文字符中间，64 KiB 正文预算返回 OWNED_FILE_TOO_LARGE；独立 12 项测试为 1 failed / 11 passed。

Writer 修复为严格 UTF-8 incremental decoder，`final=False`。只有末尾未完整 codepoint 被保留等待；前面实际非法 UTF-8 仍不被吞掉。独立测试随后转为全绿。

## 最终验证

环境：Linux，Python 3.14.6；实际导入 candidate，PYTHONPATH=candidate:candidate/upstreams:candidate/tests。禁用 bytecode 和 pytest cache，临时文件均限定 review_history。

| 验证 | 结果 |
|---|---|
| 独立自写 P1 安全/回退用例 | 12 passed |
| R1 history + R2 history | 28 passed |
| 联合独立复跑 | 40 passed in 1.40s |
| 源码在验证前后不变 | PASS |

独立用例验证了：中文截断前缀、未知布局确实执行完整正文读取、正文 SHA 不符、run 不符、安全标志不符、cutoff 与 generated_at 矛盾、伪造 latest 别名 SHA、相同 cutoff/generated_at 不同 SHA 的歧义、latest/ancestor symlink、FIFO，以及 cutoff equality 仍走完整产品 SHA 校验。

现有 journal 的损坏、错 owner/date/run、symlink 拒绝，以及 payload/receipt/date/path/PIT/source_row/其他 manifest 变化的拒绝，继续由 28 项原用例通过证明。

测试回执：`history_r2_independent_pytest_receipt.json`

测试日志：`history_r2_independent_pytest.log`

独立用例：`test_history_r2_independent.py`

## 真实数量级合成 probe

使用 supplied inventory 的七个文件尺寸生成独立合成计划。原 inventory 仅提供尺寸及时间参考，没有把它当原计划产品。所有合成产品均无 journal，且故意使 16 KiB 边界切在中文多字节字符中间。

| 指标 | 实测 |
|---|---:|
| 合成计划文件数（含 latest 副本） | 7 |
| 合成目录正文总字节 | 147,031,510 |
| 历史计划前缀读取字节 | 114,688（7 × 16,384） |
| 完整计划正文读取 | 0 |
| 明确晚生成排除 | 7 |
| 合格历史计划 | 无；select_plan 返回 None |
| 扫描异常 | 无 |
| 读取前后全部 fixture 文件 SHA | 不变 |

这里的 114,688 B 是计划归档的前缀数据读取，不是整个 API 请求、日历或其他 owner 的总 I/O。测试不使用原 Mac 计划内容，不证明原产品 SHA、原 PIT、原 owner 回执或 API/UI 读回。

数量级 probe：`probe_history_r2_scale.py`

数量级回执：`probe_history_r2_scale_result.json`

## 保留的边界与未验收项

- header 仅为负向候选筛查，不完整验证被排除文档的正文、SHA 或历史 availability；不能把它计为已校验原产品。
- 无法识别的旧格式继续承担原 32 MiB 单件 / 64 MiB 正文扫描预算；R2 不保证任意旧格式大目录都可免预算扫描。
- canonical late latest 与同 run 副本各自被排除，没有通过自报 SHA 冒领字节相等证明，也没有新增 alias 准入机制。
- 有机会合格的产品仍完整验证，并继续依赖原 owner attempt、原 source replay、PIT、冻结语义字段及 reader stability。
- 实际 Mac loaded source identity 仍为 CANNOT_CONFIRM。真实 10/09 原计划与 journals 未提供，所以实际 R 未签收。
- P5 仅确认并修复了历史 read_history 在 semantic identity 相同后又对冻结字段作 raw 字典比较的路径；原 narrow semantic_value 合同及七类相关变化拒绝已复跑通过。
- 真实 20261012 两项 identity component 的原 saved/current prehash 仍缺，实际 STALE_INPUTS_CHANGED 不得报结案。46/15 个 refs 派生对照不足以恢复组件哈希原像。

