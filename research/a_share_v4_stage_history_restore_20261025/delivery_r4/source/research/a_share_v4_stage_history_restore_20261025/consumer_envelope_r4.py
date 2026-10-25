"""Restore the existing unavailable-HK envelope; no frontend or identity relaxation."""
from __future__ import annotations
import ast
import copy
import difflib
import hashlib
import json
from pathlib import Path
import sys

OUT = Path('/Users/lexi/Desktop/学习/因子工厂/research/a_share_v4_stage_history_restore_20261025')
RUNTIME = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/a-share-stage-history-restore-20261025-r3/app')
EXPECTED_BASE = '881aef6ecdf569839f69d8becad3093ea633643448050eaeb542539db1278896'
OLD = '''        canonical_markets = payload.get("markets", {})
        selection_markets = canonical_markets
'''
NEW = '''        canonical_markets = dict(payload.get("markets", {}))
        hk_unknown = canonical_markets.get("HK_CONNECT")
        if isinstance(hk_unknown, Mapping) and (
            all(hk_unknown.get(key) == "CANNOT_CONFIRM"
                for key in ("status", "selection_status", "source_status"))
            and all(hk_unknown.get(key) is None for key in
                    ("requested_rows", "source_rows", "selected_rows", "artifact_id", "run_id"))
            and hk_unknown.get("rows") == []
            and isinstance(hk_unknown.get("cannot_confirm"), list)
            and hk_unknown.get("selection_manifest_receipt_verified") in (None, False)
        ):
            from stage_center.consumer import _invalid_market
            hk_unknown = dict(hk_unknown)
            standard = _invalid_market("HK_CONNECT")["cannot_confirm"]
            causes = hk_unknown["cannot_confirm"]
            hk_unknown["cannot_confirm"] = [reason for reason in standard if reason not in causes] + causes
            hk_unknown["selection_manifest_receipt_verified"] = False
            canonical_markets["HK_CONNECT"] = hk_unknown
        selection_markets = canonical_markets
'''


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def patched_source(source):
    assert source.count(OLD) == 1, 'PROJECT_SHARED_SELECTION_CALLSITE_DRIFT'
    result = source.replace(OLD, NEW, 1)
    ast.parse(result)
    return result


def prepare():
    base = RUNTIME / 'apps/api/v35_api/app.py'
    assert sha(base) == EXPECTED_BASE
    source = base.read_text()
    result = patched_source(source)
    dest = OUT / 'candidate_r4'
    dest.mkdir(exist_ok=False)
    (dest / 'app.py').write_text(result)
    patch = ''.join(difflib.unified_diff(source.splitlines(keepends=True), result.splitlines(keepends=True),
                                       fromfile='a/apps/api/v35_api/app.py', tofile='b/apps/api/v35_api/app.py', n=1))
    (dest / 'READER_UI_ENVELOPE.patch').write_text(patch)
    manifest = dict(schema='STANDARD_UNAVAILABLE_HK_UI_ENVELOPE_R4_V1',
                    base_path=str(base), base_sha256=EXPECTED_BASE,
                    candidate_sha256=sha(dest / 'app.py'), patch_sha256=sha(dest / 'READER_UI_ENVELOPE.patch'),
                    changed_function='project_shared_selection',
                    source_change='API app.py only; stage_center/consumer.py and frontend unchanged',
                    first_error_proof_sha256=sha(OUT / 'schema_r4/FIRST_FAILURE_REPRO.json'),
                    standard_factory='stage_center.consumer._invalid_market',
                    no_fabricated_date_stage_or_quote=True,
                    original_A_object_unchanged=True, no_live_writes=True)
    (dest / 'CANDIDATE_MANIFEST.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    return manifest


def normalize_canonical_markets(markets, source):
    """Execute the exact candidate projection prefix, without invoking readers."""
    tree = ast.parse(source)
    function = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                    and n.name == 'project_shared_selection')
    stop = next(i for i, n in enumerate(function.body) if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == 'selection_markets' for t in n.targets))
    body = function.body[:stop]
    definition = ast.FunctionDef(name='normalize', args=ast.arguments(posonlyargs=[], args=[ast.arg(arg='payload')], kwonlyargs=[], kw_defaults=[], defaults=[]),
                                 body=body + [ast.Return(value=ast.Name(id='canonical_markets', ctx=ast.Load()))], decorator_list=[])
    module = ast.fix_missing_locations(ast.Module(body=[definition], type_ignores=[]))
    sys.path.insert(0, str(RUNTIME))
    from typing import Mapping
    ns = {'Mapping': Mapping}
    exec(compile(module, '<exact-candidate-unavailable-market-prefix>', 'exec'), ns)
    return ns['normalize']({'markets': markets})


def correct_saved_payload(payload, source):
    """Project only the exact backend HK envelope delta into saved API bytes.

    Alias fields are copies of this canonical market in the unchanged deployed
    project_shared_selection loop. Every A object, header, number and guard
    result remains the original saved response value.
    """
    before = copy.deepcopy(payload)
    result = copy.deepcopy(payload)
    original = result['selection_markets']
    corrected = normalize_canonical_markets(original, source)
    result['selection_markets'] = corrected
    old_hk = original.get('HK_CONNECT')
    new_hk = corrected.get('HK_CONNECT')
    if isinstance(old_hk, dict) and isinstance(new_hk, dict) and old_hk != new_hk:
        changed = {k: v for k, v in new_hk.items() if old_hk.get(k) != v or k not in old_hk}
        assert set(changed) <= {'cannot_confirm', 'selection_manifest_receipt_verified'}
        for field in ['markets', 'market_summaries']:
            collection = result.get(field)
            if isinstance(collection, dict) and isinstance(collection.get('HK'), dict):
                collection['HK'].update(changed)
    assert result['selection_markets'].get('A_SHARE') == before['selection_markets'].get('A_SHARE')
    for field in ['markets', 'market_summaries']:
        if isinstance(before.get(field), dict):
            assert result[field].get('A') == before[field].get('A')
    assert result.get('unified_rows') == before.get('unified_rows')
    return result


if __name__ == '__main__':
    print(json.dumps(prepare(), ensure_ascii=False))
