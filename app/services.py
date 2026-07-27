"""Shared search service.

Strategy:
  - **Address queries** (digit-start): single search, no tiering.
  - **Admin exact name match** (e.g. "dhaka" matches District name.raw): tiered —
    admin pool first (boost_mode=replace → popularity hierarchy), then POI pool.
    This puts Division/District/City at the top for locality searches.
  - **No admin exact** (e.g. "dse", "Dhaka Stock Exchange"): single query where
    POI exact/text matches rank naturally (no admin tiering).
  - With focus: two-pool + rescore on the place pool.
"""
import copy
from typing import Optional

from elasticsearch import AsyncElasticsearch

from .ranking import POOL_SIZE, rescore_hits


async def fetch_two_pools(es: AsyncElasticsearch, index: str, base: dict,
                          lat: float, lon: float, limit: int) -> list:
    pool = min(max(POOL_SIZE, limit * 3), 50)
    prominence = copy.deepcopy(base)
    prominence["size"] = pool
    proximity = copy.deepcopy(base)
    proximity["size"] = pool
    proximity["track_scores"] = True
    proximity["sort"] = [{
        "_geo_distance": {"geo_location": {"lat": lat, "lon": lon},
                          "order": "asc", "unit": "km", "distance_type": "arc"},
    }]
    resp = await es.msearch(body=[{"index": index}, prominence, {"index": index}, proximity])
    hits = []
    for r in resp["responses"]:
        hits.extend((r.get("hits") or {}).get("hits", []))
    seen, uniq = set(), []
    for h in hits:
        hid = h.get("_id")
        if hid not in seen:
            seen.add(hid)
            uniq.append(h)
    return uniq


def _add_filter(body: dict, clause: dict) -> dict:
    b = copy.deepcopy(body)
    boolq = b["query"]["function_score"]["query"]["bool"]
    existing = boolq.get("filter")
    if existing is None:
        boolq["filter"] = [clause]
    elif isinstance(existing, list):
        existing.append(clause)
    else:
        boolq["filter"] = [existing, clause]
    return b


def _add_must_not(body: dict, clause: dict) -> dict:
    b = copy.deepcopy(body)
    boolq = b["query"]["function_score"]["query"]["bool"]
    boolq.setdefault("must_not", []).append(clause)
    return b


async def _has_admin_exact(es: AsyncElasticsearch, index: str, q: str) -> bool:
    """Quick check: does any admin doc have name.raw == q (lowercased)?"""
    res = await es.search(index=index, body={
        "size": 1,
        "query": {"bool": {"filter": [
            {"term": {"pType": "Admin"}},
            {"term": {"name.raw": q.lower()}}
        ]}}
    })
    return len(res["hits"]["hits"]) > 0


async def _has_alias_exact(es: AsyncElasticsearch, index: str, q: str) -> bool:
    """Quick check: does any doc have an alter_name exactly equal to q (lowercased)?"""
    res = await es.search(index=index, body={
        "size": 1,
        "query": {"term": {"alter_names.raw": q.lower()}}
    })
    return len(res["hits"]["hits"]) > 0


def _merge_alias_first(alias_hits: list, hits: list, limit: int) -> list:
    """Prepend exact-alias hits ahead of the main results (deduped by _id, sliced)."""
    if not alias_hits:
        return hits
    seen, merged = set(), []
    for h in alias_hits + hits:
        if h["_id"] not in seen:
            seen.add(h["_id"])
            merged.append(h)
    return merged[:limit]


async def ranked_search(es: AsyncElasticsearch, index: str, q: str, builder,
                        *, lat=None, lon=None, limit: int = 10, debug: bool = False,
                        **builder_kw) -> tuple[list, Optional[list]]:
    from .queries.common import is_address_query

    body = builder(q, lat=lat, lon=lon, **builder_kw)
    score_debug = None

    # ── exact-alias tier ───────────────────────────────────────────────────
    # A place whose alter_name exactly equals the query is "known by exactly this
    # name" — a stronger signal than a POI whose name merely contains the query.
    # Such POIs otherwise outrank the alias (the name field's match_phrase_prefix
    # inflates their score), so exact-alias docs are pulled into a deterministic top tier.
    alias_hits = []
    if await _has_alias_exact(es, index, q):
        alias_body = _add_filter(body, {"term": {"alter_names.raw": q.lower()}})
        alias_body["size"] = min(limit, 5)
        alias_res = await es.search(index=index, body=alias_body)
        alias_hits = alias_res["hits"]["hits"]

    # ── address queries: single search ──────────────────────────────────────
    if is_address_query(q):
        if lat is not None and lon is not None:
            pool = await fetch_two_pools(es, index, body, lat, lon, limit)
            ordered, score_debug = rescore_hits(pool, lat, lon)
            hits = ordered[:limit]
            score_debug = score_debug[:limit] if debug else None
        else:
            body["size"] = limit
            res = await es.search(index=index, body=body)
            hits = res["hits"]["hits"]
        return _merge_alias_first(alias_hits, hits, limit), score_debug

    # ── check if admin has exact name match → conditional tiering ────────────
    do_tier = await _has_admin_exact(es, index, q)

    if do_tier:
        # admin pool: 5x pop factor so hierarchy dominates but exact name matches
        # (e.g. Mirpur Area) still rank above weak-match high-pop docs (e.g. Daulatpur City)
        admin_body = _add_filter(body, {"term": {"pType": "Admin"}})
        fvf = admin_body["query"]["function_score"]["functions"][0]["field_value_factor"]
        fvf["factor"] = round(fvf["factor"] * 5.0, 6)
        admin_body["size"] = min(limit, 8)
        admin_res = await es.search(index=index, body=admin_body)
        admin_hits = admin_res["hits"]["hits"]

        # place pool: non-admin, with rescore if focused
        place_body = _add_must_not(body, {"term": {"pType": "Admin"}})
        if lat is not None and lon is not None:
            place_pool = await fetch_two_pools(es, index, place_body, lat, lon, limit)
            ordered, score_debug = rescore_hits(place_pool, lat, lon)
            place_hits = ordered[:limit]
            score_debug = score_debug[:limit] if debug else None
        else:
            place_body["size"] = limit
            place_res = await es.search(index=index, body=place_body)
            place_hits = place_res["hits"]["hits"]

        # merge admin first, then places
        seen, merged = set(), []
        for h in admin_hits + place_hits:
            if h["_id"] not in seen:
                seen.add(h["_id"])
                merged.append(h)
        return _merge_alias_first(alias_hits, merged[:limit], limit), score_debug

    # ── no admin exact: single query (POI/brand searches) ───────────────────
    if lat is not None and lon is not None:
        pool = await fetch_two_pools(es, index, body, lat, lon, limit)
        ordered, score_debug = rescore_hits(pool, lat, lon)
        hits = ordered[:limit]
        score_debug = score_debug[:limit] if debug else None
    else:
        body["size"] = limit
        res = await es.search(index=index, body=body)
        hits = res["hits"]["hits"]
    return _merge_alias_first(alias_hits, hits, limit), score_debug
