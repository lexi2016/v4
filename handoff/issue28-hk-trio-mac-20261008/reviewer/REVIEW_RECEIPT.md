# 独立验收回执：Mac HK 物理三件套候选

**身份与边界：** `/root/hk_trio_mac_review`，独立于 Writer；只审查冻结候选 `stage_center/_runner_parts/hk_input_validation.py`，并在隔离临时目录复跑 targeted harness。未改候选包、业务源码、数据、Git、服务或计划任务。

**Verdict：`REVIEWED / PASS`，限候选合成三件套身份目标。`BEHAVIOR_VERIFIED` 仅限合成输入下的末尾物理 trio / 根目录身份复核。**

**风险分级：** P0 无；P1 无；P2 无可行动缺陷（限冻结补丁）。候选明确只增加一次返回前的完整快照复读，不提供复读之后的事务隔离或跨后续消费者的原子保证。

候选是单文件双 owner 后像。两个冻结前像 SHA256 均为 `92e8fb2be06e6530c33f3cf2f5b44f29b0bcf7875e6a5902260f8be4c814f735`；候选 SHA256 均为 `b20baa18d0ee9748971db835f6fb3dd9a0e1d66aabd8da8d450aee3a4a528a8e`。审查到的关键改动为保留 canonical `PreselectionPoolStore` 实例并在返回前重新读取完整 snapshot，核对 artifact、pool/semantic digest、三份物理文件 SHA、root 和相对路径；读取错误转成 `RunnerError`。`(path, digest)` 返回合同与上游来源身份字段未改。见候选后像第 134–141、245–272 行和补丁文件。

## 独立 focused acceptance

命令：

```bash
TMPDIR=/Users/lexi/Desktop/学习/agents调试/V4_ISSUE28_HK_TRIO_MAC_20261008/reviewer_tmp \
/Users/lexi/Library/Application\ Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python -B \
harness/run_regressions.py --owner both --phase after --suite targeted \
--output-dir /Users/lexi/Desktop/学习/agents调试/V4_ISSUE28_HK_TRIO_MAC_20261008/reviewer_tmp
```

Mac ARM64，Python 3.14.6，pytest 9.1.1；退出码 0。`actual_stage_owner` 15/15 PASS，`canonical` 15/15 PASS；两组均 0 fail、0 error、0 skip。用例覆盖缺失 split-date provenance、旧价格行日期、上游哈希与本地 trio 不可混用、capture-time、primary/secondary 下 manifest 或 receipt 被晚改、合法合成 binding，以及三份字节不变而 root inode 被替换。

独立结果仅写入 `reviewer_tmp/issue28-hk-after-1_rfj136/`：

- `RESULTS.json` SHA256 `00abad7f977b34fb65674792dc589f629c11abf99b2e5ca47febc1f324625326`。
- actual Stage：JUnit SHA256 `c17a120d496ae89ad7101543430c3f8464706539b4986ad172ed5ec74819da1d`；imports SHA256 `149159cc9d3b898e99426071932f7bed8272f1d827523e6a0dd8f4a055901405`。
- canonical：JUnit SHA256 `1e8d2f6dc280ef6e3525393ff415812d49d84900e96c1dfdaaae03b2d25dc4dc`；imports SHA256 `634832a928c32e80f723ec90dd1f533a5cd4cc8c857a8464f7a715b8566e568e`。
- 两份 imports 回执中实际加载的 `stage_center._runner_parts.hk_input_validation` 均为候选 SHA `b20baa18…a528a8e`；actual Stage 与 canonical 的 runner、Store、resolver 均各自来自其精确 owner source slice。

## 现场及验收限制

canonical 与 actual Stage 现场 helper 的只读 SHA 都仍匹配冻结前像。canonical 文件在当前 V4 Git worktree 显示为 untracked；没有更改该文件。

此次 harness 自报 scope 为 `ISOLATED_SOURCE_SLICES_WITH_PINNED_SUPPLEMENTS_NOT_FULL_MAC_RUNTIME`，`runtime_recovery_status=CANNOT_CONFIRM`。因此完整当前 Mac 运行依赖、源码集成、部署、API/UI、自然时段及旧槽恢复均为 `CANNOT_CONFIRM` / `NOT_RUN`。真实 HK 输入也仍 `CANNOT_CONFIRM`：测试 fixture 是合成输入，不能证明 10/07 价格原来源、9/30 Connect 资格与 capture 链已恢复，也不能修正现存 9/30 价格行。原 19 项基线按冻结指示未复跑；它不属于本次 targeted PASS。


## 新增 current dependency closure 复核

**增量结论：`REVIEWED / PASS`，限该隔离 exercised dependency closure；没有新增 P0/P1/P2 finding。`TESTED`：两 owner 各 15/15。`BEHAVIOR_VERIFIED`：仅在合成输入、17 个当前依赖副本加 8 个包内 owner source slices 的闭包中验证三件套身份目标。**

已核对 Writer receipt SHA256 `c1e8b52ee5c57f077775f6c91a9992a2d189c38bd6d06651794c69d8a40d62b5` 与其结果 SHA256 `bf4f504761c19b87721021e44a185e43e23fbb12ef8e8a86891d9941f4ca30ec`。为避免覆盖 Writer 输出，我把其 runner 复制到本 reviewer 目录，仅把 `OUT` 从 `isolated_test/current_dependency_closure_retry` 改为 `reviewer_tmp/current_dependency_closure_review`；两文件 `diff` 只有这一行。复制 runner SHA256 为 `9bffb64f8fa1a6c5586d79e67c476a80acd6916aa7e582c16deb94b4df0908fc`，Writer 原 runner SHA256 为 `4260fa390773d3b52a8a0f5333add6f4341fa68d340efebb948316d3558f6041`。

独立命令：

```bash
/Users/lexi/Library/Application\ Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python -B \
/Users/lexi/Desktop/学习/agents调试/V4_ISSUE28_HK_TRIO_MAC_20261008/reviewer/run_current_dependency_closure.py \
--canonical-root /Users/lexi/Desktop/学习/v4_app \
--actual-stage-root /Users/lexi/Desktop/学习/agents调试/V4_HK_STAGE_RECOVERY_20261003/issue23_runner_helper_r3/stage_r1_binding_candidate_r3/app \
--python /Users/lexi/Library/Application\ Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python
```

Mac ARM64，Python 3.14.6，pytest 9.1.1；退出码 0。actual Stage 与 canonical 各 15/15 PASS，均无 fail/error/skip，candidate helper SHA 均为 `b20baa18…a528a8e`。每个 owner 的克隆输入清单有 30 个文件；我按输出目录中的 `IMPORT_EXPECTATIONS.json` 逐项复算，均为 0 SHA mismatch。各 imports 回执记录 25 个已加载模块，17 个 `CURRENT_OWNER_DEPENDENCY_COPY`、8 个 `EXACT_OWNER_SOURCE_SLICE`；逐项核对已加载路径与 SHA，均为 0 mismatch。

当前与 pinned supplement 不同的依赖均出现在 imports 回执中：actual Stage 的 `stage_center/acquisition.py` 当前 SHA `2806c63dbe76af9051a3ea655356738d45a67205441c03638fd52ca44087fc1b`（pinned `33e5003faed8127ec3393eb36af473c0d63ee3a79843418ef1a950ce7b697397`）、`stage_center/raw_store.py` 当前 SHA `15052b23c62d38b65d65b96bf3b837782ebfa6fca7fe83f7c1d9374400bbdbde`（pinned `2dea717cb65053c48b75468fd61508b3b61b421a6b528aa8ce93395e99aef547`）、`stage_center/scheduler.py` 当前 SHA `db110aba2fe504213591330000120b660cff04292728b5325711e2fa6799e7b0`（pinned `e56651ec7bb481b28e383cb403d60ba48747ddf7426f9fb380f5ae24fc3a37a4`）；canonical 的 `stage_center/contracts.py` 当前 SHA `7741d0b977cc9994a0b526b35d6b3a3586bfb3b6c0b2f09f4cf8f05449c2bb18`（pinned `6880f6a82c7f4fb0fde5c0661bd5a8bb12b590661a4b8552bcb3d6be969ae83d`）。

独立回执只在 `reviewer_tmp/current_dependency_closure_review/`：`RESULTS.json` SHA256 `c63699d4f7cc2db98ab26f7b03a656b01f4d0c9eb48ca7b337a135bd359c3f8f`；actual Stage JUnit/imports SHA256 分别为 `ef3017ce146ae3ae2e890031e507471b28ef5ea76b8254d11f016f8df13791f6` / `4377f2272539e3bc4ce1e0312e9816ef5fe2953e46be2956e68d4a843c6d97aa`；canonical 分别为 `452b50ec60ea0f823ec3f05a60ae581a172e6153f7be372a670389e78076a4e1` / `40b71f3edecc87914ad2cad0e06813f6b558c52879f7490d77f3de7755167201`。

Scope 保持 `ISOLATED_CURRENT_EXERCISED_DEPENDENCY_CLOSURE_NOT_FULL_STAGE_RUNTIME`，而且每 owner 的 8 个 `EXACT_OWNER_SOURCE_SLICE` 仍是本包源码切片。完整 Stage app/service 运行、当前源代码集成、ops/API/UI、真实 HK source validity、部署、自然时段和旧槽恢复继续为 `CANNOT_CONFIRM` / `NOT_RUN`。Writer 首次 wrapper 的 interpreter 错误路径及早先 clone-path 报告更正没有被复用；本次以原 V4 venv 路径在新 reviewer 目录重新运行并独立复算。
