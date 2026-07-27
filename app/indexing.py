"""Doc builder: maps a Postgres ``places`` row (joined with ``places_bangla``) to a
cleaned ES document.

Dedupes the legacy field sprawl (no Address/address/new_address triple, no
type/sub_type + pType/subType duplicates, no union/unions), applies the popularity
scheme, and shapes geo fields. Shared by the bulk and single indexers.
"""
from . import popularity


def concat_with_prefix(value, prefix: str) -> str:
    if value is None:
        return ""
    tokens = str(value).split()
    if len(tokens) == 1 and any(c.isdigit() for c in tokens[0]) and not str(value).startswith(prefix):
        return f"{prefix} {value}"
    return str(value)


def _join_unique(parts) -> str | None:
    """Join non-empty parts with ', ', dropping consecutive duplicates (case-insensitive).

    Avoids inflated addresses like 'Mirpur, Mirpur, Mirpur' (when name/area/city are
    all the same) which would otherwise over-boost text matches for that doc.
    """
    out, prev = [], None
    for p in parts:
        if not p:
            continue
        s = str(p).strip()
        if not s:
            continue
        key = s.lower()
        if key != prev:
            out.append(s)
            prev = key
    return ", ".join(out) or None


def _collect_alter_names(row: dict):
    """Per-place aliases for the ``alter_names`` field
    (e.g. ``['pathao hq', 'pathao gulshan head office']``).

    Returns None for now (no source in the DB). Wire a source here later — e.g. load
    a CSV (place_code -> aliases) once and merge per place. The field, mapping and
    query are already wired, so populating this is the only change needed.
    """
    return None


def build_doc(row: dict, existing_alter_names=None) -> dict:
    """row keys: places.* + bounds_geom + address_bn/area_bn/city_bn (from the join).

    alter_names are authored via the API (stored only in ES), so pass the doc's
    existing alter_names to preserve them across a reindex (else they're lost).
    """
    r = row
    lat = r.get("latitude")
    lon = r.get("longitude")
    lat_s = str(lat) if lat is not None else None
    lon_s = str(lon) if lon is not None else None

    ptype = r.get("type")
    sub = r.get("sub_type")

    bn = (r.get("business_name") or "").strip() or None
    pn = (r.get("place_name") or "").strip() or None
    name = bn or pn  # canonical name = business_name else place_name

    # alter_names: preserve aliases already in ES (passed by the indexers); fall back
    # to the (currently empty) DB source hook.
    alter = existing_alter_names if existing_alter_names is not None else _collect_alter_names(r)

    # new_address excludes the name (it lives in `name`/`alter_names` now)
    new_address = _join_unique([
        concat_with_prefix(r.get("holding_number"), "House "),
        concat_with_prefix(r.get("road_name_number"), "Road "),
        r.get("super_sub_area"), r.get("sub_area"), r.get("area"), r.get("city"),
    ])
    address_bn = ", ".join(filter(None, [r.get("address_bn"), r.get("city_bn")])) or None

    doc = {
        "id": r.get("id"),
        "place_code": r.get("place_code"),
        "name": name,
        "business_name": bn,
        "place_name": pn,
        "alter_names": alter,
        "new_address": new_address,
        "address": r.get("address"),
        "address_bn": address_bn,
        "area": r.get("area"),
        "area_bn": r.get("area_bn"),
        "city": r.get("city"),
        "city_bn": r.get("city_bn"),
        "district": r.get("district"),
        "thana": r.get("thana"),
        "union": r.get("union"),
        "sub_area": r.get("sub_area"),
        "super_sub_area": r.get("super_sub_area"),
        "sub_district": r.get("sub_district"),
        "postCode": r.get("postcode"),
        "pType": ptype,
        "subType": sub,
        "popularity_ranking": popularity.rank(ptype, sub),
        "latitude": lat_s,
        "longitude": lon_s,
        "bounds": r.get("bounds_geom"),
        "created_at": r.get("created_at"),
        "updated_at": r.get("updated_at"),
    }
    if lat is not None and lon is not None:
        try:
            doc["geo_location"] = {"lat": float(lat), "lon": float(lon)}
            doc["location_shape"] = f"POINT ({lon_s} {lat_s})"
        except (TypeError, ValueError):
            pass
    return {k: v for k, v in doc.items() if v is not None}
