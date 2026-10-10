# 给 Chat：修复 archive 原 builder 身份绑定缺口

请先读本文件与 `REPAIR_REQUIREMENTS.md`，检查所附代码，给出最小合同/接线修复及失败测试；不要仅写孤立 helper，也不要把静态判断写成测试通过。

- 仓库：私有 `lexi2016/v4`；开发分支 `v5/module-isolation-20261008`。
- 审查基线：`4a8063eb3ac4bdbbb30bd7659c5a38c4b32e6d28`。
- 必须保留的修正候选：`7115f65267a1496d0ca8214cc14130f8c2b65d87`，原 owner / V4 未改。
- 当前状态：静态候选；产品测试 **NOT_RUN**；Mac **离线**。本包候选复现也未运行，不是已验证 RED。
- 本包不包含真实原始材料、行情、账号、凭据、完整本地目录或运行日志；上传本包不表示已联系外部 Chat 或获得回复。

## 已知问题

原 `domains.research._dedupe_tuple` 使用 stock_code/code、source_title/title、url/source_url、source_path、source_name/source_type、claim_type or evidence_level，逐项 strip/lower 后以 U+001F 拼接。原 builder 计算 dedupe_key=SHA256(canonical_key)，article_id=SHA256(archive_date + U+001E + canonical_key)。archive v1不保留claim_type；当前v2 importer只接收archive_v1与capture，不能保证还原原始去重元组。

原v1 validator对两个身份键只核64hex及唯一性；v2 enrich没有用原builder重新证明它们。当前status路径SHA已核对，正文/URL/主体/原页时间已有另一套独立绑定，因此这是身份元数据来源证明缺口，不能据此断言任意US业务关系可注入。`archive_input_v1`的SHA仅绑定收到的archive字节，不能证明它由正确原builder输入生成。

7115f652已加入发布时间微秒、显式response group及status相对路径绑定修正；不得回退这些修正。`before-after.patch`和`SOURCE_SHA256.json`给出精确范围/前后SHA。

## 合成最小复现

在固定7115f652源码checkout根目录，把本包放在 `handoff/v5-article-identity-20261010`。使用现有独立Mac测试任务及隔离完整原源码；不要真实采集。原依赖由 `V5/producers/archive-acquisition-v2/manifest.json` 的 `test_dependency_sha256` 检查。下面只运行指定3项，避免继承基类后意外扩展整套测试：

```bash
V5_ARCHIVE_PRODUCER_SOURCE_ROOT=/ABS/EXISTING_ISOLATED_FULL_SOURCE \
PYTHONPATH=V5/src:V5/tests:handoff/v5-article-identity-20261010 \
python3 -B -m unittest \
 test_identity_gap_candidate.IdentityGapCandidate.test_control_valid_capture_is_accepted \
 test_identity_gap_candidate.IdentityGapCandidate.test_article_id_mutation_must_be_rejected \
 test_identity_gap_candidate.IdentityGapCandidate.test_dedupe_key_mutation_must_be_rejected -v
```

每项独立setUp/临时目录，使用现有合成页/正文/分类器fixture，外部CLI替换为合成CompletedProcess。control应成功；另两项仅变异一个合法64hex身份键，期望拒绝但当前静态路径预测仍接受，因此是RED候选。必须先看到control成功，且变异失败点确为“unexpectedly accepted”，才能确认漏洞复现；依赖缺失、时间/路径门禁、其他拒绝不得算作RED证明或修复成功。保留实际原拒绝理由。

## 内容导航

- `REPAIR_REQUIREMENTS.md`：缺失输入、最小修复边界和验收要求。
- `test_identity_gap_candidate.py`：3项合成候选，不含真实输入。
- `source/`：9个按固定commit导出的必要源码/依赖清单快照，仅供定位；执行依赖完整固定checkout。
- `SOURCE_SHA256.json`：基线/候选及逐源码前后SHA。
- `PACKAGE_SHA256.json`：除自身与zip外每个交付文件SHA。
- `article-identity-question.zip`：同一包的便携副本，不包含自身。

需要的答复是可评审补丁、原owner接口选择及RED/GREEN候选；未拿到实际同批builder输入前，继续标记来源证明未闭合。自然运行仍不得从合成、手工恢复或离线测试升级为true。
