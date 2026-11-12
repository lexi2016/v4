"""Prepare only a sparse live-base delta. Never edits an active app or store."""
import ast
import difflib
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = Path('/Users/lexi/.codex/worktrees/v192-source-binding-20261112/v4_app')
MAIN = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/v4-storage-compaction-20261112-r1/main/app')
SHARED = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/hk-tdx-conflict-repair-shared-20261015-r4/app/upstreams/v3_shared_data')
OUT = HERE / 'runtime_delta_r3'


def sha(raw): return hashlib.sha256(raw).hexdigest()

def one(text, before, after):
    if text.count(before) != 1: raise ValueError('EXACT_DELTA_ANCHOR_CONFLICT:' + before[:80])
    return text.replace(before, after, 1)

def function(text, name):
    tree = ast.parse(text)
    node = next(n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
    return '\n'.join(text.splitlines()[node.lineno-1:node.end_lineno])


def main():
    OUT.mkdir(exist_ok=False)
    records=[]; patches=[]
    def emit(root, relative, after):
        target=OUT/root/relative; target.parent.mkdir(parents=True,exist_ok=True)
        base=(MAIN if root=='main' else SHARED)/relative
        before=base.read_text() if base.exists() else ''
        target.write_text(after)
        ast.parse(after)
        records.append(dict(root=root,path=relative,before_sha256=sha(before.encode()) if before else None,
            after_sha256=sha(after.encode()),source=str(base),prepared=str(target)))
        patches.extend(difflib.unified_diff(before.splitlines(True),after.splitlines(True),
            fromfile='a/'+root+'/'+relative,tofile='b/'+root+'/'+relative))
    # Existing module is absent from the live Main; its new source helper is
    # reused unchanged from the isolated V4 task source, not a new producer.
    emit('main','infrastructure/formula_generation.py',(SOURCE/'infrastructure/formula_generation.py').read_text())
    emit('main','ops/materialize_shared_v192_preselection.py',(SOURCE/'ops/materialize_shared_v192_preselection.py').read_text())
    relative='ops/daily_materialize.py'
    live=(MAIN/relative).read_text(); updated=(SOURCE/relative).read_text()
    # Preserve live signature/imports and all unrelated stages. Only replace
    # the matching resolver's legacy body below its already-existing root.
    old=function(live,'resolve_selector_panel'); new=function(updated,'resolve_selector_panel')
    start=new.index('    def _max_trade_date(')
    before=old[old.index('    def _max_trade_date('):]
    emit('main',relative,one(live,before,new[start:]))
    relative='infrastructure/scheduling/executor_registry_preselection.py'
    live=(MAIN/relative).read_text()
    live=one(live,'                "--target-date", request.target_date,\n            ],\n            cwd=self.repo_root,',
        '                "--target-date", request.target_date,\n                *(["--source-panel", str(selector)] if selector is not None else []),\n            ],\n            cwd=self.repo_root,')
    needle='            if market == "HK":\n                if payload.get("status") not in'
    addition='''            if market == "A":
                try:
                    from contracts.trading_calendar import load_market_calendar, previous_session
                    from infrastructure.formula_generation import verify_v192_current_source, verify_v192_native_cache_identity
                    from infrastructure.isolated_package_loader import load_isolated_package_module
                    signal_date = previous_session(load_market_calendar(), trade_date, market="a_share")
                    module = load_isolated_package_module(self.shared_package_root,
                        package_directory="shared_data", module_leaf="v192_selector",
                        namespace_prefix="v192_nonempty_cache_gate")
                    verified = module.read_verified_v192_pool(self.shared_data_root,
                        target_date=trade_date, expected_signal_date=signal_date)
                    verify_v192_current_source(verified, self.selector_data_root, signal_date=signal_date)
                    verify_v192_native_cache_identity(payload, verified)
                except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
                    self._v192_source_reuse_conflict = str(error)
                    return None  # exact original producer path retains the source conflict
            if market == "HK":
                if payload.get("status") not in'''
    live=one(live,needle,addition)
    emit('main',relative,live)
    relative='infrastructure/preselection_pool_store.py'
    live=(MAIN/relative).read_text()
    method=function((SOURCE/relative).read_text(),'refresh_verified_v192_source') if False else None
    tree=ast.parse((SOURCE/relative).read_text());cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='PreselectionPoolStore')
    node=next(n for n in cls.body if isinstance(n,ast.FunctionDef)and n.name=='refresh_verified_v192_source')
    method='\n'.join((SOURCE/relative).read_text().splitlines()[node.lineno-1:node.end_lineno])+'\n\n'
    live=one(live,'    def materialize(self, payload: Mapping[str, Any]) -> dict[str, str]:',method+'    def materialize(self, payload: Mapping[str, Any]) -> dict[str, str]:')
    emit('main',relative,live)
    relative='domains/preselection_materializer.py'
    live=(MAIN/relative).read_text()
    live=one(live,'    artifact["source_run_id"] = str(verification["run_id"])',
        '    artifact["source_run_id"] = str(verification["run_id"])\n    artifact["source_manifest_sha256"] = str(verification["manifest_sha256"])\n    artifact["source_receipt_sha256"] = str(verification["receipt_sha256"])')
    emit('main',relative,live)
    relative='shared_data/v192_selector.py'; live=(SHARED/relative).read_text(); updated=(SOURCE/'upstreams/v3_shared_data'/relative).read_text()
    # Transplant only the unchanged producer's I/O wrappers. Oracle execution,
    # roles, scoring and all source SHA constants remain live-base bytes.
    for name in ['publish_v192_rows','_date_bounded_panel_for_oracle','_read_selector_panel_source_rows','materialize_frozen_v192_selector']:
        old=function(live,name); new=function(updated,name)
        # Live oracle publishing has no local-bundle additions. Keep its exact
        # body and add only source identity and original-store CAS parameters.
        if name=='publish_v192_rows':
            new=one(old,'    oracle_sha256s: Mapping[str, str],\n)',
                    '    oracle_sha256s: Mapping[str, str],\n    historical_backfill: bool = False,\n    expected_previous: Mapping[str, Any] | None = None,\n)')
            new=one(new,'    if signal_date >= target_date:',
                '    if historical_backfill and (not isinstance(expected_previous, Mapping) or set(expected_previous) != {\n            "run_id", "artifact_sha256", "manifest_sha256", "receipt_sha256",\n            "artifact_relative", "manifest_relative", "receipt_relative"}):\n        raise StoreError("v1.9.2 historical repair requires complete expected_previous identity")\n    if signal_date >= target_date:')
            new=one(new,'source_id="fmla04_v192_frozen_selector",','source_id="fmla04_v192_frozen_selector_" + panel_sha256,')
            new=one(new,'            stage_id=V192_STAGE_ID,\n        )',
                '            stage_id=V192_STAGE_ID,\n            historical_backfill=historical_backfill,\n            expected_previous=expected_previous,\n        )')
        live=one(live,old,new)
    emit('shared',relative,live)
    relative='shared_data/store.py';live=(SHARED/relative).read_text()
    emit('shared',relative,one(live,'if historical_backfill and existing.get("status") == READY:',
        'if historical_backfill and existing.get("status") in {READY, READY_EMPTY}:'))
    (HERE/'RUNTIME_DELTA_R3.json').write_text(json.dumps(dict(status='PREPARED_NOT_ACTIVATED',
        source_root=str(SOURCE),main_base=str(MAIN),shared_base=str(SHARED),entries=records,
        api_changed=False,oracle_sources_changed=False,shared_store_written=False),indent=2)+'\n')
    (HERE/'RUNTIME_DELTA_R3.patch').write_text(''.join(patches))
    print(json.dumps(dict(status='PREPARED_NOT_ACTIVATED',files=len(records))))

if __name__=='__main__':main()
