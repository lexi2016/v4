"""Read-only report evidence routes; index operations are never exposed."""
from pathlib import Path
import os
from fastapi import APIRouter, HTTPException, Query
from domains.report_evidence import ReportEvidenceService
from infrastructure.report_evidence_index import PdfOwner, ReportIndex, SAFETY, shared_pdf_owner
from infrastructure.report_evidence_native import LocalNative

def configured_service(data_root):
    root = os.environ.get('V4_REPORT_EVIDENCE_INDEX_ROOT')
    if not root:
        return None
    bridge = os.environ.get('V4_REPORT_EVIDENCE_LOCAL_BRIDGE')
    return ReportEvidenceService(ReportIndex(Path(root), shared_pdf_owner(str(data_root))), LocalNative(bridge) if bridge else None)

def create_report_evidence_router(data_root):
    router=APIRouter(prefix='/api/v4/research',tags=['research-evidence'])
    @router.get('/evidence-search')
    async def evidence_search(text: str=Query(min_length=1,max_length=2000),security: str='',market: str='',source: str='',
        date_from: str='',date_to: str='',mode: str='current_research',as_of: str|None=None,limit: int=Query(default=10,ge=1,le=20)):
        service=configured_service(data_root)
        if service is None:
            return dict(status='EVIDENCE_GAP',gaps=['REPORT_INDEX_NOT_CONFIGURED'],hits=[],**SAFETY)
        try:
            return await service.search(text,security=security,market=market,source=source,date_from=date_from,
                                        date_to=date_to,mode=mode,as_of=as_of,limit=limit)
        except ValueError as error:
            raise HTTPException(422,str(error)) from None
    @router.get('/stage-report-evidence')
    def stage_report_evidence(date: str,stage: str,selection_run: str,market: str):
        from infrastructure.report_evidence_sidecar import read_sidecar
        root=os.environ.get('V4_REPORT_EVIDENCE_SIDECAR_ROOT')
        try:
            return read_sidecar(root,date=date,stage=stage,selection_run=selection_run,market=market)
        except ValueError as error:
            raise HTTPException(422,str(error)) from None
    return router
