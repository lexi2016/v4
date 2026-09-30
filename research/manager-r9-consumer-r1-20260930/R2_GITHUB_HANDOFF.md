# Issue #8：R2 接续包 GitHub 提交入口

关联：[#8](https://github.com/lexi2016/v4/issues/8)。本次提交既有 R2 交付物，不代表运行接入问题已解决，也不关闭 Issue。

## 固定基线与文件位置

输入基线为 `4c1e2de72ef8a026aa5229caca6e4a5e98b17e36`。已有 R1 的源码、测试、37 份索引源文件及证据保持原字节。

完整 R2 位于 [r2_connect_authority/](r2_connect_authority/README.md)，共 **69 个展开文件**，不是文本分片或省略源码的摘要。包含 before/after、三份 patch、测试、只读核验工具、原日志、SHA 清单、本机接续及回退文档。

- [唯一运行增量](r2_connect_authority/runtime.patch)
- [完整后像](r2_connect_authority/after/api/v4/manager_research/connect_selection.py)
- [owner 供给判定与合法接入分支](r2_connect_authority/OWNER_CLOSURE.md)
- [本机验收与回退](r2_connect_authority/LOCAL_ACCEPTANCE.md)
- [状态回执](r2_connect_authority/REVIEW_STATUS.json)

## 传输核对

原下载包：`V4_R9_R2_ConnectAuthority_ReadOnly_Candidate_20260930.zip`，177,374 字节。

原 ZIP SHA256：`d3ba187367ff53270d20fbaf959c1ee09a871d12e7b67ecd3a7408a7486e1e81`。

本次以展开文件提交，不重复存储 ZIP 二进制。69 个文件的相对路径、字节及 Git blob 身份与原包一致；包目录 Git tree SHA 为 `5d6fec093655e2cebb16e81bfe8c8cd25a0760e4`。原 MANIFEST 的 68 条记录（不包含自身）与补丁正反回放已重新核对。

包内关于“本轮未提交 GitHub”的文字和历史 receipt 保留原字节，描述的是原 R2 交付时点；本页记录其后发生的 GitHub 提交，不追改历史回执。

## 实际范围与未通过门槛

R2 仅对已验 R1 的 `v4/manager_research/connect_selection.py` 提供一个运行文件增量：成对显式 owner root/SHA 接线及原 reader 结构化拒因保留。未放宽目标日资格合同；不会产生缺失的目标日名单。

27 项测试记录是原作者 Linux 合成测试，不是本次新做的 Mac、独立 Luna、真实 API/UI 或自然运行验收。R1 的独立验收照原收据复用，不计作 R2 独立通过。

**当前状态仍是 `CANNOT_CONFIRM_TARGET_RUNTIME_SUPPLY`。** 当前唯一活动资格 producer、目标日 authority、R2 本机独立复验及实际 API/UI 仍须按 Issue #8 与 LOCAL_ACCEPTANCE 接续。未部署、未启用新绑定、未调用旧 full-market producer、未修改 Stage/BUY/Vibe/暂停的 daily 草稿。

只验证交付文件与隔离补丁：

```bash
cd research/manager-r9-consumer-r1-20260930/r2_connect_authority
python -I tools/verify_delivery.py
```

真实 Mac 接续使用 LOCAL_ACCEPTANCE 中固定的原解释器及当前经核实路径。`reference_only/` 禁止部署。该 PR 保持草稿，不应因为文件上传或离线通过而关闭 #8。
