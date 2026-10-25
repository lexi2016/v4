"""Finite optional-override isolation; original SelectionStore validation stays intact."""
from __future__ import annotations
import ast
import difflib
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import types

OUT = Path('/Users/lexi/Desktop/学习/因子工厂/research/a_share_v4_stage_history_restore_20261025')
RUNTIME = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/a-share-stage-history-restore-20261025-r2/app')
SELECT = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/state/stage/selection')
EXPECTED_BASE = 'd62706882d52d0f1388afc44bc454fc1b17638de73a4d3d79dcc650ccb74d433'
EXPECTED_SCOPE = '810f85c2528c0ba5268d21db4729052555d30d03ebf57c90e2c81a1888a0c75c'
OLD_TARGETS = '''                ("20260929", "STAGE_1445_1500"),
                ("20260930", "STAGE_1445_1500"),'''
OLD_GUARD = '''            except ResearchReadError as error:
                raise HTTPException(status_code=409, detail="approved research read binding is unavailable or invalid") from error
'''
NEW_GUARD = '''            except ResearchReadError as error:
                # The optional research package covers BOTH A and HK. Its
                # rejected A is never authenticated by this fallback: read the
                # independent ordinary A trio through the unchanged verifier.
                if (selected, stage) == ("20261009", "STAGE_0930_0935") and (
                    market is None and backfill_run_id is None
                    and shared_selection_consumer is not None
                ):
                    ordinary = shared_selection_consumer.get(
                        selected, stage, markets=("A_SHARE",), allow_backfill=True
                    )
                    a_market = (ordinary.get("markets") or {}).get("A_SHARE")
                    if isinstance(a_market, Mapping) and (
                        a_market.get("selection_manifest_receipt_verified") is True
                        and int(a_market.get("selected_rows") or 0) > 0
                        and len(a_market.get("rows") or []) == a_market["selected_rows"]
                    ):
                        from stage_center.consumer import _invalid_market_with_reason
                        denied = _invalid_market_with_reason(
                            "HK_CONNECT", "APPROVED_RESEARCH_BINDING_INVALID"
                        )
                        denied["cannot_confirm"].append(str(error))
                        result = dict(ordinary)
                        result["markets"] = {"A_SHARE": a_market, "HK_CONNECT": denied}
                        result.update(artifact_id=None, bundle_artifact_id=None, run_id=None)
                        result["optional_override_failure"] = {
                            "scope": ["A_SHARE", "HK_CONNECT"],
                            "reason": str(error),
                            "fallback": "INDEPENDENT_VERIFIED_ORDINARY_A_TRIO_ONLY",
                            "rejected_research_A_used": False,
                        }
                        execution = dict(ordinary.get("execution_evidence") or {})
                        execution_markets = dict(execution.get("markets") or {})
                        execution_markets["HK_CONNECT"] = {
                            "status": "CANNOT_CONFIRM", "execution_verified": False,
                            "natural_verified": False,
                            "cannot_confirm": list(denied["cannot_confirm"]),
                        }
                        execution.update(markets=execution_markets,
                                         execution_verified=False, natural_verified=False)
                        result["execution_evidence"] = execution
                        return project_shared_selection(result, limit, ordinary_hk_display=True)
                raise HTTPException(status_code=409, detail="approved research read binding is unavailable or invalid") from error
'''


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def frozen_targets():
    scope_path = OUT / 'control/ROOT_INCREMENTAL22_SCOPE.json'
    assert sha(scope_path) == EXPECTED_SCOPE
    scope = json.loads(scope_path.read_text())
    return [(x['trade_date'], x['stage_id']) for x in scope['targets']]


def patched_source(source):
    assert source.count(OLD_TARGETS) == 1, 'EXACT_TWO_TARGET_SET_DRIFT'
    assert source.count(OLD_GUARD) == 1, 'APPROVED_RESEARCH_GUARD_DRIFT'
    targets = set(frozen_targets()) - {('20261009', 'STAGE_0930_0935')}
    targets |= {('20260929', 'STAGE_1445_1500'), ('20260930', 'STAGE_1445_1500')}
    literal = '\n'.join('                ' + repr(x) + ',' for x in sorted(targets))
    candidate = source.replace(OLD_TARGETS, literal, 1).replace(OLD_GUARD, NEW_GUARD, 1)
    candidate = candidate.replace('# These two historical composite reads have independently verified',
                                  '# These frozen historical composite reads have independently verified', 1)
    ast.parse(candidate)
    return candidate


def prepare():
    base = RUNTIME / 'apps/api/v35_api/app.py'
    assert sha(base) == EXPECTED_BASE
    source = base.read_text()
    candidate = patched_source(source)
    root = OUT / 'candidate_r3'
    root.mkdir(exist_ok=False)
    (root / 'app.py').write_text(candidate)
    patch = ''.join(difflib.unified_diff(source.splitlines(keepends=True), candidate.splitlines(keepends=True),
                                       fromfile='a/apps/api/v35_api/app.py', tofile='b/apps/api/v35_api/app.py'))
    (root / 'READER_INCREMENTAL22.patch').write_text(patch)
    manifest = dict(schema='INCREMENTAL22_READER_CANDIDATE_V1', root_scope_sha256=EXPECTED_SCOPE,
                    base_path=str(base), base_sha256=EXPECTED_BASE,
                    candidate_sha256=sha(root / 'app.py'), patch_sha256=sha(root / 'READER_INCREMENTAL22.patch'),
                    affected22=frozen_targets(), previous_two_regression=[['20260929', 'STAGE_1445_1500'], ['20260930', 'STAGE_1445_1500']],
                    unchanged_A_guard='ORIGINAL_SELECTIONSTORE_READ_VERIFIED', no_live_writes=True,
                    approved_package_scope='BOTH_MARKETS_REJECTED_INDEPENDENT_ORDINARY_A_ONLY')
    (root / 'CANDIDATE_MANIFEST.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    return manifest


def reader_namespace(source):
    """Isolate actual nested router logic with pinned read-only dependencies.

    The live app and its files are never modified. No create_app constructors,
    collectors, materializers, services or alternate listening ports are used.
    """
    sys.path.insert(0, str(RUNTIME))
    name = '_v4_incremental_readonly_module'
    module = types.ModuleType(name)
    module.__file__ = str(RUNTIME / 'apps/api/v35_api/app.py')
    sys.modules[name] = module
    exec(compile(source, module.__file__, 'exec'), module.__dict__)
    tree = ast.parse(source)
    factory = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'create_app')
    functions = [n for n in factory.body if isinstance(n, ast.FunctionDef)]
    for node in functions:
        node.decorator_list = []
    from stage_center.consumer import StageSelectionConsumer
    from stage_center.research_read_binding import ApprovedResearchReadBinding
    namespace = module.__dict__.copy()
    pool = Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data')
    namespace.update(shared_selection_consumer=StageSelectionConsumer(SELECT, a_name_pool_root=pool),
                     resolved_pool_source=pool,
                     configured_selection_root=SELECT, configured_morning_news_root=None,
                     stage_runner=None,
                     approved_research_reader=ApprovedResearchReadBinding(
                         binding_path=RUNTIME / 'stage_center/approved_research_read.json',
                         history_root=SELECT, api_root=RUNTIME,
                         expected_reader_sha256=module._STAGE_RESEARCH_READER_SHA256))
    exec(compile(ast.Module(body=functions, type_ignores=[]), '<isolated-actual-candidate-router-logic>', 'exec'), namespace)
    return namespace


if __name__ == '__main__':
    print(json.dumps(prepare(), ensure_ascii=False))

# Separate, immutable final candidate for the one failed hard-coded day24 lane.
DAY24_OLD = '''                    exact_hk = stage_workbench(
                        date=selected,
                        stage=stage,
                        limit=limit,
                        market="HK_CONNECT",
                        backfill_run_id=day24_run_id,
                    )
'''
DAY24_NEW = '''                    try:
                        exact_hk = stage_workbench(
                            date=selected,
                            stage=stage,
                            limit=limit,
                            market="HK_CONNECT",
                            backfill_run_id=day24_run_id,
                        )
                    except HTTPException as error:
                        a_market = (payload.get("markets") or {}).get("A_SHARE")
                        if error.status_code != 409 or not isinstance(a_market, Mapping) or not (
                            a_market.get("selection_manifest_receipt_verified") is True
                            and int(a_market.get("selected_rows") or 0) > 0
                            and len(a_market.get("rows") or []) == a_market["selected_rows"]
                        ):
                            raise
                        from stage_center.consumer import _invalid_market_with_reason
                        denied = _invalid_market_with_reason(
                            "HK_CONNECT", "EXACT_TARGET_HK_BINDING_INVALID"
                        )
                        denied["cannot_confirm"].append(str(error.detail))
                        denied["recovery_provenance"] = {
                            "mode": "BACKFILL_BINDING_REJECTED",
                            "backfill_run_id": day24_run_id,
                            "source": "DAY24_EXACT_HK_OVERRIDE",
                            "http_status": error.status_code,
                        }
                        result = dict(payload)
                        markets = dict(payload.get("markets") or {})
                        markets["HK_CONNECT"] = denied
                        result.update(markets=markets, artifact_id=None,
                                      bundle_artifact_id=None, run_id=None)
                        execution = dict(payload.get("execution_evidence") or {})
                        execution_markets = dict(execution.get("markets") or {})
                        execution_markets["HK_CONNECT"] = {
                            "status": "CANNOT_CONFIRM", "execution_verified": False,
                            "natural_verified": False,
                            "cannot_confirm": list(denied["cannot_confirm"]),
                        }
                        execution.update(markets=execution_markets,
                                         execution_verified=False, natural_verified=False)
                        result["execution_evidence"] = execution
                        return project_shared_selection(result, limit, ordinary_hk_display=True)
'''


def final_source(source):
    candidate = patched_source(source)
    assert candidate.count(DAY24_OLD) == 1, 'DAY24_INDEPENDENT_CALLSITE_DRIFT'
    candidate = candidate.replace(DAY24_OLD, DAY24_NEW, 1)
    ast.parse(candidate)
    return candidate


def prepare_final():
    base = RUNTIME / 'apps/api/v35_api/app.py'
    assert sha(base) == EXPECTED_BASE
    source = base.read_text()
    candidate = final_source(source)
    root = OUT / 'candidate_r3b'
    root.mkdir(exist_ok=False)
    (root / 'app.py').write_text(candidate)
    patch = ''.join(difflib.unified_diff(source.splitlines(keepends=True), candidate.splitlines(keepends=True),
                                       fromfile='a/apps/api/v35_api/app.py', tofile='b/apps/api/v35_api/app.py'))
    (root / 'READER_INCREMENTAL22.patch').write_text(patch)
    manifest = json.loads((OUT / 'candidate_r3/CANDIDATE_MANIFEST.json').read_text())
    manifest.update(candidate_sha256=sha(root / 'app.py'), patch_sha256=sha(root / 'READER_INCREMENTAL22.patch'),
                    prior_candidate_path=str(OUT / 'candidate_r3/app.py'),
                    prior_candidate_sha256=sha(OUT / 'candidate_r3/app.py'),
                    change_from_prior='ONLY_SEP24_0930_HARDCODED_OPTIONAL_HK_CALLSITE',
                    prior27_software_passes_reused=True,
                    failed_branch_and_direct_guard_only_retested=True)
    (root / 'CANDIDATE_MANIFEST.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    return manifest
