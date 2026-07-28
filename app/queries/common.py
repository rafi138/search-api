"""Shared query builders: address vs name mode + function_score.

Address mode triggers ONLY when q starts with a pure digit pattern (e.g. "473 shewrapara",
"2/7 pallabi") — not for brand names like "10MS school" or "10 minute school".
"""
import re

from .. import ranking


def is_address_query(q: str) -> bool:
    """True if q looks like an address: starts with a pure house/road number."""
    return bool(re.match(r'^\d+[/\d]*\s+\D', q.strip()))


# keep old name for any remaining references
def has_digit(q: str) -> bool:
    return is_address_query(q)


def exact_should(q: str) -> list:
    """High-boost exact-name match (term on lowercased .raw)."""
    if is_address_query(q):
        return []
    ql = q.lower()
    return [
        {"term": {"all_names.raw": {"value": ql, "boost": ranking.EXACT_BOOST}}},
    ]


def address_should(q: str, fuzzy: bool = False) -> list:
    """Address search: new_address primary, name secondary."""
    f = {"fuzziness": "AUTO"} if fuzzy else {}
    return [
        {"match": {"new_address": {"query": q, "boost": 15, "analyzer": "name_search_analyzer", **f}}},
        {"match_phrase_prefix": {"new_address": {"query": q, "boost": 10, "analyzer": "name_search_analyzer"}}},
        {"match": {"new_address.complete": {"query": q, "boost": 8, **f}}},
        {"match": {"all_names": {"query": q, "boost": 10, **f}}},
        {"match": {"all_names.complete": {"query": q, "boost": 5}}},
        {"match": {"area": {"query": q, "boost": 3, **f}}},
    ]


def name_should(q: str, fuzzy: bool = False) -> list:
    """Name / locality search: exact + prefix + name primary + locality."""
    f = {"fuzziness": "AUTO"} if fuzzy else {}
    ql = q.lower()
    return [
        # name + alter_names combined (all_names): an alias matches/ranks like the name
        {"match": {"all_names": {"query": q, "boost": 12}}},
        {"match_phrase_prefix": {"all_names": {"query": q, "boost": 8}}},
        {"match": {"all_names.complete": {"query": q, "boost": 7}}},
        # prefix (name/alias STARTS with query — left-to-right priority)
        {"prefix": {"all_names.raw": {"value": ql, "boost": ranking.PREFIX_BOOST}}},
        # address + locality
        {"match": {"new_address": {"query": q, "boost": 4, "analyzer": "name_search_analyzer", **f}}},
        {"match_phrase_prefix": {"new_address": {"query": q, "boost": 3, "analyzer": "name_search_analyzer"}}},
        {"match": {"new_address.complete": {"query": q, "boost": 2, **f}}},
        {"match": {"area": {"query": q, "boost": 3, **f}}},
        {"match": {"district": {"query": q, "boost": 2, **f}}},
    ]


def digit_must(q: str) -> list | None:
    """For clear address queries (house numbers ≥3 digits or containing '/'):
    require the digit pattern in new_address as adjacent tokens (match_phrase).
    Skips short numbers like '10' or '5' (likely brand names, not house numbers)."""
    if not is_address_query(q):
        return None
    m = re.match(r'^(\d+[/\d]*)\s', q.strip())
    if not m:
        return None
    pat = m.group(1)
    if len(pat) >= 3 or '/' in pat:
        return [{"match_phrase": {"new_address": {"query": pat, "analyzer": "name_search_analyzer"}}}]
    return None


def all_words_must(q: str) -> list | None:
    """For multi-word queries (2+ tokens): require ALL query words to appear across
    all_names + new_address + area + district. Prevents docs matching only one word
    (e.g. admin areas matching just 'gulshan' for 'pathao gulshan').

    Uses name_search_analyzer, whose bangla_synonym filter is now ``synonym_graph``:
    multi-word synonyms like "head office" == "hq" are treated as one concept, so
    'pathao head office' matches a place named 'Pathao HQ'. (With the old non-graph
    'synonym' filter this over-constrained multi-word matches, so it briefly used the
    plain 'standard' analyzer; synonym_graph makes name_search_analyzer correct again.)
    """
    tokens = q.strip().split()
    if len(tokens) < 2:
        return None
    return [{"multi_match": {
        "query": q,
        "fields": ["all_names", "new_address", "area", "district"],
        "operator": "and",
        "type": "cross_fields",
        "analyzer": "name_search_analyzer",
    }}]


def build_should(q: str, fuzzy: bool = False) -> list:
    if is_address_query(q):
        return address_should(q, fuzzy=fuzzy)
    return exact_should(q) + name_should(q, fuzzy=fuzzy)


def parse_bbox(bbox: str | None) -> dict | None:
    if not bbox:
        return None
    parts = str(bbox).split(",")
    if len(parts) != 4:
        raise ValueError("bbox must be minlon,minlat,maxlon,maxlat")
    w, s, e, n = (float(x) for x in parts)
    return {"geo_bounding_box": {"geo_location": {
        "top_left": {"lat": n, "lon": w}, "bottom_right": {"lat": s, "lon": e}}}}


def normalize_radius(radius) -> str | None:
    if radius is None or radius == "":
        return None
    r = str(radius).strip()
    if r.lower().endswith("km"):
        return r
    try:
        float(r)
        return f"{r}km"
    except ValueError:
        return None


def build_function_score(should: list, *, limit: int = 10, lat=None, lon=None,
                         zoom: int = ranking.DEFAULT_ZOOM, scale: float = ranking.DEFAULT_SCALE,
                         from_: int = 0, bbox: str | None = None, radius=None,
                         address_mode: bool = False, must: list | None = None,
                         all_words: list | None = None) -> dict:
    iw = scale if (lat is not None and lon is not None) else 1.0
    pop_base = ranking.POP_BOOST_ADDRESS if address_mode else ranking.POP_BOOST
    pop_factor = pop_base * iw

    functions = [
        {"field_value_factor": {"field": "popularity_ranking",
                                "factor": round(pop_factor, 6),
                                "modifier": "none", "missing": 0.00001}},
    ]
    if not address_mode:
        functions.append({"filter": {"term": {"pType": "Admin"}}, "weight": ranking.ADMIN_BOOST})
    if lat is not None and lon is not None:
        functions.append({
            "weight": ranking.IMPORTANCE_FACTOR * (1 - iw),
            "exp": {"geo_location": {
                "origin": {"lat": lat, "lon": lon},
                "offset": f"{ranking.zoom_to_radius(zoom)}km",
                "scale": f"{ranking.decay_radius(zoom)}km",
                "decay": ranking.DECAY}},
        })

    boolq = {"should": should, "minimum_should_match": 1}
    if must:
        boolq["must"] = must
    if all_words:
        boolq.setdefault("must", []).extend(all_words)
    filters = []
    bb = parse_bbox(bbox)
    if bb:
        filters.append(bb)
    if lat is not None and lon is not None:
        r = normalize_radius(radius)
        if r:
            filters.append({"geo_distance": {"distance": r, "geo_location": {"lat": lat, "lon": lon}}})
    if filters:
        boolq["filter"] = filters

    return {
        "from": from_, "size": limit, "track_scores": True,
        "query": {"function_score": {
            "query": {"bool": boolq},
            "functions": functions,
            "score_mode": "sum", "boost_mode": "sum",
        }},
    }
