"""Place details endpoint — return the full document by place_code (the _id)."""
from fastapi import APIRouter, Depends, HTTPException
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
