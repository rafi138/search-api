"""Geocoding search endpoint ("press enter").

With a focus point: two-pool + rescore (proximity + name-text + popularity).
Optional bbox / radius restrict to an area. Returns name + address + types only.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from elasticsearch import AsyncElasticsearch

from ....config import get_settings
from ....es import get_es
from ....models.place import PlaceSummary
from ....queries.common import parse_bbox
from ....queries.search import build_search_query
from ....services import ranked_search

router = APIRouter(prefix="/search", tags=["search"])


class SearchResponse(BaseModel):
    places: list[PlaceSummary]
    score_debug: Optional[list[dict]] = None


@router.get("", response_model=SearchResponse, summary="Geocoding search")
async def search(
    q: str = Query(..., min_length=1),
    latitude: float | None = Query(None),
    longitude: float | None = Query(None),
    bbox: str | None = Query(None, description="minlon,minlat,maxlon,maxlat"),
    radius: str | None = Query(None, description="e.g. '5' or '5km' (needs lat/lon)"),
    limit: int = Query(10, ge=1, le=50),
    debug: bool = Query(False, description="include per-doc score breakdown"),
    es: AsyncElasticsearch = Depends(get_es),
):
    if bbox:
        try:
            parse_bbox(bbox)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

    hits, score_debug = await ranked_search(
        es, get_settings().INDEX_NAME, q, build_search_query,
        lat=latitude, lon=longitude, limit=limit, debug=debug, bbox=bbox, radius=radius)
    places = [PlaceSummary.from_source(h["_source"]) for h in hits]
    return SearchResponse(places=places, score_debug=score_debug)
