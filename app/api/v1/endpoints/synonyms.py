"""Managed synonyms endpoints (ES ``_synonyms`` API).

Operations mirror the official ES synonyms API (create/replace a set, list/get/
delete a set, upsert/delete a single rule, and reload the index search analyzers
so changes take effect with no close/reopen or reindex).
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from elasticsearch import AsyncElasticsearch

from ....config import get_settings
from ....es import get_es
from ....models.synonym import SynonymSetIn, SynonymRuleIn

router = APIRouter(prefix="/synonyms", tags=["synonyms"])


def _normalize(resp: dict) -> dict:
    """ES get_synonym -> {id, description, synonyms:[rule strings]}.
    Handles both response shapes (flat list or nested dict) across ES versions."""
    resp = resp or {}
    ss = resp.get("synonyms_set")
    if isinstance(ss, dict):
        set_id = ss.get("id", resp.get("id"))
        desc = ss.get("description", resp.get("description"))
        rules_list = ss.get("synonyms_set", []) or []
    elif isinstance(ss, list):
        set_id = resp.get("id")
        desc = resp.get("description")
        rules_list = ss
    else:
        set_id, desc, rules_list = resp.get("id"), resp.get("description"), []
    rules = []
    for r in rules_list:
        if isinstance(r, dict):
            rules.append(r.get("synonyms"))
        else:
            rules.append(str(r))
    return {"id": set_id, "description": desc, "synonyms": [r for r in rules if r]}


@router.get("", summary="List synonym sets")
async def list_sets(es: AsyncElasticsearch = Depends(get_es)):
    return await es.synonyms.get_synonyms_sets()


@router.put("/{set_id}", summary="Create or replace a synonym set")
async def put_set(set_id: str, body: SynonymSetIn, es: AsyncElasticsearch = Depends(get_es)):
    payload = {"synonyms_set": [{"synonyms": r} for r in body.synonyms]}
    # NOTE: this ES build rejects a top-level "description" in the synonym-set body.
    try:
        await es.synonyms.put_synonym(id=set_id, body=payload)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"id": set_id, "synonyms": body.synonyms, "description": body.description}


@router.get("/{set_id}", summary="Get a synonym set")
async def get_set(set_id: str, es: AsyncElasticsearch = Depends(get_es)):
    try:
        resp = await es.synonyms.get_synonym(id=set_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _normalize(resp)


@router.delete("/{set_id}", summary="Delete a synonym set")
async def delete_set(set_id: str, es: AsyncElasticsearch = Depends(get_es)):
    try:
        await es.synonyms.delete_synonym(id=set_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"deleted": set_id}


@router.put("/{set_id}/rules/{rule_id}", summary="Upsert a single synonym rule")
async def put_rule(set_id: str, rule_id: str, body: SynonymRuleIn,
                   es: AsyncElasticsearch = Depends(get_es)):
    try:
        await es.synonyms.put_synonym_rule(set_id=set_id, rule_id=rule_id, synonyms=body.synonyms)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"set_id": set_id, "rule_id": rule_id, "synonyms": body.synonyms}


@router.delete("/{set_id}/rules/{rule_id}", summary="Delete a single synonym rule")
async def delete_rule(set_id: str, rule_id: str, es: AsyncElasticsearch = Depends(get_es)):
    try:
        await es.synonyms.delete_synonym_rule(set_id=set_id, rule_id=rule_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"deleted": f"{set_id}/{rule_id}"}


@router.post("/{set_id}/reload", summary="Reload search analyzers on the index (apply changes live)")
async def reload(set_id: str, es: AsyncElasticsearch = Depends(get_es)):
    """Reload search analyzers so updated synonym rules take effect immediately."""
    try:
        resp = await es.indices.reload_search_analyzers(index=get_settings().INDEX_NAME)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"set_id": set_id, "index": get_settings().INDEX_NAME, "reloaded": resp.get("reloaded_analyzers")}
