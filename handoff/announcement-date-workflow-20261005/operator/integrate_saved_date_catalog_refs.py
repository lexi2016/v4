#!/usr/bin/env python3
"""Dry-run or explicitly integrate the saved Sep 29 catalog refs via the owner."""
from __future__ import annotations

import argparse
from pathlib import Path
import json
import sys

REPO = Path('/Users/lexi/Desktop/学习/v4_app')
DIAG = Path('/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_SELECTION_PATH_DIAG_20261005')
SOURCE = DIAG / 'date_scoped_collection'
MASTER_SNAPSHOT = DIAG / 'fresh_preopen/verified_master_20260930.json'
DEFAULT_MATERIAL_ROOT = Path.home() / 'Library/Application Support/com.lexi.v4.local/state/manager_auto_research/materials'
TARGET_DATE = '20260930'
PUBLICATION_DATE = '2026-09-29'


def load_refs() -> dict[int, dict]:
    refs = {}
    for page in range(1, 40):
        receipt_path = SOURCE / 'page_receipts' / f'page_{page:03d}.json'
        receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
        ref = receipt.get('source_ref')
        if receipt.get('page_index') != page or not isinstance(ref, dict):
            raise ValueError(f'SAVED_CATALOG_REFERENCE_MISSING_PAGE_{page}')
        refs[page] = ref
    return refs


def verify_master_snapshot(active_names: dict, active_witness: dict, master: dict) -> None:
    """Compare the same full native rows and keep the source witness strict."""
    if active_names != master['names'] or active_witness != master['identity_witness']:
        raise SystemExit('VERIFIED_MASTER_SNAPSHOT_DRIFT')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='write through the explicit-date owner; default is read-only dry-run')
    parser.add_argument('--state-root', type=Path, help='explicit ManagerResearchStore root required with --apply')
    parser.add_argument('--material-root', type=Path, default=DEFAULT_MATERIAL_ROOT,
                        help='shared MaterialStore containing the saved response blobs')
    parser.add_argument('--master-root', type=Path,
                        help='verified HK security master root required with --apply')
    args = parser.parse_args()
    if args.apply and (args.state_root is None or args.master_root is None):
        parser.error('--apply requires explicit --state-root and --master-root')

    refs = load_refs()
    sys.path.insert(0, str(REPO))
    from v4.manager_research.announcement_catalog import (
        collect_date_scoped_catalog, validate_product, verify_product_sources,
    )
    from v4.manager_research.materials import MaterialStore

    master = json.loads(MASTER_SNAPSHOT.read_text(encoding='utf-8'))
    materials = MaterialStore(args.material_root)
    preview = collect_date_scoped_catalog(None, materials, target_trade_date=TARGET_DATE,
        publication_date=PUBLICATION_DATE, master_names=master['names'],
        identity_witness=master['identity_witness'], resume_refs=refs,
        run_id='00000000000000000000000000000002',
        generated_at='2026-10-05T00:00:00+00:00')
    preview = validate_product(preview, target_trade_date=TARGET_DATE,
        publication_date=PUBLICATION_DATE)
    verify_product_sources(preview, materials)
    if preview['status'] != 'COMPLETE' or preview['total_hits'] != 744 or preview['manager_consumer_row_count'] != 234:
        raise SystemExit(json.dumps(dict(status='PARTIAL_DRY_RUN', gaps=preview['gaps'],
            total_hits=preview['total_hits'], manager_rows=preview['manager_consumer_row_count']), sort_keys=True))

    result = dict(mode='DRY_RUN', status=preview['status'], page_count=preview['captured_page_count'],
        total_hits=preview['total_hits'], unique_art_codes=preview['unique_art_code_count'],
        manager_rows=preview['manager_consumer_row_count'], network_requests=0,
        note='No owner state written; source timestamps remain those in the saved refs.')
    if args.apply:
        from v4.manager_research.service import ManagerResearchJobService
        from v4.manager_research.store import ManagerResearchStore
        from v4.manager_research.workspace_announcements import _master, _now
        from v4.manager_research.workspace_plan import plan_context
        from v4.manager_research.workspace_projection import timestamp

        service = ManagerResearchJobService(ManagerResearchStore(args.state_root), None, None,
            material_store=materials, workspace_security_master_root=args.master_root)
        try:
            existing = service.get_announcement_date_catalog(TARGET_DATE, PUBLICATION_DATE)
            if existing.get('catalog') is not None or existing.get('readback_status') != 'NOT_RUN':
                raise SystemExit('OWNER_DATE_CATALOG_ALREADY_EXISTS_OR_IS_NOT_READABLE')
            context = plan_context(TARGET_DATE, now=timestamp(_now()))
            active_names, active_witness = _master(service, context)
            verify_master_snapshot(active_names, active_witness, master)
            imported = service.accept_saved_date_catalog_refs(TARGET_DATE, PUBLICATION_DATE, refs)
            readback = service.get_announcement_date_catalog(TARGET_DATE, PUBLICATION_DATE)
            refreshed = service.refresh_announcements(TARGET_DATE,
                source_scope='EASTMONEY_HK_DATE_CATALOG', publication_date=PUBLICATION_DATE)
            result.update(mode='SAVED_REFERENCE_IMPORT', status=imported.get('status'),
                readback_status=readback.get('readback_status'),
                refresh_run_id=refreshed.get('catalog', {}).get('run_id'),
                imported_run_id=imported.get('catalog', {}).get('run_id'),
                capture_mode=imported.get('catalog', {}).get('capture_mode'),
                manager_rows=imported.get('catalog', {}).get('manager_consumer_row_count'),
                source_retrieved_at=[page.get('retrieved_at') for page in imported.get('catalog', {}).get('page_receipts', [])],
                note='Provider is disabled; all owner intake/readback/reuse operations are zero-network.')
            if (imported.get('readback_status') != 'VERIFIED' or imported.get('status') != 'COMPLETE'
                    or imported.get('catalog', {}).get('total_hits') != 744
                    or imported.get('catalog', {}).get('manager_consumer_row_count') != 234
                    or imported.get('catalog', {}).get('capture_mode') != 'SAVED_REFERENCE_IMPORT'
                    or readback.get('readback_status') != 'VERIFIED'
                    or refreshed.get('catalog', {}).get('run_id') != imported.get('catalog', {}).get('run_id')):
                raise SystemExit(json.dumps(result, ensure_ascii=False, sort_keys=True))
        finally:
            service.close()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
