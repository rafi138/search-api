"""Reverse geocoding endpoint.

Priority: nearest POI within 50m first (just one). If no POI within 50m, fall back
to the admin hierarchy (Division > District > ... > Road, nearest per subtype).
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from elasticsearch import AsyncElasticsearch

from ....config import get_settings
from ....es import get_es
from ....models.place import PlaceSummary
from ....queries.reverse import ADMIN_HIERARCHY, build_reverse_msearch
from ....ranking import haversine_km

router = APIRouter(prefix="/reverse", tags=["reverse"])

POI_RADIUS = "50m"


class ReverseResult(BaseModel):
    place_code: Optional[str] = None
    name: str
    address: str
    type: Optional[str] = None
    subtype: Optional[str] = None
    distance_km: Optional[float] = None


class ReverseResponse(BaseModel):
    places: list[ReverseResult]


def _summary(src: dict, lat: float, lon: float) -> ReverseResult:
    s = PlaceSummary.from_source(src)
    d = haversine_km(
        float(src.get("latitude") or 0), float(src.get("longitude") or 0), lat, lon)
    return ReverseResult(
        place_code=s.place_code, name=s.name, address=s.address,
        type=s.type, subtype=s.subtype,
        distance_km=round(d, 4) if d is not None else None,
    )


@router.get("", response_model=ReverseResponse, summary="Reverse geocode: nearest POI or admin hierarchy")
async def reverse(
    latitude: float = Query(..., description="Point latitude"),
    longitude: float = Query(..., description="Point longitude"),
    limit: int = Query(15, ge=1, le=50),
    es: AsyncElasticsearch = Depends(get_es),
):
    index = get_settings().INDEX_NAME

    # 1) try nearest POI within 50m first
    poi_body = {
        "size": 1,
        "query": {"bool": {
            "must_not": [{"term": {"pType": "Admin"}}],
            "filter": [{"geo_distance": {
                "distance": POI_RADIUS, "geo_location": {"lat": latitude, "lon": longitude},
            }}],
        }},
        "sort": [{"_geo_distance": {
            "geo_location": {"lat": latitude, "lon": longitude},
            "order": "asc", "unit": "km", "distance_type": "arc",
        }}],
    }
    poi_res = await es.search(index=index, body=poi_body)
    poi_hits = poi_res["hits"]["hits"]

    if poi_hits:
        # found a POI within 50m → return just that one
        return ReverseResponse(places=[_summary(poi_hits[0]["_source"], latitude, longitude)])

    # 2) no POI within 50m → admin hierarchy (nearest per subtype)
    body = build_reverse_msearch(latitude, longitude, index)
    resp = await es.msearch(body=body)
    responses = resp["responses"]

    admin_results = []
    for i in range(len(ADMIN_HIERARCHY)):
        hits = (responses[i].get("hits") or {}).get("hits", [])
        if hits:
            admin_results.append(_summary(hits[0]["_source"], latitude, longitude))

    return ReverseResponse(places=admin_results[:limit])
