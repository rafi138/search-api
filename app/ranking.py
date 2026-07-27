"""Ranking: photon-style blend (text + popularity + proximity) + admin boost,
plus a Python re-rank (two-pool, per-query relevance) used for focus queries.

Default sort is popularity-weighted (Typesense-style ``popularity_ranking:desc``);
admin places get an extra boost (single index, no separate admin index).

Constants here are shared by the query builders (``app.queries``) so the ES
function_score and the Python re-rank estimate text contribution consistently.
"""
import math

from . import popularity

# ── photon function constants ────────────────────────────────────────────────
IMPORTANCE_FACTOR = 30.0
POP_SCALE = popularity.POP_MAX           # 200 (used for rescore normalization)
DECAY = 0.5
DEFAULT_ZOOM = 12
DEFAULT_SCALE = 0.4                      # importance-vs-proximity split when focused
POP_BOOST = 1.0                          # field_value_factor multiplier on popularity_ranking (no focus)
POP_BOOST_ADDRESS = 0.1                  # reduced for address/digit queries (text relevance dominates)
ADMIN_BOOST = 60.0                       # admin docs beat same-name POIs for locality searches
EXACT_BOOST = 100.0                      # exact name match (term on .raw) — the locality/name IS the query wins
PREFIX_BOOST = 50.0                      # name STARTS with the query (prefix on .raw) — left-to-right priority

# ── Python re-rank constants (focus queries) ─────────────────────────────────
POOL_SIZE = 25                           # per-pool candidate count
RESCORE_SCALE_KM = 10.0                  # harmonic proximity scale
RESCORE_REL_GATE = 0.30                  # drop candidates below 30% of best est_text
RESCORE_W_PROX, RESCORE_W_POP, RESCORE_W_REL = 0.50, 0.05, 0.45  # proximity suppresses far; name-text wins co-located ties


def zoom_to_radius(zoom: int) -> float:
    return (2.2 ** (18 - zoom)) * 0.1


def decay_radius(zoom: int) -> float:
    return max(8.0, zoom_to_radius(zoom) * (zoom - 3))


def haversine_km(lat1, lon1, lat2, lon2) -> float | None:
    try:
        lat1, lon1, lat2, lon2 = float(lat1), float(lon1), float(lat2), float(lon2)
    except (TypeError, ValueError):
        return None
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _exp_decay_term(d_km, offset, scale, decay=DECAY) -> float:
    if d_km is None:
        return 0.0
    if d_km <= offset:
        return 1.0
    return decay ** ((d_km - offset) / (scale - offset))


def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _focus_terms(zoom=DEFAULT_ZOOM, scale=DEFAULT_SCALE):
    return (zoom_to_radius(zoom), decay_radius(zoom),
            (IMPORTANCE_FACTOR * scale) / POP_SCALE,
            IMPORTANCE_FACTOR * (1 - scale))


def rescore_hits(hits: list, focus_lat: float, focus_lon: float,
                 zoom: int = DEFAULT_ZOOM, scale: float = DEFAULT_SCALE):
    """Re-rank ES hits by the normalized prox/pop/text blend (focus queries).

    Returns (ordered_hits, debug_rows). Per-query min-max rel prevents a fixed
    band from capping co-located matches; a relevance gate demotes weak matches.
    """
    offset, es_scale, pop_factor, loc_weight = _focus_terms(zoom, scale)
    rows = []
    for h in hits:
        s = h.get("_source", {}) or {}
        ptype = s.get("pType") or s.get("type")
        sub = s.get("subType") or s.get("sub_type")
        indexed_pop = s.get("popularity_ranking") or 0
        scheme_pop = popularity.rank(ptype, sub)
        lat = _to_float(s.get("latitude"))
        lon = _to_float(s.get("longitude"))
        d = haversine_km(lat, lon, focus_lat, focus_lon) if (lat is not None and lon is not None) else None
        prox = (1.0 / (1.0 + d / RESCORE_SCALE_KM)) if d is not None else 0.0
        # estimate text part of _score by subtracting the ES function terms
        pop_term = pop_factor * indexed_pop
        prox_term = loc_weight * _exp_decay_term(d, offset, es_scale)
        admin_term = ADMIN_BOOST if popularity.is_admin(ptype) else 0.0
        text_contrib = max((h.get("_score") or 0.0) - pop_term - prox_term - admin_term, 1.0)
        rows.append({"h": h, "s": s, "ptype": ptype, "sub": sub,
                     "indexed_pop": indexed_pop, "scheme_pop": scheme_pop,
                     "d": d, "prox": prox, "pop_term": pop_term,
                     "prox_term": prox_term, "admin_term": admin_term, "text": text_contrib})
    if not rows:
        return [], []

    max_text = max(r["text"] for r in rows)
    threshold = RESCORE_REL_GATE * max_text
    rel_texts = [r["text"] for r in rows if r["text"] >= threshold] or [max_text]
    min_text = min(rel_texts)
    span = (max_text - min_text) or 1.0

    feats = []
    for r in rows:
        rel = max(0.0, min(1.0, (r["text"] - min_text) / span))
        blend = (RESCORE_W_PROX * r["prox"]
                 + RESCORE_W_POP * (r["scheme_pop"] / POP_SCALE)
                 + RESCORE_W_REL * rel)
        passed = r["text"] >= threshold
        dbg = {
            "place_code": r["s"].get("place_code") or r["s"].get("uCode") or r["s"].get("id"),
            "name": _name_of(r["s"]),
            "es_score": round(r["h"].get("_score") or 0.0, 3),
            "popularity": r["scheme_pop"], "indexed_popularity": r["indexed_pop"],
            "distance_km": round(r["d"], 3) if r["d"] is not None else None,
            "es_terms": {"pop": round(r["pop_term"], 3), "prox": round(r["prox_term"], 3),
                         "admin": round(r["admin_term"], 3), "est_text": round(r["text"], 3)},
            "rescore": {"prox": round(r["prox"], 4), "pop": round(r["scheme_pop"] / POP_SCALE, 4),
                        "rel": round(rel, 4), "blend": round(blend, 4)},
            "rel_gate": {"threshold": round(threshold, 3), "passed": bool(passed)},
            "weights": {"prox": RESCORE_W_PROX, "pop": RESCORE_W_POP, "rel": RESCORE_W_REL},
        }
        feats.append((blend, r["text"], r["h"], dbg))

    relevant = [f for f in feats if f[1] >= threshold]
    weak = [f for f in feats if f[1] < threshold]
    relevant.sort(key=lambda f: f[0], reverse=True)
    weak.sort(key=lambda f: f[0], reverse=True)
    ordered = relevant + weak
    return [f[2] for f in ordered], [f[3] for f in ordered]


def _name_of(s: dict) -> str:
    return (s.get("business_name") or s.get("place_name") or s.get("area")
            or (s.get("new_address") or "").split(",")[0].strip() or "")
