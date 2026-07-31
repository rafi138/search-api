"""Types discovery endpoint — list valid pType/subType values with counts.

Clients use this to know what values to pass as ``type``/``subtype`` filters to
``/v1/search`` and ``/v1/suggest``.
"""
from fastapi import APIRouter, Depends, Query
from elasticsearch import AsyncElasticsearch

from ....config import get_settings
from ....es import get_es
from ....queries.common import build_facet_filters

router = APIRouter(prefix="/types", tags=["types"])


@router.get("", summary="List valid pType/subType values with counts (for filter discovery)")
async def list_types(
    type: str | None = Query(None, description="drill down: scope counts to this pType"),
    area: str | None = Query(None),
    district: str | None = Query(None),
    city: str | None = Query(None),
    thana: str | None = Query(None),
    postcode: str | None = Query(None),
    size: int = Query(100, ge=1, le=500, description="max buckets per aggregation"),
    es: AsyncElasticsearch = Depends(get_es),
):
    """Returns ``{"pType": [{value, count}, …], "subType": […]}`` scoped by the
    optional locality filters and/or ``type`` drill-down."""
    settings = get_settings()
    filters = build_facet_filters(area=area, district=district, city=city,
                                  thana=thana, postcode=postcode)
    if type:
        filters.append({"term": {"pType": type.strip()}})

    body = {
        "size": 0,
        "query": {"bool": {"filter": filters}} if filters else {"match_all": {}},
        "aggs": {
            "pType": {"terms": {"field": "pType", "size": size}},
            "subType": {"terms": {"field": "subType", "size": size}},
        },
    }
    res = await es.search(index=settings.INDEX_NAME, body=body)

    result = {}
    for agg_name, agg_data in res.get("aggregations", {}).items():
        result[agg_name] = [
            {"value": b["key"], "count": b["doc_count"]}
            for b in agg_data.get("buckets", [])
        ]
    return result
