"""Place details + upsert + delete endpoints (by place_code, the ES _id)."""
from fastapi import APIRouter, Body, Depends, HTTPException
from elasticsearch import AsyncElasticsearch, NotFoundError

from ....config import get_settings
from ....es import get_es
from ....models.place import PlaceDetail

router = APIRouter(prefix="/places", tags=["places"])


@router.get("/{place_code}", response_model=PlaceDetail, summary="Full place details by place_code")
async def get_place(place_code: str, es: AsyncElasticsearch = Depends(get_es)):
    try:
        return (await es.get(index=get_settings().INDEX_NAME, id=place_code))["_source"]
    except NotFoundError:
        raise HTTPException(status_code=404, detail=f"Place {place_code} not found")


@router.put("/{place_code}", summary="Upsert a place document by place_code")
async def upsert_place(
    place_code: str,
    body: dict = Body(..., description="Full document JSON (any fields)"),
    es: AsyncElasticsearch = Depends(get_es),
):
    """Create or replace a place document. The body is indexed with ``_id = place_code``.
    Returns ``{"place_code": ..., "result": "created" | "updated"}``."""
    res = await es.index(index=get_settings().INDEX_NAME, id=place_code, document=body)
    return {"place_code": place_code, "result": res["result"]}


@router.delete("/{place_code}", summary="Delete a place document by place_code")
async def delete_place(place_code: str, es: AsyncElasticsearch = Depends(get_es)):
    """Delete a place document by place_code (ES _id). Returns 404 if not found."""
    try:
        await es.delete(index=get_settings().INDEX_NAME, id=place_code)
    except NotFoundError:
        raise HTTPException(status_code=404, detail=f"Place {place_code} not found")
    return {"deleted": place_code}
