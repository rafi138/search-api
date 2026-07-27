"""Popularity ranking scheme (single source of truth).

Admin ptype -> administrative-granularity hierarchy (largest unit highest).
Non-Admin  -> search-frequency tier by type. Scale 0-200.

Self-contained copy (kept inside this project so it has no dependency on the old
codebase). The indexer applies ``rank()`` at index time; the API ranking uses it
for rescore + admin boost.
"""

# Admin sub_type (lowercase) -> score
ADMIN_RANK = {
    "division": 195,
    "district": 190,
    "city": 185,
    "thana": 180,
    "sub district": 178,
    "paurashava": 176,
    "union": 170,
    "area": 160,
    "subarea": 150,
    "supersubarea": 140,
    "micro_area": 130,
    "road": 90,
    "village": 80,
}
ADMIN_DEFAULT = 120

# Non-admin pType (exact case) -> score
TYPE_RANK = {
    "Bank": 140, "Healthcare": 135, "Transportation": 132, "Food": 128,
    "Education": 128, "Fuel": 125, "Hotel": 120,
    "Shop": 108, "Landmark": 95, "Commercial": 92, "Government": 88,
    "Office": 82, "Religious Place": 78, "Recreation": 72,
    "Residential": 55, "Utility": 48, "Industry": 42,
    "Agricultural": 38, "Construction": 32, "Others": 25,
}
TYPE_DEFAULT = 25

POP_MAX = 200.0


def rank(ptype, sub_type) -> int:
    """Return the popularity_ranking for a place by type/sub_type."""
    if ptype and str(ptype).strip().lower() == "admin":
        key = str(sub_type).strip().lower() if sub_type else ""
        return ADMIN_RANK.get(key, ADMIN_DEFAULT)
    return TYPE_RANK.get(str(ptype).strip() if ptype is not None else "", TYPE_DEFAULT)


def is_admin(ptype) -> bool:
    return bool(ptype) and str(ptype).strip().lower() == "admin"
