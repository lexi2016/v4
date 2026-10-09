# R3 evaluator 历史身份来源核对

## 身份依据

原反馈固定在 `lexi2016/v4` 提交 `cd1a080c13f1b1849d4b882b587b374dd948e5c8`，四项缺失依赖的历史身份当时尚未确认。本次用独立保存的历史元数据恢复了所需身份；没有把当前快照的摘要直接提升为历史 pin。

历史 `MAC_FIXED_SOURCE_MANIFEST.json` 保存时间为 2026-09-23T03:45:54.298791Z。完整文件为 19131 bytes，SHA256 `64fd0f7a5e3d646f7b5b184d44ca10576aab9db73772b3abb2cfceab36862a9b`。独立 `MAC_FIXED_PACKAGE_IDENTITY_RECEIPT.json` 保存时间为 2026-09-23T03:46:17.479973Z，其中 `source_manifest` 明确记录相同文件名、大小与 SHA。原读取记录私有保留；公开交付不包含存储内部定位信息。

清单文本接口返回 19130 字节，恢复一个末尾 LF 后，完整大小和 SHA 同时匹配独立旧回执；随包清单因此是经完整摘要认证的原字节恢复。身份回执按接口返回的 5826-byte 文本附为 `evidence/historical/MAC_FIXED_PACKAGE_IDENTITY_RECEIPT.read_text.json`。该回执的原文件元数据记载 5827 bytes，本包不声称已经取得其完整原文件字节或原文件 SHA。

这份历史清单属于 **Mac-fixed source archive**：1073959 bytes，SHA256 `aaf9d39eaed231f957c1818e19396edc258bf1df3a7add3d480630122b003412`。原提交包则是 1049399 bytes、SHA256 `fa107fd967bcaca1b4d4b994d7d57a953d2585e1ea87c9e0ed82fb224c2a9baf`。本次原包字节下载失败，未绕过访问控制或重复重试，也未声称重新校验完整 ZIP。依赖验证使用下面七项精确文件身份。

## 七项历史身份

| 相对路径 | bytes | SHA256 |
| --- | ---: | --- |
| `spike5/__init__.py` | 22 | `27e8febb48ada44153ea2add9969a2c50a9831a74d9755fdd53c549a888b1cc2` |
| `spike5/common.py` | 2067 | `affff27d758d73fdbde3da21af59b94b265d4072cf83036475cd06b0941a4097` |
| `spike5/features.py` | 5941 | `947e8d9a2f2b36e44ecfc8d713e0c492670039838dcf3e5abb9396f17a637c38` |
| `spike5/settings.py` | 288 | `702c374612806e45647b8cdb8cb345736b6cac689f23df352c00d08735bfb4fc` |
| `spike5/metrics.py` | 8758 | `c8ffabf345069d64a82ac686e6747afda8c22433f1309eecdc999a7ad1eac763` |
| `config/base_features.json` | 408 | `6284bfe3609ec9f220b4f4baef6e0cb4d3190529830fbcb0d8ff435c0859c7af` |
| `config/contract.json` | 10193 | `17ecffd1304e152da4f611b3ffc4b5e92633fac20d528b93ce9b6f8714b1c4bb` |

六份反馈快照与清单对应记录在完整 bytes 和 SHA 上匹配。反馈未附 init 字节，恢复候选 `__version__ = "1.0.0"` 加一个 LF 为22字节，完整SHA与历史记录匹配，并由独立复核者复算。该方法不等于观察到实际 Mac 文件；本机 prepare/加载必须仍然核验原包 init，补丁不会替换它。

`contract.json` 的身份与历史回执的 `actual_package_source.contract_sha256`、`prepared_binding.prepared_contract_sha256` 一致。历史清单的 `actual_source_changes["config/contract.json"]` 和原配置的 `input_metadata_amendment` 说明 metadata amendment `HK_SPIKE_F5_INPUT_METADATA_R1_20260914`；其原提交摘要 `d610fc60f8ee078e8c934a29738e3b1683e395b2cf143251433afdb062403f31` 与 Mac-fixed 摘要的区别保留。

## 用于修复与测试的范围

生产代码固定完整历史清单 SHA，从其七条记录获取预期摘要和字节数，再验证真实包指定位置。模块图由原源码逐项审查：init 无包内依赖，common/features 无进一步包内依赖，settings 使用 common/features 并读两 JSON，metrics 使用 settings。生产运行不执行动态 AST 图推断。

测试 fixture 中保存同一19131-byte清单及七份原文件的精确字节。临时文件目录重定位不改变源码；已校验 score-aware wrapper 的两个路径属性是唯一正例路径适配。未知模块、错误字节等故障只注入临时副本。测试未训练、预测、加载模型、调用真实指标计算或读取真实数据/registry。

历史证据恢复不替代新 Mac 绑定复核和 parent release；它为这次依赖修复提供可交叉核对的固定文件身份。
