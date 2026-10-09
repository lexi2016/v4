# 等待时钟与节点入口的独立审查

结论：**PASS_CONDITIONAL_HISTORICAL_SOURCE_SLICE**。四个候选文件（两种历史 owner 变体，每种两文件）没有发现未解决的 P0/P1/P2 问题。它们只能在本机现役前像核对通过后作为窄改动应用；不是对未知当前 helper 的整文件替换许可。

审查者：`/root/stage_hk_and_entrypoint`；作者：`/root`。审查者没有修改产品候选。固定输入 commit：`28ab2d35020adf031f10f38c1040514fc81b6d66`。

## 固定前后像

| 变体／文件 | 前像 SHA256 | 候选 SHA256 |
|---|---|---|
| `actual_stage/deadline_supervision.py` | `95ce916246f3376fc3618c0890ee1f76f2b0231c50d77fe5440a9b956884a674` | `1f65476c5a274195b789a3529a3e95821bfcf81278c6ac72e01c52655932cf08` |
| `actual_stage/node_entry.py` | `f9530f010055476e17d87e93198e28d3f4943ed34255a2419130eb9f39deb6ed` | `3a40b79ecea876997aad9272205ebf61289af2a17162057fa680174c50e74fd2` |
| `canonical/deadline_supervision.py` | `95ce916246f3376fc3618c0890ee1f76f2b0231c50d77fe5440a9b956884a674` | `1f65476c5a274195b789a3529a3e95821bfcf81278c6ac72e01c52655932cf08` |
| `canonical/node_entry.py` | `2343cd5e250aaa05acc698ba2daf34220f13ffb5543c655df799fdb3bd7fe464` | `0efb31e207a7282eea9308c81c69c7bfd0f4c989d03d03acc9407e430f832fe6` |

`SOURCE_IDENTITY_AND_DIFF.json` 逐项记录 repo 路径、Git blob SHA、字节 SHA 和精确一行差异。四个前像的 Git blob 均与固定 `BASE_TREE.json` 匹配。actual_stage 的名称仅表示 10/5 manifest 所映射的 Stage owner；当前 Mac 对应文件没有在本轮实取。deadline helper 的 Stage owner 与 canonical 使用相同历史字节，node_entry 两种 owner 保留各自前像。

## 改动与原合同

等待 helper 原来在 `sleep` 返回后直接返回计划 cutoff，原 node_entry 又把只要发生等待的路径强制标成 NATURAL。候选分别改为：

1. 保留原等待请求与原 deadline checkpoint，之后读取 `datetime.now(SHANGHAI)` 并交给原 `_as_shanghai`。
2. 等待后使用这个实际观察时刻，再调用原 `_node_mode`，不增加阈值或改写该原策略。

两种 owner 均只有上述两个单行改动。阶段合同、Node 的整分钟计划、原 `evaluate_due`、报价时间窗与评分没有变化。actual contracts 的 SHA 为 `6880f6a82c7f4fb0fde5c0661bd5a8bb12b590661a4b8552bcb3d6be969ae83d`。

| 情况（上海时区） | 原节点窗口判断 | 原阶段 due 判断 |
|---|---|---|
| STAGE_0940_0945 实际 09:45:05.000001，节点09:45:00、阶段cutoff09:45:05 | RECOVERY | LATE_CATCHUP_REPLAY |
| 同阶段回退至09:45:04.5 | NATURAL | NOT_DUE |
| 同阶段回退至09:44:59 | RECOVERY | NOT_DUE |
| STAGE_0945_1030 实际10:30:00.25，节点与cutoff均10:30:00 | NATURAL | LATE_CATCHUP_REPLAY |
| 同阶段实际10:30:05.000001 | RECOVERY | LATE_CATCHUP_REPLAY |
| 等待后时钟跳到次日 | RECOVERY | CANNOT_CONFIRM |

这两个判断保持独立。NATURAL 字样仍是原节点模式，不能升级为已验证的自然完成；它也不能把 NOT_DUE 改成 DUE。真实行情接收仍由原阶段/collector 的时间合同决定，不能把晚醒时刻填成行情截止时间。

## 独立执行

作者最终使用 actual contracts 的测试套件由审查者复跑：**29/29 PASS**。

审查者另写 **22/22 PASS**：完整导入候选 deadline/node_entry helper 模块，加载原 Node 类、原节点时间映射、原 `_node_mode`、原 `evaluate_due`，核对全部支持文件 SHA。时间、calendar 和最后 dispatcher 是显式边界，calendar seam 设置 HK Connect 关闭，不执行观察 lane 或数据采集。

新增探针覆盖：

- 1 微秒越过 cutoff、整分钟 cutoff 与 +5秒 cutoff 的不同节点模式。
- 向后回调和向前跨日跳钟，实际时刻完整传到原 due 函数。
- 传入无限大的 `max_wait_seconds` 也不能把原请求上限扩展到 5 秒以上；恰好5秒允许等待，5.000001秒不等待。
- 操作系统晚醒8秒时记录实际醒来时刻；返回的 `waited` 仍是原请求秒数，不能拿它证明实际只耗时5秒。
- `sleep` 中断或原 deadline checkpoint 抛错时不返回假 cutoff，不进行新时钟宣称。
- UTC目标／原无时区上海输入都按既有 `_as_shanghai` 合同处理，实际调用明确读取上海时区。

独立 fixture 首轮漏了 `calendar_provenance` 这一显式测试依赖，导致12失败、10通过；该失败来自 reviewer fixture，产品未修改。补上声明的 calendar provenance seam 后22项全部通过。原始日志在 `evidence/independent_clock_final` 保留，正确最终通过日志为 `evidence/independent_clock_review_pass`。

## 不能由本测试证明的事项

5秒是原 helper 的**请求等待窗口上限**；它无法约束操作系统真实唤醒延迟，更不等于整个采集、算法、归档、API 链都已在5秒内完成。完整 pipeline 的原 monotonic deadline、Mac真实负载性能和最终落盘完成状态仍要按原链验收。

本测试没有当前 Mac CLI import、真实 provider 采集、HK资格输入、自然时段 receipt、API/UI、部署或历史数据重建。必须先核对本机现役 helper、facade、contracts 与本报告前像条件；不匹配时保留当前版本并针对当前源做同等窄修复。不能用候选直接覆盖未知现役文件。

## 自包含复跑

测试仅依赖 `work/entrypoint_clock/{before,after,test_support}` 与本报告的 tests；不依赖未随包复制的 `hk_entrypoint/references`。

```bash
python work/hk_entrypoint/run_independent_review.py --suite clock --label local_clock_review --python /path/to/existing/venv/bin/python
python work/hk_entrypoint/run_independent_review.py --suite clock-author --label local_clock_author_review --python /path/to/existing/venv/bin/python
```

`--python` 为已有且可运行 pytest 的解释器；未指定时优先用已有审查环境，否则使用启动此脚本的当前 Python。所有测试都只生成临时 fixture 和审查日志，不启动业务服务。
