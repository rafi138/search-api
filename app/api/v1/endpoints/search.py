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
from ....queries.common import parse_bbox, parse_polygon, build_facet_filters
from ....queries.search import build_search_query
from ....services import ranked_search

router = APIRouter(prefix="/search", tags=["search"])


class SearchResponse(BaseModel):
    places: list[PlaceSummary]
    score_debug: Optional[list[dict]] = None


@router.get("", response_model=SearchResponse, summary="Geocoding search (text + facet filters)")
async def search(
    q: str = Query("", max_length=200, description="search text (empty = filter-only, e.g. list banks in a city)"),
    latitude: float | None = Query(None),
    longitude: float | None = Query(None),
    bbox: str | None = Query(None, description="minlon,minlat,maxlon,maxlat"),
    radius: str | None = Query(None, description="e.g. '5' or '5km' (needs lat/lon)"),
    polygon: str | None = Query(None, description="geo_polygon ring: lon1,lat1,lon2,lat2,… (>=3 pts)"),
    # facet filters (locality: case-insensitive, comma-separated multi-value)
    area: str | None = Query(None),
    district: str | None = Query(None),
    city: str | None = Query(None),
    thana: str | None = Query(None),
    union: str | None = Query(None),
    sub_area: str | None = Query(None),
    super_sub_area: str | None = Query(None),
    sub_district: str | None = Query(None),
    # enum filters (exact keyword, comma-separated multi-value)
    postcode: str | None = Query(None),
    type: str | None = Query(None),
    subtype: str | None = Query(None),
    limit: int = Query(10, ge=1, le=50),
    offset: int = Query(0, ge=0),
    debug: bool = Query(False, description="include per-doc score breakdown"),
    bangla: bool = Query(False, description="include Bangla (_bn) fields in response"),
    es: AsyncElasticsearch = Depends(get_es),
):
    if q and len(q.strip()) < 2:
        raise HTTPException(status_code=422, detail="Query must be at least 2 characters, or empty for filter-only")
    if bbox:
        try:
            parse_bbox(bbox)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
    try:
        poly = parse_polygon(polygon)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    filters = build_facet_filters(area=area, district=district, city=city, thana=thana,
                                  union=union, sub_area=sub_area, super_sub_area=super_sub_area,
                                  sub_district=sub_district, postcode=postcode, type=type, subtype=subtype)
    if poly:
        filters.append(poly)

    hits, score_debug = await ranked_search(
        es, get_settings().INDEX_NAME, q, build_search_query,
        lat=latitude, lon=longitude, limit=limit, debug=debug,
        bbox=bbox, radius=radius, from_=offset, filters=filters)
    places = [PlaceSummary.from_source(h["_source"], bangla=bangla) for h in hits]
    return SearchResponse(places=places, score_debug=score_debug)
