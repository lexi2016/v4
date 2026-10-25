"""Exact18 read-path recovery support. No selection, collector or live data writes."""
from __future__ import annotations
import argparse
import ast
import difflib
import hashlib
import json
from pathlib import Path

TARGETS = frozenset({('20260929', 'STAGE_1445_1500'), ('20260930', 'STAGE_1445_1500')})
RUNTIME = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/a-share-history-consumer-20261025-r1/app')
ROOT = Path('/Users/lexi/Desktop/学习/因子工厂/research/a_share_v4_stage_history_restore_20261025')
SOURCE = '''        exact = stage_workbench(
            date=trade_date,
            stage=stage_id,
            limit=limit,
            market="HK_CONNECT",
            backfill_run_id=binding["backfill_run_id"],
        )
'''
PATCHED = '''        try:
            exact = stage_workbench(
                date=trade_date,
                stage=stage_id,
                limit=limit,
                market="HK_CONNECT",
                backfill_run_id=binding["backfill_run_id"],
            )
        except HTTPException as error:
            # These two historical composite reads have independently verified
            # A-share trios. An invalid HK override must not hide that A lane;
            # the explicit HK read above still rejects its invalid binding.
            if error.status_code != 409 or (trade_date, stage_id) not in {
                ("20260929", "STAGE_1445_1500"),
                ("20260930", "STAGE_1445_1500"),
            }:
                raise
            markets = dict(payload.get("markets") or {})
            a_market = markets.get("A_SHARE")
            if not isinstance(a_market, Mapping) or not (
                a_market.get("selection_manifest_receipt_verified") is True
                and int(a_market.get("selected_rows") or 0) > 0
            ):
                raise
            from stage_center.consumer import _invalid_market_with_reason
            denied = _invalid_market_with_reason(
                "HK_CONNECT", "EXACT_TARGET_HK_BINDING_INVALID"
            )
            denied["cannot_confirm"].append(str(error.detail))
            denied["recovery_provenance"] = {
                "mode": "BACKFILL_BINDING_REJECTED",
                "backfill_run_id": binding["backfill_run_id"],
                "source": source_label,
                "http_status": error.status_code,
            }
            markets["HK_CONNECT"] = denied
            result = dict(payload)
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
            return result
'''


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def patched_source(source: str) -> str:
    if source.count(SOURCE) != 1:
        raise ValueError('ACTUAL_RUNTIME_EXACT_TARGET_CALLSITE_DRIFT')
    candidate = source.replace(SOURCE, PATCHED, 1)
    ast.parse(candidate)
    return candidate


def prepare(destination: Path) -> dict:
    source_path = RUNTIME / 'apps/api/v35_api/app.py'
    destination.mkdir(parents=True, exist_ok=False)
    source = source_path.read_text()
    candidate = patched_source(source)
    candidate_path = destination / 'app.py'
    candidate_path.write_text(candidate)
    patch = ''.join(difflib.unified_diff(
        source.splitlines(keepends=True), candidate.splitlines(keepends=True),
        fromfile='a/apps/api/v35_api/app.py', tofile='b/apps/api/v35_api/app.py'))
    (destination / 'READER_ONLY.patch').write_text(patch)
    manifest = dict(schema='EXACT_TWO_A_HISTORY_READER_RECOVERY_V1',
                    actual_runtime_source=str(source_path),
                    actual_runtime_source_sha256=sha(source_path),
                    candidate_path=str(candidate_path), candidate_sha256=sha(candidate_path),
                    patch_sha256=sha(destination / 'READER_ONLY.patch'),
                    exact_changed_function='_read_exact_target_hk_override',
                    exact_targets=sorted(TARGETS), no_live_writes=True,
                    no_input_selection_or_hk_data_mutation=True,
                    qualification='A_PRESERVED_HK_INVALID_OVERRIDE_QUARANTINED; EXACT_HK_409_UNCHANGED')
    (destination / 'CANDIDATE_MANIFEST.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(args.destination), ensure_ascii=False))
