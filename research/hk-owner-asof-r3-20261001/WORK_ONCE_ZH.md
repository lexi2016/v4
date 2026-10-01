# Mac 一次接续

业务目标：仅打通原HK owner→原publisher→shared→projector→Stage输入，价格日与资格as-of分开；A收尾不重做。

## 1. 取回固定代码而非覆盖活动目录

本批GitHub未推送，输入PR19固定3ed。`GIT_DELIVERY.json`给出本地commit、branch、bundle SHA；完整对象文件包含在ZIP，或使用单独bundle链接。bundle是以3ed为先决对象的增量包，不是新的运行环境。

在已授权的原Git仓库执行（只是源码导入/提交，不部署）：

```sh
git fetch origin codex/stage-hk-status-handoff-20261001
git cat-file -e 3ed9e89a1de1616d89ddbe166484227b5fcd42fa^{commit}
git bundle verify "$PACKAGE/V4_HK_OWNER_ASOF_R3_20261001.bundle"
git fetch "$PACKAGE/V4_HK_OWNER_ASOF_R3_20261001.bundle" \
  refs/heads/codex/hk-owner-asof-r3-20261001:refs/heads/codex/hk-owner-asof-r3-20261001
```

`git rev-parse`必须等于GIT_DELIVERY的commit。该Git提交只新增交付目录，不修改PR19冻结来源。

## 2. 选择唯一前像，隔离应用

先读本机上位AGENTS。在非活动目录操作，即使现役目录名含candidate也禁止写入。

- canonical编辑树：核`canonical/before`每文件SHA，只用`canonical/runtime.patch`，其HK-only日历已包含frozen_r2，不再叠加旧r2整包。
- 实际owner适配：分别核`active/before/preselection_app`、`shared_package`、`stage_app`。只在三个独立镜像中分别用`active/preselection_app.patch`、`active/shared_package.patch`、`active/stage_app.patch`。它们与总`active/runtime.patch`是二选一，不能叠加。
- 已等于目标after直接复用；第三个SHA按单文件差分审查，不自动覆盖。活动shared的native读取证据/scoring必须保留。active/catalog只改preselection策略，六项旧drift不统一到canonical。

```sh
git -C "$ISOLATED_PRESELECTION" apply --check "$PACKAGE/active/preselection_app.patch"
git -C "$ISOLATED_PRESELECTION" apply "$PACKAGE/active/preselection_app.patch"
git -C "$ISOLATED_SHARED" apply --check "$PACKAGE/active/shared_package.patch"
git -C "$ISOLATED_SHARED" apply "$PACKAGE/active/shared_package.patch"
git -C "$ISOLATED_STAGE" apply --check "$PACKAGE/active/stage_app.patch"
git -C "$ISOLATED_STAGE" apply "$PACKAGE/active/stage_app.patch"
```

不自动更新任何活动manifest/pin/plist，不停旧服务。非活动候选的明确依赖清单和实际模块SHA仍由原构建流程审核；不全量复制dirty工作区。

## 3. 一次针对性独立验收

将`tests/test_hk_owner_asof_r3.py`置于完整隔离应用测试目录。测试的active适配夹具仅复现原r9 facade函数绑定，不是业务源码修改。

```sh
cd "$ISOLATED_PRESELECTION"
HK19_VARIANT=active "$SERVICE_PYTHON" -m pytest \
  tests/test_hk_owner_asof_r3.py -q --tb=short \
  --junitxml="$REVIEW_OUT/hk_owner_asof.xml" \
  > "$REVIEW_OUT/hk_owner_asof.stdout.txt" \
  2> "$REVIEW_OUT/hk_owner_asof.stderr.txt"
echo "$?" > "$REVIEW_OUT/hk_owner_asof.exit"
```

当前载体需要把实际`ISOLATED_SHARED`作为原`upstreams/v3_shared_data`包、Stage reader作为同应用原Stage模块显式装配。不要用作者缓存publisher/universe替换Mac原件。先读`TEST_DEPENDENCY_LIMITS.json`，核实际原publisher、`scripts/live_acquisition/universe.py`、原shared store/allowlist及Stage reader路径/SHA，按原count/plate合同使用合成成员；若报真实依赖合同差异保留失败，不改count凑通过。原HK模型专用Python绑定不动。

保存stdout/stderr/exit/JUnit以及这次实际模块SHA；未变化已验项引用，不跑全仓、不重跑A144517项或五个A阶段。允许的合成Futu替身不代表自然source；测试不启动真实Futu/Stage/provider。测试真实文件保全对象是临时目录合成A池，真实Mac A数据只做另行授权的只读前后比对。

## 4. 实际完成标准，当前均未宣称通过

仅在原自然owner的合法时段与有效来源具备后另行验收，不在本次执行真实采集。

同一目标的可用HK结果须价格日=目标前一HK证券日；qualification为原publisher返回的真实来源日/capture，master与原成员列表交叉一致；shared、projector、Stage验证同一run/各种SHA。不可用来源要显示CANNOT_CONFIRM，不能以HTTP200/100行替代来源正确。

9/30创建的10/8池即使READY100，也不能当10/7自然刷新。遇same-target immutable冲突不调用隐藏reset、不覆盖；先保留原run/manifest/receipt/SHA，由Mac按原批准流程决定冲突处理，不以本候选授权替代。

真实已有A池、receipt及共享manifest中A条目须与只读前像一致。普通API/阶段页须读同一源根、date/stage/market/run/hash/行序，并保留NO_BUY等实际字段；UI本批未改、未验。实际natural parent、worker加载、Stage selection/API/UI均需独立证据。

## 5. 源码推送与Draft PR

仅在代码导入身份核对后，可由Mac上传已固定提交（不合并不部署）：

```sh
git push origin codex/hk-owner-asof-r3-20261001
gh pr create --draft --head codex/hk-owner-asof-r3-20261001 \
  --base codex/stage-hk-status-handoff-20261001 \
  --title 'fix(hk): original owner publisher and verified eligibility as-of' \
  --body-file "$PACKAGE/PR_BODY.md"
```

如原GitHub界面建PR更合适，使用同base/head与PR_BODY。禁止推main或自动合并。当前Chat没有执行这些写操作，不能填不存在的PR号。

## 6. 回退

只在同一隔离镜像核after SHA后用对应`*.rollback.patch`，不删除/改写任何source、pool、receipt、authority、latest、历史capture或服务配置。canonical/active不能交叉回退。A1445原包本批不安装，不借09:25额度，不跨日延长任何历史授权。
