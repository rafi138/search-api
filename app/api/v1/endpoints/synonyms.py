"""Managed synonyms endpoints (ES ``_synonyms`` API).

Edit the managed ``places_synonyms`` set (create/replace, list/get/delete, upsert/
delete a single rule). The index uses an inline ``synonym_graph`` filter, so to APPLY
edits call ``POST /{set_id}/reload`` — it closes the index, updates the inline rules,
and reopens (no reindex; the index is briefly unavailable while closed).
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


@router.post("/{set_id}/reload", summary="Apply this set's synonyms to the index (close/reopen, no reindex)")
async def reload(set_id: str, es: AsyncElasticsearch = Depends(get_es)):
    """Apply the managed set's synonym rules to the index.

    The index uses an inline ``synonym_graph`` filter (which can't reference a managed
    set), so changes are applied by closing the index, updating the filter's inline
    rules from this set, and reopening — NO reindex. The index is briefly unavailable
    while closed (a few seconds). Edit the rules first (PUT/DELETE rule, or PUT set).
    """
    settings = get_settings()
    try:
        resp = await es.synonyms.get_synonym(id=set_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))
    rules = [r["synonyms"] for r in (resp.get("synonyms_set") or [])
             if isinstance(r, dict) and r.get("synonyms")]
    idx = settings.INDEX_NAME
    try:
        await es.indices.close(index=idx)
        await es.indices.put_settings(index=idx, body={"analysis": {"filter": {"bangla_synonym": {
            "type": "synonym_graph", "synonyms": rules, "lenient": True}}}})
        await es.indices.open(index=idx)
        await es.cluster.health(index=idx, wait_for_status="yellow", timeout="60s")
    except Exception as e:
        try:  # best-effort reopen if something failed mid-way
            await es.indices.open(index=idx)
        except Exception:
            pass
        raise HTTPException(status_code=400, detail=str(e))
    return {"set_id": set_id, "index": idx, "applied_rules": len(rules),
            "method": "close/reopen (synonym_graph inline, no reindex)"}
