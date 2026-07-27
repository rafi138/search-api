"""ES index settings + mapping for the ``places`` index.

Improvements over the legacy mapping:
  * ``business_name`` and ``place_name`` get a ``.complete`` sub-field
    (edge-n-gram autocomplete + a search analyzer with the managed **synonyms set**),
    so prefix + synonym matching works on names — not just on ``new_address``.
  * Deduped field set (no ``Address``/``address``/``new_address`` triple, no
    ``type``/``sub_type`` + ``pType``/``subType`` duplicates, no ``union``/``unions``).
  * Single index (admin docs live here with a popularity uplift — no admin index).

The ``synonyms_set`` referenced by the filter is created separately via the managed
``PUT _synonyms/<id>`` API (see scripts/manage_synonyms.py).
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


def analysis_settings(synonym_set_id: str) -> dict:
    return {
        "analysis": {
            "filter": {
                "bangla_synonym": {
                    "type": "synonym",
                    "synonyms_set": synonym_set_id,
                    "lenient": True,
                    "updateable": True,
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
            "name": _NAME_FIELD,
            "alter_names": _NAME_FIELD,
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


def build_index_body(synonym_set_id: str) -> dict:
    return {"settings": analysis_settings(synonym_set_id), "mappings": mapping_properties()}
