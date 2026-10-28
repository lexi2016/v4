"""Dedicated read-only route; does not change existing V4 pool/selection routes."""
from fastapi import APIRouter, HTTPException, Response

from .opening_observation_service import OpeningObservationService


def create_opening_observation_router(service: OpeningObservationService) -> APIRouter:
    router = APIRouter()

    @router.get('/api/v4/research/opening-observation')
    def opening_observation(response: Response, date: str, symbol: str,
            candidate_source_date: str | None = None) -> dict:
        response.headers['Cache-Control'] = 'no-store'
        try:
            return service.get(date=date,symbol=symbol,candidate_source_date=candidate_source_date)
        except ValueError as error:
            raise HTTPException(status_code=422,detail=str(error)) from error

    return router
