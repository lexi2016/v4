R2已在Mac实际落地检查，现回传精确阻断，请直接交最小适配代码，不再让Mac自行改工具或设计补丁。固定反馈commit 4db264512b71723cb13680c4f7554deef401ef44（父提交就是R2 7a9c94d43a296372488541b02e8e35a0f763dc1a），8份文件已全部远端读回SHA一致：
https://github.com/lexi2016/v4/blob/4db264512b71723cb13680c4f7554deef401ef44/handoff/stage-r2-mac-blockers-20261009/HANDOFF.md
目录包含三份原始prepare JSON、SOURCE_MAP、local_observations，以及本机当前App.vue/runtime.ts完整原字节，缺panel事实已记录。不是再次缺源码的空问题包。

已完成：328个包文件blob全部匹配；包verify PASS；Stage16/16和API2/2全部BEFORE_MATCH，21after SHA匹配。Mac Python3.14.6/Node24.19.0离线Stage148/API82/Vue45共275通过无skip，fresh合成fixture API/Vue通过；这是Writer执行，独立Reviewer复跑进行中，不是假装真实行情/现役API成功。

只剩本机适配阻断：
1. Stage prepare拒绝两个现存symlink。app/v3_shared_data→upstreams/v3_shared_data，为配置引用的内部依赖；app/upstreams/v3.5指向外部既有release且目标存在，是否必须CANNOT_CONFIRM。实际链接文本/完整目标/原错误已给。请修工具为明确、受限的依赖处理，保留路径与来源身份、不写链接目标、不盲跟随任意外部链接，也不全树见symlink就挡死。
2. API源码及stage_center为0555、目标文件0444。copytree保留只读mode后，工具在新副本stage_center创建tmp0pz8q150时报Errno13；这是新副本写权限失败，不是某个已有坏临时目录。原根不改权限，只处理新候选所需写权限并在完成时核字节/权限；旧partial copy留存，重跑用新目标。详见api_prepare.json与lstat。
3. UI实际App.vue SHA ffbfcde222175c7849dfd5a1089cafe6c104dea2a1760b18645d95bc48780530；runtime.ts SHA6d66ae53d26a6c48110d040ad0440bb023e88d49924a697d6671c6da51176d92；StageExecutionEvidencePanel.vue目前不存在。请以已附完整实际源码制作最小patch及新增组件清单，保留已有经理等并行修改；别将缺失的新组件当应存在旧文件。UI树还有现存依赖/pytest临时symlink，按明确源集合处理，不把临时测试目录作为应用依赖或覆盖canonical。

真实HK PyTDX canary因Stage prepare门禁尚NOT_RUN，不是取不到价格。API/UI副本也没准备成功，未发布，actual/canonical/state/plist均未改。不要改算法/研究模式/数据合同，不启API拆分，不另建producer。交R2→适配增量、完整after/前后SHA、对应反例与MAC_APPLY更新，使本机能按交付命令prepare→真实canary→同run API/UI。用户明确：Chat修代码，Mac只执行落地和验证。有新增真正必要证据一次精确列出。

独立Reviewer已完成：Mac 275项fixture全部复跑通过（148/82/45，均无skip），真实canary/API/UI仍NOT_RUN；上述P1准备阻断独立确认。另外P2：tools/run_checks.py仅解析Stage/API passed数量，但PASS判定未强制完整期望数量与零skip（Vue才检查skip），请同时补这项测试工具门槛及反例。本次实际测试数量齐全，不受该缺陷影响。独立报告见同一反馈分支的INDEPENDENT_REVIEW.json。