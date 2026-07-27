"""Alter-names endpoints — upsert/delete aliases for a place by place_code.

``PUT  /v1/places/{place_code}/alter-names``   body: {"alter_names": ["alias1", "alias2"]}
DELETE /v1/places/{place_code}/alter-names``   clears all aliases
DELETE /v1/places/{place_code}/alter-names/{index}``  removes one alias by index
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from elasticsearch import AsyncElasticsearch, NotFoundError

from ....config import get_settings
from ....es import get_es

router = APIRouter(prefix="/places", tags=["alter-names"])


class AlterNamesIn(BaseModel):
    alter_names: list[str]


class AlterNamesOut(BaseModel):
    place_code: str
    alter_names: list[str]


@router.get("/{place_code}/alter-names", response_model=AlterNamesOut, summary="Get alter_names for a place")
async def get_alter_names(place_code: str, es: AsyncElasticsearch = Depends(get_es)):
    try:
        doc = await es.get(index=get_settings().INDEX_NAME, id=place_code)
        return AlterNamesOut(place_code=place_code, alter_names=doc["_source"].get("alter_names") or [])
    except NotFoundError:
        raise HTTPException(status_code=404, detail=f"Place {place_code} not found")


@router.put("/{place_code}/alter-names", response_model=AlterNamesOut, summary="Replace all alter_names")
async def put_alter_names(place_code: str, body: AlterNamesIn,
                          es: AsyncElasticsearch = Depends(get_es)):
    """Replace the full alter_names list (idempotent upsert)."""
    idx = get_settings().INDEX_NAME
    try:
        await es.update(index=idx, id=place_code, body={"doc": {"alter_names": body.alter_names}})
    except NotFoundError:
        raise HTTPException(status_code=404, detail=f"Place {place_code} not found")
    return AlterNamesOut(place_code=place_code, alter_names=body.alter_names)


@router.post("/{place_code}/alter-names", response_model=AlterNamesOut, summary="Add aliases (merge with existing)")
async def add_alter_names(place_code: str, body: AlterNamesIn,
                          es: AsyncElasticsearch = Depends(get_es)):
    """Append new aliases to the existing list (deduped, order preserved)."""
    idx = get_settings().INDEX_NAME
    try:
        doc = await es.get(index=idx, id=place_code)
    except NotFoundError:
        raise HTTPException(status_code=404, detail=f"Place {place_code} not found")
    existing = doc["_source"].get("alter_names") or []
    seen = {a.lower() for a in existing}
    merged = list(existing)
    for a in body.alter_names:
        if a.lower() not in seen:
            merged.append(a)
            seen.add(a.lower())
    await es.update(index=idx, id=place_code, body={"doc": {"alter_names": merged}})
    return AlterNamesOut(place_code=place_code, alter_names=merged)


@router.delete("/{place_code}/alter-names", response_model=AlterNamesOut, summary="Clear all alter_names")
async def delete_all_alter_names(place_code: str, es: AsyncElasticsearch = Depends(get_es)):
    idx = get_settings().INDEX_NAME
    try:
        await es.update(index=idx, id=place_code, body={"doc": {"alter_names": []}})
    except NotFoundError:
        raise HTTPException(status_code=404, detail=f"Place {place_code} not found")
    return AlterNamesOut(place_code=place_code, alter_names=[])


@router.delete("/{place_code}/alter-names/{alias}", response_model=AlterNamesOut,
               summary="Remove one alias by value (URL-encoded)")
async def delete_one_alter_name(place_code: str, alias: str,
                                es: AsyncElasticsearch = Depends(get_es)):
    idx = get_settings().INDEX_NAME
    try:
        doc = await es.get(index=idx, id=place_code)
    except NotFoundError:
        raise HTTPException(status_code=404, detail=f"Place {place_code} not found")
    existing = doc["_source"].get("alter_names") or []
    remaining = [a for a in existing if a.lower() != alias.lower()]
    await es.update(index=idx, id=place_code, body={"doc": {"alter_names": remaining}})
    return AlterNamesOut(place_code=place_code, alter_names=remaining)
