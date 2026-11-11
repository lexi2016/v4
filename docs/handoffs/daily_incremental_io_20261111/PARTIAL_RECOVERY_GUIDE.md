# D11 显式恢复引用：接入方受控步骤（本批未执行）

本步骤只准备一个小型、不可覆盖的恢复描述符，不运行公式、采集、物化或发布。必须先按原正式 release/source-pin 流程接入两个已审 patch，并使调用进程正常从新 release 导入原模块；本文不授权部署。不得把候选模块注入旧 Main 的 `sys.modules`、改旧 manifest，或删除/关闭 policy env 来“接上”。

原旧 release 继续只读保存，作为真实 `source_core`。旧 core SHA 必须为 `7b1f6b4ef739c7074cfcb1e4b1fda6910d4c02e70f8bf5bf653aaf696a95ca13`；新 QFQ SHA 必须为 `1cec9399c5b41c9d402c51650936ea4a9947402052d4a2f8ad256004c1d568be`。新 authority SHA 为 `ef543bb0de814c2a25ed28f9ae2d1e30d3cbb68b7fae34d1a419ea6873cd6429`。新 publication 身份使用新 SHA，原 chunk 始终保留旧 fingerprint。

使用已批准、身份封签的新 app 为 cwd，以及既有绝对生产 Python 的 `-B`；完整原环境保持。以下代码由接入方在满足这些前提后单独执行。`output` 要使用本任务证据目录内新的名字；已有同名文件时停止并核对原 ID/内容，不覆盖、不盲重试。代码只枚举已确认的 D11 原 checkpoint 目录，不搜索其它 run，不复制原文件，不重新 hash 全市场行情或旧主面板。

```python
from pathlib import Path
import json, os
from ops import research_panel_qfq as q
from ops.research_panel_turnover import load_daily

app = Path.cwd().resolve()
expected = {
    'ops/research_panel_qfq.py': '1cec9399c5b41c9d402c51650936ea4a9947402052d4a2f8ad256004c1d568be',
    'ops/macos_research_panel_daily_authority.py': 'ef543bb0de814c2a25ed28f9ae2d1e30d3cbb68b7fae34d1a419ea6873cd6429',
}
manifest_ref = dict(path=os.environ['V4_RELEASE_MANIFEST_PATH'],
                    sha256=os.environ['V4_RELEASE_MANIFEST_SHA256'])
manifest = json.loads(q._source(manifest_ref, owner='approved release manifest').read_text())
assert Path(manifest['app_root']).resolve() == app
inventory = {r['path']: r['sha256'] for r in manifest['application_inventory']['entries']
             if r.get('kind', 'file') == 'file'}
assert Path(q.__file__).resolve() == app / 'ops/research_panel_qfq.py'
for relative, digest in expected.items():
    assert q.sha(app / relative) == inventory[relative] == digest

base = Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/state')
data = base / 'workspace/数据'
run = base / 'research_panel_daily/a_formula_runs/qfq_5b6da037da39fae667c1'
snapshot_path = run / 'adjustment_input_snapshot.json'
snapshot = json.loads(snapshot_path.read_text())
assert snapshot['asof_date'] == 20261111
assert snapshot == json.loads(q.input_path(data).read_text())
old_core = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/v4-panel-daily-source-fix-20261111-r2/v4-panel-daily-source-fix-20261111-r2-main/app/ops/research_panel_qfq.py')
assert q.sha(old_core) == '7b1f6b4ef739c7074cfcb1e4b1fda6910d4c02e70f8bf5bf653aaf696a95ca13'
formula = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/workbench-daily-chain-20261031-r6-main/app/components/a_formula/build_canonical_formula_research_panel.py')
contract = Path('/Users/lexi/Library/Application Support/com.lexi.research-panel.local/releases/20260821T073000Z-v35-hk0920-materialization-bridge/app/runtime/v1/authoritative_field_contract_v0.csv')
identity = q.generation_identity(snapshot, app / 'ops/vendor/data_layer_daily_formula_increment_update_v1.py',
                                 formula, contract)
turnover = load_daily(data, base / 'research_panel_daily/tdx', 20261111)
assert turnover.failure is None
identity['turnover_input_sha256'] = turnover.identity
old_identity = {**identity, 'adapter_sha256': q.sha(old_core)}

prior = json.loads((base / 'research_panel_daily/a_formula_runs/qfq_231df8b469ade0ba8e62/candidate_receipt.json').read_text())
pointers = {
    'selector': data / 'data_layer_interface_current/CURRENT_SELECTOR_READY_PANEL.txt',
    'backtest': data / 'backtest_panel_interface_current/CURRENT_BACKTEST_BASE_PANEL.txt',
}
for role, pointer in pointers.items():
    path = Path(pointer.read_text(encoding='utf-8-sig').strip())
    assert str(path) == prior['candidates'][role]
    assert q.panel_contract(path)['generation_id'] == prior['generation_id']
baseline = prior['candidate_sha256']
assert q.canonical_sha(dict(target=20261111, baseline_panel_sha256=baseline, **old_identity)) == \
    '5b6da037da39fae667c1d2eb224a5c56268c6574821ef8c6345e2ffd87d7df14'

chunks = {}
for receipt_path in sorted((run / 'symbol_checkpoints').glob('*.receipt.json')):
    assert not receipt_path.is_symlink()
    code = receipt_path.name.removesuffix('.receipt.json')
    assert code in snapshot['symbols']
    path = receipt_path.with_name(code + '.parquet')
    assert path.is_file() and not path.is_symlink()
    receipt = json.loads(receipt_path.read_text())
    fingerprint = q.canonical_sha(dict(code=code, item=snapshot['symbols'][code], **old_identity))
    assert receipt['checkpoint_id'] == q.panel_contract(path)['checkpoint_id'] == fingerprint
    chunks[code] = dict(artifact=dict(path=str(path), sha256=receipt['sha256']),
                        receipt=dict(path=str(receipt_path), sha256=q.sha(receipt_path)))
assert len(chunks) == 1364
factor_identity = q.factor_cache_identity(data, 20261111, snapshot)
assert factor_identity
descriptor = dict(
    schema='qfq_original_checkpoint_recovery_v1', recovery_scope='D11_PARTIAL_IO_ONLY_V1',
    asof_date=20261111, source_identity=old_identity,
    source_core=dict(path=str(old_core), sha256=q.sha(old_core)), source_run=str(run),
    original_snapshot=dict(path=str(snapshot_path), sha256=q.sha(snapshot_path)),
    factor_cache_identity=factor_identity, baseline_panel_sha256=baseline,
    chunks=chunks, retry_original_quarantined=[], completed_count=len(chunks),
    total_count=len(snapshot['symbols']), prepared_only=True,
    artifact_bytes_verified_by_generator=False, **q.FLAGS)
output = Path('/Users/lexi/Desktop/学习/agents调试/v4_daily_panel_futu1112_20261111/D11_PARTIAL_RECOVERY_1364_PREPARED.json')
with output.open('x', encoding='utf-8') as stream:
    json.dump(descriptor, stream, ensure_ascii=False, sort_keys=True, indent=2)
    stream.write('\n')
print(json.dumps(dict(path=str(output), sha256=q.sha(output), status='PREPARED_NOT_VALIDATED')))
```

这里 `old_identity` 不是伪装新代码身份：它是旧 run 的计算身份，必须精确重现原 `5b6da037…`，只用来认证旧 chunk。新原 owner 仍用真实新 adapter 生成 publication 身份。生成器从原回执取 artifact SHA，尚未认证文件字节；这是避免在控制脚本和原 owner 中重复全量 hash 的准备清单。**原 owner 首次消费时仍须逐份 `_source` 校验全部 artifact/receipt 字节 SHA、精确输入和数学身份，缺项继续原算，错源停止。1364 数量若变、原指针改变或任一前提不符，停止并保留差异，不能为凑数改断言。**

接入方将生成器返回的小型 `{path, sha256}`，作为 `checkpoint_resume` 显式传给新 release 中正常导入的 `run_windows_a_formula_authority`；其余 kwargs 沿现役 catalog 的原公式参数、`formula_max_workers=4`，完整 env 及 `run_with_retention` 不变。不要直接调用未登记 candidate 文件，也不要调用 `run_daily_rebuild` 绕过原 authority/retention。原 storage admission 拒绝时保持原失败，不盲重试、不清理或放宽 policy。只有原 owner READY 后才允许原 daily product 后续阶段。

本指南为准备/接线方法，未执行生成器、未逐份验收 1364、未运行任何 live producer 或发布。
