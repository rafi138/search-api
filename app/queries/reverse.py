"""Reverse geocoding query builder.

Per-subtype msearch: one query per admin subtype (nearest doc, size=1) + one POI
query (within 50m, nearest first). Guarantees every admin subtype is represented
regardless of how many small admin docs crowd the area.
"""

ADMIN_HIERARCHY = [
    "Division", "District", "Sub District", "Thana", "Union",
    "Area", "Subarea", "Village", "Supersubarea", "Road",
]

POI_RADIUS = "50m"
POI_POOL = 10


def _geo_sort(lat: float, lon: float) -> list:
    return [{"_geo_distance": {
        "geo_location": {"lat": lat, "lon": lon},
        "order": "asc", "unit": "km", "distance_type": "arc",
    }}]


def build_reverse_msearch(lat: float, lon: float, index: str) -> list:
    """Return msearch body: one sub-query per admin subtype + one POI query."""
    body = []
    for st in ADMIN_HIERARCHY:
        q = {
            "size": 1,
            "query": {"bool": {"filter": [
                {"term": {"pType": "Admin"}},
                {"term": {"subType": st}},
            ]}},
            "sort": _geo_sort(lat, lon),
        }
        body.extend([{"index": index}, q])
    # POI query (non-admin within 50m)
    poi = {
        "size": POI_POOL,
        "query": {"bool": {
            "must_not": [{"term": {"pType": "Admin"}}],
            "filter": [{"geo_distance": {
                "distance": POI_RADIUS, "geo_location": {"lat": lat, "lon": lon},
            }}],
        }},
        "sort": _geo_sort(lat, lon),
    }
    body.extend([{"index": index}, poi])
    return body


def hierarchy_rank(subtype: str | None) -> int:
    """Sort key for admin subtypes by the hierarchy (0 = Division = first)."""
    from .reverse import ADMIN_HIERARCHY
    if subtype and subtype in ADMIN_HIERARCHY:
        return ADMIN_HIERARCHY.index(subtype)
    return len(ADMIN_HIERARCHY)
