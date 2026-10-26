# 生命周期防重复补采 · Writer交接

状态：`FROZEN_FOR_ONE_FINAL_REVIEW_NOT_INSTALLED`。源码/候选已备，实际接入待一次独审、现役Graph owner协调及共享scheduler最终授权。所有code/data/PASS在此交接后冻结。

根因位于现役 `a_share_daily_sync` 组件的 `_run_sync_body`：原collector前没有消费已接受摘牌事实。原链是 Main scheduler `_research_panel_daily` → `macos_research_panel_daily_authority` →固定a_daily严格shim→组件facade→workflow。现在同一入口在provider前判定已验证市场/代码/生效日事实；有效摘牌记 lifecycle_skip，保留原QUARANTINED/REBUILD_REQUIRED分类、target分母/accepted门槛5000，不把skip做READY、不抹旧TIMEOUT、不造bar、不改unknown600193。

实际业务差异仅五文件及一测试：`ops/a_share_daily_sync.py`、`ops/_a_share_daily_sync_parts/sync_workflow.py`、新collector事实JSON、现有API事实JSON及其getter SHA常量、`tests/test_mac_lifecycle_retry_guard.py`。`SOURCE_DELTA.patch`相对精确现役preimages；W中的其他未跟踪helper/caller均原字节依赖，见SOURCE_CUSTODY而不是额外业务实现。API资产增加601198/601059，二者20261019摘牌；原19事实保留，collector使用独立truthful usage说明，非PIT首次认证。

检查已完成且不重跑：601198原loader路径强报错provider哨兵0调用，native及旧TIMEOUT原字节保留；同代码21事实+1正常current样本，target22/accepted1/quarantine21、technical0，原authority仍REBUILD_REQUIRED；日期前/未知/非成员/市场不匹配维持原路。针对性pytest15 passed。严格新shim实际原loader、15 pins/seed/preimage、网络审计零调用另通过。000523六日真实已接受缓存/API core envelope与原保存件完全一致，0公式/0provider，不重算76。初版API原dispatcher和fresh Graph基线R2原dispatcher均exit0；fresh1319文件仅2差异、其余1317与六项Graph变化机械全保全。

候选：新组件不覆盖旧a_daily，Main881物理文件逐字节保全、只改外层绑定identity/provenance，避免外层旧清单失真。最新API标准候选基于fresh `runtime-graph-repair-20261026-api-r2`，没有回退并行Graph工作。精确SHA/路径看 `IDENTITY.json`、三个control包JSON；Root动作看 `ROOT_ACTIONS.md`。

首错保留：remote6551不可本地解析，使用现有55基线+精确现役source custody；旧API投影fresh CAS发现并行变更而拒绝，旧包/控制/日志原样保留，未覆盖现役。Root授权后以fresh c4f1/ec095完成新R2候选。当前原API integration严格不支持active custom schema，未扩大schema/伪造标准基线；该接口与Graph config的Main/API path对应须由Root协调原owner。共享scheduler必须reload才能获得新env，Writer未绕过它；旧Graph能力分层不虚称整体PASS。

运行命令及输出：`canary_601198.py`、固定Python `-m pytest -q -p no:cacheprovider tests/test_mac_lifecycle_retry_guard.py --basetemp=<本目录>/test_tmp_r1`、`prepare_candidates.py`、`validate_fixed_candidate.py`、`prepare_main_metadata.py`、`prepare_api_fresh_r2.py`。全使用固定Python-B与两旗，输出日志/原件均在本目录。未执行provider真实请求、采集、76/5538重算、服务/计划任务/权限动作、commit/push。

最后只需一次独审本源码+实际证据+完整候选+控制边界；review不是安装/HTTP/UI/自然运行证明。安全旗持续 RESEARCH_ONLY=true，production_allowed=false，buy_gate_updated=false，orders_sent=false。
