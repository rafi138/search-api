"""ES index settings + mapping for the ``places`` index.

Improvements over the legacy mapping:
  * ``business_name`` and ``place_name`` get a ``.complete`` sub-field
    (edge-n-gram autocomplete + a search analyzer with **synonyms**),
    so prefix + synonym matching works on names — not just on ``new_address``.
  * Deduped field set (no ``Address``/``address``/``new_address`` triple, no
    ``type``/``sub_type`` + ``pType``/``subType`` duplicates, no ``union``/``unions``).
  * Single index (admin docs live here with a popularity uplift — no admin index).

Synonyms use the ``synonym_graph`` filter (not ``synonym``) so **multi-word** synonyms
(e.g. "head office" == "hq") are treated as single concepts. ``synonym_graph`` cannot
reference a managed/updated synonym set, so the rules are passed **inline** and baked
into the index at creation time (scripts/create_index.py reads the managed
``places_synonyms`` set as the source of truth). Applying synonym edits therefore
requires recreating the index (no live ``_reload_search_analyzers``).
"""

# A name-style text field: base tokenization + synonyms at search time, an
# edge-ngram ``.complete`` sub-field for type-ahead, and a lowercased ``.raw``
# keyword for exact-name matching.
_NAME_FIELD = {
    "type": "text",
    "analyzer": "standard",
    "search_analyzer": "name_search_analyzer",
    "fields": {
        "complete": {
            "type": "text",
            "analyzer": "autocomplete_analyzer",
            "search_analyzer": "autocomplete_search_analyzer",
        },
        "raw": {"type": "keyword", "normalizer": "lowercase"},
    },
}

# Full-address style field (kept for address/area searches).
_ADDRESS_FIELD = {
    "type": "text",
    "analyzer": "standard",
    "search_analyzer": "autocomplete_search_analyzer",
    "fields": {
        "complete": {
            "type": "text",
            "analyzer": "autocomplete_analyzer",
            "search_analyzer": "autocomplete_search_analyzer",
        }
    },
}

_ADMIN_TEXT_FIELD = {  # locality fields: text + lowercased raw keyword (exact match)
    "type": "text", "analyzer": "standard",
    "fields": {"raw": {"type": "keyword", "normalizer": "lowercase"}},
}


def analysis_settings(synonyms: list[str]) -> dict:
    return {
        "analysis": {
            "filter": {
                # synonym_graph (not synonym) handles multi-word synonyms like
                # "head office" as a single concept. It can't use a managed/updated
                # set, so the rules are inline — baked in at index creation.
                "bangla_synonym": {
                    "type": "synonym_graph",
                    "synonyms": list(synonyms or []),
                    "lenient": True,
                },
            },
            "normalizer": {
                "lowercase": {"type": "custom", "filter": ["lowercase"]},
            },
            "tokenizer": {
                "autocomplete": {"type": "edge_ngram", "min_gram": 1, "max_gram": 20},
            },
            "analyzer": {
                # indexing time for .complete fields (prefix tokens)
                "autocomplete_analyzer": {"tokenizer": "autocomplete", "filter": ["lowercase"]},
                # search time for .complete fields (keyword + synonyms)
                "autocomplete_search_analyzer": {"tokenizer": "keyword", "filter": ["lowercase", "bangla_synonym"]},
                # search time for base name/address fields (standard + synonyms)
                "name_search_analyzer": {"tokenizer": "standard", "filter": ["lowercase", "bangla_synonym"]},
            },
        }
    }


def mapping_properties() -> dict:
    return {
        "properties": {
            "id": {"type": "long"},
            "place_code": {"type": "keyword"},
            # name + alter_names copy into all_names so an alias matches/ranks like a
            # name (shared field stats) and each alias gets autocomplete (.complete).
            "name": {**_NAME_FIELD, "copy_to": "all_names"},
            "alter_names": {**_NAME_FIELD, "copy_to": "all_names"},
            "all_names": _NAME_FIELD,
            "business_name": _NAME_FIELD,
            "place_name": _NAME_FIELD,
            "new_address": _ADDRESS_FIELD,
            "address": _ADDRESS_FIELD,
            "address_bn": _ADDRESS_FIELD,
            "alternate_address": {"type": "text"},
            "area": _ADMIN_TEXT_FIELD,
            "area_bn": _ADMIN_TEXT_FIELD,
            "city": _ADMIN_TEXT_FIELD,
            "city_bn": _ADMIN_TEXT_FIELD,
            "district": _ADMIN_TEXT_FIELD,
            "thana": _ADMIN_TEXT_FIELD,
            "union": _ADMIN_TEXT_FIELD,
            "sub_area": _ADMIN_TEXT_FIELD,
            "super_sub_area": _ADMIN_TEXT_FIELD,
            "sub_district": _ADMIN_TEXT_FIELD,
            "postCode": {"type": "keyword"},
            "pType": {"type": "keyword"},
            "subType": {"type": "keyword"},
            "tags": {"type": "keyword"},
            "popularity_ranking": {"type": "integer"},
            "latitude": {"type": "keyword"},
            "longitude": {"type": "keyword"},
            "geo_location": {"type": "geo_point"},
            "location_shape": {"type": "geo_shape"},
            "bounds": {"type": "text", "index": False},  # large polygon WKT — stored, not indexed
            "created_at": {"type": "date"},
            "updated_at": {"type": "date"},
        }
    }


def build_index_body(synonyms: list[str]) -> dict:
    return {"settings": analysis_settings(synonyms), "mappings": mapping_properties()}
