# 离线恢复源身份加固

基线 3eaf4a5ccc73bb2c368b623509ac4e830a0f1982。仅加固恢复入口，不触碰旧 run、BLOCKED、原 SHA 或正文。云端未运行产品测试。

新增必需输入：`--source-app` 指向已核实的原 874 app；`--identity-sha256` 为父任务只读取得的原 v5_owner_identity.json SHA。不能改写旧身份来满足新校验。

恢复前依次验证：

1. 原 identity 原始字节 SHA、schema、private_root 与实际 source_root 一致；private_parent 为规范绝对路径、真实存在，source 为其严格子目录，路径无链接。
2. identity.source_commit 固定为原成功链 0382f753929365048d231a7252d9c328d40f8522；identity、policy 及全部 policy.history 的 app_manifest_sha256 都匹配固定 874 manifest，history 最后记录须与 policy 顶层一致。
3. 874 manifest 固定 SHA256 为 `7b9e27770331c67734bac30c17cc36a76dba32d34be3cbeed64378eff85384f7`。该值由 git 874 的三个 manifest 与原 assembler 的确定性序列化静态重建，未执行 assembler/产品。完整预期 manifest 在 SOURCE_OWNER_APP_874_MANIFEST.json，共 26 文件。实际旧 app manifest 字节必须匹配，并逐一核对全部原 app 文件 SHA；不接受任意指定 app 或当前新恢复 app 充当原 app。
4. identity.forbidden_roots 必须非空且规范；叠加已知 V4 根。source/output 不得等于、位于其内，或成为其祖先；output 也不得与 source、原 app 重叠，不得为已有目录或含符号链接。

新目录的 OFFLINE_RECOVERY.json 与 recovery_receipt.json 分别明确记录 source_root、derived_root、source_identity_sha256、source_app_root 和 source_app_manifest_sha256。原身份只原样归档到 original，不在新根伪造 v5_owner_identity.json。prepare 还验证 derived_root 与实际恢复根一致。

原 55 项测试文件不变；已有 7 项恢复断言保留，但合成 fixture 明确重绑定临时测试根并仅在测试进程替换合成 app 信任锚，以适配新增必需参数。生产代码没有测试旁路、可配置 manifest 信任锚或放宽分支。新增 6 项负例：错误源 root、identity manifest、policy manifest（即使重新提供 policy SHA）、禁写根子目录/祖先、原 app manifest 字节变化、原 app 文件变化。该文件现在 15 项，总计 70 项待 Mac 验收。

```bash
shasum -a 256 -c SHA256SUMS || exit 1
python3 -B -I tests/test_offline_evidence_recovery.py > recovery-identity-validation.log 2>&1
RC=$?
cat recovery-identity-validation.log
printf 'recovery_identity=%s\n' "$RC"
test "$RC" -eq 0
```

实际离线恢复沿用 OFFLINE_RECOVERY.md，但增加两个参数：

```bash
python3 -B -I "$RECOVERY_APP/ops/recover_announcement_evidence_offline.py" \
  --source-root "$OLD_PRIVATE_STATE" --source-app "$OLD_874_APP" \
  --output-root "$NEW_OFFLINE_RECOVERY" \
  --run-id 16cc60afcb089f11690430b05853114c \
  --policy-sha256 "$READONLY_POLICY_SHA256" \
  --batch-sha256 "$READONLY_BATCH_RECEIPT_SHA256" \
  --identity-sha256 "$READONLY_IDENTITY_SHA256"
```

旧 app 或 identity 不符合固定值即停止；不得修改它们、放宽信任锚、删除 BLOCKED 或重新采集。旧 3eaf 恢复命令缺少新增身份参数，不能继续使用。全部真实阅读仍需覆盖 392 条，不生成 semantic 或复用审查结论。

## 同轮 Mac 实际失败与 JSON 类型修复

父任务返回 3eaf 新增恢复用例实际执行 0 项、exit1：类属性 cls.run 覆盖 unittest.TestCase.run，TypeError: str object is not callable。现最小改名为 run_id 并更新引用，保留既有断言。原 55 项在 3eaf 独立 55 PASS，不能把恢复文件的加载当成测试通过。

原 Python JSON 对象 == 会把 false/0、true/1 视为相同。恢复入口改为递归类型严格比较（dict 键集合、list 顺序/长度、每层 type 与值），然后仍检查原 SHA。新增真实 manifest 字段 physical_network_bytes_verified false→0 负例，即使更新合成旧 capture SHA 且普通 Python 相等仍成立，必须拒绝；另覆盖嵌套 false/0、true/1、int/float 与相同结构正例。生产旧证据不作任何修改。

本轮 shell git HTTPS 认证不可用；已通过现有 GitHub 连接器只读确认同一分支与基线，现有连接器 tree 写入经两次自动审批均被拒绝，故本轮仅生成本地固定提交和交付，不增加凭据或绕过拒绝。
