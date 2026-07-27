"""Suggest endpoint (per-keystroke autocomplete).

Field priority: business_name > place_name > address > area > district. With a
focus point, uses the same two-pool + rescore as /search (proximity + name +
popularity). Returns name + address + types only (no coordinates).
"""
from fastapi import APIRouter, Depends, Query
from elasticsearch import AsyncElasticsearch

from ....config import get_settings
from ....es import get_es
from ....models.place import PlaceSummary, SummaryResponse
from ....queries.suggest import build_suggestion_query
from ....services import ranked_search

router = APIRouter(prefix="/suggest", tags=["suggest"])


@router.get("", response_model=SummaryResponse, summary="Autocomplete suggestions")
async def suggest(
    q: str = Query(..., min_length=1, description="Search text (required)"),
    latitude: float | None = Query(None, description="Focus latitude (with longitude)"),
    longitude: float | None = Query(None, description="Focus longitude (with latitude)"),
    bbox: str | None = Query(None, description="Bounding box: minlon,minlat,maxlon,maxlat"),
    radius: str | None = Query(None, description="Hard geo filter, e.g. '5' or '5km' (needs lat/lon)"),
    limit: int = Query(10, ge=1, le=50),
    es: AsyncElasticsearch = Depends(get_es),
):
    hits, _ = await ranked_search(
        es, get_settings().INDEX_NAME, q, build_suggestion_query,
        lat=latitude, lon=longitude, limit=limit, bbox=bbox, radius=radius)
    places = [PlaceSummary.from_source(h["_source"]) for h in hits]
    return SummaryResponse(places=places)
