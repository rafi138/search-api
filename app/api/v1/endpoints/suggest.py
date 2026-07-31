"""Suggest endpoint (per-keystroke autocomplete).

Field priority: business_name > place_name > address > area > district. With a
focus point, uses the same two-pool + rescore as /search (proximity + name +
popularity). Returns name + address + types only (no coordinates).
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from elasticsearch import AsyncElasticsearch

from ....config import get_settings
from ....es import get_es
from ....models.place import PlaceSummary, SummaryResponse
from ....queries.common import parse_polygon, build_facet_filters
from ....queries.suggest import build_suggestion_query
from ....services import ranked_search

router = APIRouter(prefix="/suggest", tags=["suggest"])


@router.get("", response_model=SummaryResponse, summary="Autocomplete suggestions (text + facet filters)")
async def suggest(
    q: str = Query(..., min_length=1, description="Search text (required)"),
    latitude: float | None = Query(None, description="Focus latitude (with longitude)"),
    longitude: float | None = Query(None, description="Focus longitude (with latitude)"),
    bbox: str | None = Query(None, description="Bounding box: minlon,minlat,maxlon,maxlat"),
    radius: str | None = Query(None, description="Hard geo filter, e.g. '5' or '5km' (needs lat/lon)"),
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
    es: AsyncElasticsearch = Depends(get_es),
):
    try:
        poly = parse_polygon(polygon)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    filters = build_facet_filters(area=area, district=district, city=city, thana=thana,
                                  union=union, sub_area=sub_area, super_sub_area=super_sub_area,
                                  sub_district=sub_district, postcode=postcode, type=type, subtype=subtype)
    if poly:
        filters.append(poly)

    hits, _ = await ranked_search(
        es, get_settings().INDEX_NAME, q, build_suggestion_query,
        lat=latitude, lon=longitude, limit=limit, bbox=bbox, radius=radius, filters=filters)
    places = [PlaceSummary.from_source(h["_source"]) for h in hits]
    return SummaryResponse(places=places)
