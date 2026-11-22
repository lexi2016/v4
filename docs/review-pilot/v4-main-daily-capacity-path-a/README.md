# V4 Main Path A 隔离候选：有界基础实现，尚不能启用

状态：`PREPARED_PARTIAL`；`INTEGRATION_ACCEPTANCE=CANNOT_CONFIRM`；迁移、切换、部署与自然链均 `BLOCKED/NOT_RUN`。生产未写入。Stage/QFQ 原 P1 既有 PASS 不重评。

本目录只含冻结 R4 的源码覆盖层、独立控制器候选、测试和禁用状态 policy delta。`PREIMAGE_SHA256.json` 是覆盖前字节合同；不是以 Git base 里的另一版本替代 R4。没有修改原候选、现役 app/launchd/policy、registry、CURRENT 或任何旧预留。261 GiB、八条旧预留与对应物理峰值继续全额计账。

## 已实现的有界行为

- `research_panel_delta.classify_delta_scope` 抽取原六类分类，只有读取，随后原 owner 再次比较类别、变动行数与原始价格/因子/基线/字段 schema 的分类 SHA。相同类别、相同行数而原值变化也会阻断。
- 原 QFQ 路径新增自动输入快照准备子阶段：仅在既有 input admission、输入写适配器和 publication 锁中，按原 producer 准备一次，再交原 QFQ 使用。该子阶段 JSON 与 parser parquet 在内存中按原 serializer 得到精确字节，写前检查原不可递增 Claim；不复制整张历史面板。原 raw_sync 行为保留。
- `research_daily_capacity` 生成 scope/input/policy SHA 绑定的不可变计划；未给独立审查静态输出上界则拒绝。逻辑布局以外、规则重算、未知新历史、过量修订与日产品 history bootstrap 均拒绝。没有自动编造每股或每行的预算。
- `growth_guard` 只在启用且计划有效时取该计划上界；缺省仍按原 48 GiB 路径。原 `Claim.begin/checkpoint/finish` 不可递增和恢复合同未修改。
- `begin_creation` 移至成功 claim 后，写自身证据前也测精确序列化字节。原 owner 的 pool→publication 取锁顺序保留。
- 新 controller 保留原 lane、角色、pool-writer、registry 锁顺序。原控制器实际上已持有后两把锁，未再制造第二次获取。新容量合同绑定 controller/helper/policy SHA，只允许全部锁持有期间，使用候选解释器运行 `Registry.read` 与实际根/inode 去重测量；不重入 registry transaction。读取所有活动旧预留，失败工件的 absence 边界也计入 resident。原静态五分钟合同继续按旧规则处理；新合同现场测量，无旧数字后备。

## 明确保留的阻断

`INSTRUMENTED_WRITER_PHASES={qfq}` 只表示已接入代码门禁，不表示 QFQ 完整 owner/输入/故障路径已经独立通过。`ACCEPTED_WRITER_PHASES` 为空，锁内 probe 一律返回 `CANNOT_CONFIRM`，controller 不会激活。

日产品/Top200 仍存在异步写和直接写缺口，`product_plan` 在 Reader 扫描与新 claim 前直接抛出 `INCREMENTAL_PRODUCT_WRITER_COVERAGE_NOT_PROVEN`。这不是三阶段闭环修复，不能据本目录宣布 T2/T6 或自然链 PASS。具体下一步在 `DOWNSTREAM_WRITE_SEAMS.md`。

`policy.disabled.delta.json` 是可移植、未激活的最小 delta，`enabled=false`，无生产数值上界，不能用于上线。任何激活需要完整三阶段字节/文件数/在途/替换临时峰值的可执行合同、真实 owner 集成回归、独审和用户精确批准。

## 验证入口

使用 `PANEL_PYTHON` 的绝对解释器：

```sh
"$PANEL_PYTHON" -B docs/review-pilot/v4-main-daily-capacity-path-a/verify_overlay.py \
  --frozen-app /ABS/FROZEN/app \
  --frozen-controller /ABS/FROZEN/cutover/main_only_cutover.py \
  -q -p no:cacheprovider docs/review-pilot/v4-main-daily-capacity-path-a/tests
```

入口先验证所有变更文件的前像 SHA，再仅将 Python 源码合并到生命周期受控的临时目录；不复制数据、面板或 runtime。现有 oracle 用 `owner.__file__` 找同目录源码，因此必须合并源码，而不能把稀疏 overlay 冒充完整 app。测试临时目录随进程退出清理。

所有测试是隔离源码/合成数据验证；未运行生产 producer，未触发网络采集、调度、Top200 发布或 UI 验收。完整命令和本轮结果见 `WRITER_RECEIPT.json`；Writer 结果须由独立 Reviewer 审查。
