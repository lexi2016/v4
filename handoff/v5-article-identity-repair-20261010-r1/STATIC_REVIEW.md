# 独立静态审查记录

独立 reviewer 只读检查 candidate 对固定 baseline 的差异、原 owner/collector/store 调用关系、AST 与 SHA，没有修改文件，没有导入产品模块或运行测试。主控修复产品代码，独立测试任务补候选。**所有产品执行 NOT_RUN。**

## 发现与处理

| 级别 | 静态发现 | 处理与候选 |
|---|---|---|
| P1 | 最终 v2 仅 Python 对象比较，可能吞掉 `1/true`、等值 `int/float`，即使旧 v1/source 不变也能改 v2 类型 | validator、原 store 读回与独立读回加入规范字节比较；新增两个完整重哈希 reader 候选 |
| P1 | 原 collector 的 `.0900.json.<pid>.tmp` Path writer 可能跟随预置 symlink，读回拒绝前先损坏目标 | V5 BoundPath 限制原 owner IO；相同原 serializer 经固定 SafeRoot no-follow/no-replace 提交，锁用 dirfd；新增旧临时/目的 symlink 两个 sentinel 保持候选 |
| P2 | owner source 可用时间与 v2 生成时间未相接，可能倒填到 capture 可用与 source 完成之间 | verify_builder 返回 receipt 后追加排序，保留 ARTICLE_V2_IMPORT_CLOCK；新增完整重哈希 reader 时间候选 |
| P2 | 自洽 source/archive 伪造测试原用 compact JSON，会被原 pretty serializer 提前拒绝，掩盖语义缺口 | helper 支持精确 source_raw；真实原 bytes 控制后仅改 claim_type，所有 source 与 archive SHA 一致，用原格式触发语义重放拒绝 |

reviewer 复读前三项产品代码修正后未报告新的确定阻断；测试任务完成第四项和相应候选，主控再次只读检查并 AST 解析。这里没有“测试 PASS”结论。

## 已核到的接线

- 新 source 验证在导入写入前和每次独立 v2 reader 进入；缺引用无旧 v2 接受分支，v1 明确交原 validator。
- 完整 source 是原 collector/normalizer 输出，没有从 article 猜字段；原 builder 比较包括非身份 stock_pool 数据。
- 新 BoundPath 覆盖固定 collector 实际需要的 summary.is_file、source.read_bytes、relative_to/as_posix；旧原临时 writer 不接真实 Path。
- 两个 CLI 的加载顺序未发现必现循环或 _OWNER 二次加载阻断；这是静态调用追踪。
- 原固定 ResearchArchiveStore SHA `471ad4ceb0c34f080da674d147df5bb96045c5e7998ab41ba2845297ab63ab6f`，read_exact 会进入安装后的 validator。
- 原 SafeRoot SHA `9a74731287ca7c9667643557d4ae42f63453a025665ba28f5b65fdbff7d54ee0`，存在 dirfd/O_NOFOLLOW/独占临时文件/require_absent 路径。
- manager 动态复用 archive_reader.PATTERN；新 source/receipt 文件传递与 worker identity 有相应接线。
- 合成正文的主体、alias 和首个证据句符合所读原 normalizer 路径；fallback、重复合并的合同候选符合原 builder 源码。
- 八份 owner/support 原字节与 descriptor 的长度、SHA-256、Git blob SHA 相符。namespace 缺口按结构支持标注，并保留 Mac 实际原路径 SHA gate。

## 未证明的部分

Mac 仍须验证完整原依赖、原 namespace 实际路径、两个 CLI 的真实动态加载、完整同批 source 字节、类型/时间/自洽伪造拒绝、symlink sentinel、原 store→reader→材料/主体→manager→同 run plan。临时目录必须满足无 symlink 祖先的产品门禁，当前 US 合成时间必须满足原 calendar/PIT。

没有读取本批真实原始材料，没有真实 owner/run 独立见证；可重放性和全部声明字节自洽不能替代真实来源或自然发生时间。具体执行环境和静态工件检查在 STATIC_CHECKS.json，产品测试状态为 NOT_RUN。
