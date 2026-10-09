# R3 evaluator 依赖绑定修复范围

基准为已获本机 38/38 与一次 metadata-only prepare PASS 的 R2 `4be3c657c04cb3431d19a83cf584bdb2a0481dac`。不重新安装或验收同一 R2。新问题固定反馈为 `cd1a080c13f1b1849d4b882b587b374dd948e5c8`、Issue #33 comment 6074178999。

## 历史身份依据

已恢复历史 `MAC_FIXED_SOURCE_MANIFEST.json`：19131 bytes，SHA256 `64fd0f7a5e3d646f7b5b184d44ca10576aab9db73772b3abb2cfceab36862a9b`。完整身份与独立保存的 `MAC_FIXED_PACKAGE_IDENTITY_RECEIPT.json` 指定的大小和 SHA 同时一致。此清单对应 Mac-fixed archive `aaf9d39eaed231f957c1818e19396edc258bf1df3a7add3d480630122b003412`，而非原提交 ZIP `fa107fd967bcaca1b4d4b994d7d57a953d2585e1ea87c9e0ed82fb224c2a9baf`。

七项依赖使用历史清单中的精确相对路径、文件 SHA256 和 bytes。六份反馈快照逐字匹配历史身份。22-byte init 从版本声明候选 `__version__ = "1.0.0"` 加终端 LF 恢复，完整 SHA 独立核算命中清单；不声称下载或读取了原 ZIP。原包字节下载曾返回 403，没有绕过或反复重试；使用独立保存的历史清单和身份回执完成所需来源核验。

`config/contract.json` 的历史 Mac metadata amendment 已将原提交 `d610fc60…` 改为 `17ecffd1…`。本修复保留这一历史区别，不回退配置、不改指标或门槛。

## 代码与配置闭包

固定包模块：`spike5`、`spike5.common`、`spike5.features`、`spike5.settings`、`spike5.metrics`。配置仅 `config/base_features.json`、`config/contract.json`。路径由已冻结 metrics 包根派生；历史清单本身作为固定 SHA metadata 纳入 binding。

prepare 只读取来源和配置 metadata，收集完整记录；load_documents 重验闭包、历史摘要及来源路径。模块加载只编译校验过的源码，settings 两次配置读取使用限定路径的校验字节，保留原 JSON 语义。缓存需同时匹配模块名、origin、完整 source SHA 和整套 evaluator 闭包身份。

runner 在 native 校验之后、官方 adapter/guard 创建之前调用相同 worker evaluator loader 作 source/config-only preflight。child 原加载检查与临近 claim 的 source snapshot 校验继续保留。缺失、漂移、错误来源或不符缓存应在新 RUN_STARTED 前拒绝。

## 保留边界

不改变 PR5 accepted join、frames、指标、阈值、Top3、labels、真实预算、登记生命周期或原候选工件。R3 新测试验证新的依赖问题；R2 的 Mac 验收与实际 unsigned spec/binding 作为已完成历史事实保留。真实 R3 prepare、review/release 和评价仍由本机 Luna Max 进行，远端不创建授权。
