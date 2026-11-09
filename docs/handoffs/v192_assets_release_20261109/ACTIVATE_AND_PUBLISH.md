# Root activation, rollback and existing module publication

Use the real independent incremental receipt with PASS/REVIEWED/PASS and packet_sha256 exactly `4f5ce4b9c2a06621d46707bee28e0d2bf46acd3225145684663ad7539ddbe945`. Healthy Main jobs/children must finish; do not terminate them. Main/Stage/API live-before CAS is the deployed V192 R2 tuple.

```sh
PYTHONPATH=/Users/lexi/.codex/worktrees/v192-assets-release-20261109 '/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v4-mac/bin/python' -B -m ops.activate_daily_materials_release --packet '/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/v4-v192-assets-20261109-r1/PACKET.json' --review '<absolute reviewed receipt>'
```

The same command with `--rollback` restores deployed R2 service/policy tuple only; it never reverts business data. Inspect ACTIVATION_RECEIPT.json. The tool verifies source/locators/full dependency tuple, acquires DEFAULT+A_LONG, rejects Main descendants, then drains original PIDs/descendants before replacement and bootstrap. It releases every lock before returning.

Only after successful activation and lock release, use the existing owner completion module from the actual candidate Main app. The following Root-only snippet performs the exact business handoff prepare/publication steps with actual Main profile; it was NOT executed by release Writer:

```python
from pathlib import Path
import json, os, plistlib, subprocess
packet=json.loads(Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/v4-v192-assets-20261109-r1/PACKET.json').read_text())
main=packet['services']['main']
env=dict(os.environ, **plistlib.loads(Path(main['draft_plist']).read_bytes())['EnvironmentVariables'])
runtime=Path(env['V4_RUNTIME_ROOT'])
PANEL_PYTHON=runtime/'venvs/v4-mac/bin/python'
env['PYTHONPATH']=main['app_root']+':'+str(runtime/'venvs/v4-mac/lib/python3.14/site-packages')+':'+env.get('PYTHONPATH','')
publication=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/v4-v192-assets-20261109-r1/publication_after_review')
common=[str(PANEL_PYTHON),'-B','-S','-m','ops.complete_workbench_v192_assets']
subprocess.run(common+['prepare-publication','--descriptor','/Users/lexi/Desktop/学习/agents调试/v4_daily_materials_release_repair_20261109/v192_assets/PREPARED_DESCRIPTOR.json',
    '--root','/Users/lexi/Desktop/学习/因子工厂/research/a_daily_update_path_20261029_r1/dashboard_completion_r1/today_full_r1/daily_products/a_share',
    '--stage',str(publication),'--lock','/Users/lexi/Library/Application Support/com.lexi.v35.local/state/dispatcher/scheduler_lane_owners/A_LONG.lock'],
    cwd=main['app_root'],env=env,check=True)
subprocess.run(common+['publish','--plan',str(publication/'PUBLICATION_PLAN.json')],cwd=main['app_root'],env=env,check=True)
```

This reuses original A_LONG inode/CAS and current index/event snapshot. Changed CAS must be diagnosed and re-prepared, not overwritten or merged blindly. Keep the durable17 asset root referenced by module195af9. Then verify actual603286 graph2256bars/51/22,3of5 and both research contexts, selected301361/301199 if needed,all17 coverage,and native371 descriptor unchanged. NewMain natural numeric/preselection completion remains a future receipt gate, not proved by manual publication.
