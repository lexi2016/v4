# V4 三路 R2｜冻结差异与交接

固定问题：[#34](https://github.com/lexi2016/v4/issues/34)，关联 [#32](https://github.com/lexi2016/v4/issues/32)。

本分支包含用户 R2 附件内 runtime/canonical 两套源码上生成的**精确补丁**，未修改现役 V4 根，也未重写原业务数据。独立 Mac 实测、完整 App 回归、API/UI、自然槽 **NOT_RUN**。综合状态 **PARTIAL**。

- `GITHUB_PATCHES.tar.gz.b64` 已与生成环境字节级 Git blob SHA 一致：`a30e3b4577a67583652c32bc299b605f2fc14a4f`
- Base64 解码后的 gzip SHA256：`089ab6675ba5cd7d68f8f29b3249daca035372c26ff69a38cceded3f6da775c4`
- 压缩包内包含 `patches/runtime_source.patch`、`patches/canonical_source.patch` 及 `SHA_MANIFEST.json`。两套补丁分别对 frozen before SHA 独立应用、读回 after SHA、反向还原均通过。不要交叉套用，也不要覆盖 canonical 未提交修改。
- 从本分支下载 b64 文件后，Mac 可执行 `base64 -D -i GITHUB_PATCHES.tar.gz.b64 -o GITHUB_PATCHES.tar.gz`，`shasum -a 256 GITHUB_PATCHES.tar.gz`，`tar -tzf GITHUB_PATCHES.tar.gz`。只在隔离复制根验证，先核每个 before SHA；之后由原 Mac 主控决定集成。
- 修改：分离原 StageSelectionConsumer 与观察 DTO、禁止 backfill 替代正式 HK、历史失败 owner/stage 稳定诊断、canonical 恢复已部署的原 owner_plan_readback 入口。
- R2 原数据缺口未补：10/08 港股权威主表缺 entry、10/09 Top100 `EXPECTED_MISSING`、超跌 60 日/量纲、旧计划 `STALE_INPUTS_CHANGED`、10/09 历史 PIT 无当时有效计划、自然 slot 未验。55/214 为事后研究候选，不是正式 10/09 选股。
- 研究隔离不变：`RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。

工程执行范围：基于实际目标源码的隔离单元红测 5 failed（预期）→绿测 8 passed；完整原 App 无法收集（缺 `infrastructure`），不自称独立 Reviewer PASS。详细测试证据与 Mac 完整验收矩阵在同轮独立交付 ZIP 的 README。
