"""Create the managed synonym set + the ``places`` index.

The index's ``bangla_synonym`` filter references the synonym set by id, so synonym
updates (via scripts/manage_synonyms.py or the /v1/synonyms API) take effect with a
``reload_search_analyzers`` — no close/reopen, no reindex.

Usage:
    python scripts/create_index.py                 # create if absent
    python scripts/create_index.py --force         # delete + recreate
    python scripts/create_index.py --index places  # override index name
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from elasticsearch import Elasticsearch

from app.config import get_settings
from app.schema.mapping import build_index_body


def ensure_synonym_set(es: Elasticsearch, set_id: str) -> None:
    try:
        es.synonyms.get_synonym(id=set_id)
        print(f"synonym set {set_id!r} exists.")
    except Exception:
        es.synonyms.put_synonym(id=set_id, body={"synonyms_set": []})
        print(f"synonym set {set_id!r} created (empty — populate via scripts/manage_synonyms.py).")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", default=None)
    ap.add_argument("--force", action="store_true", help="delete and recreate the index")
    args = ap.parse_args()

    s = get_settings()
    index = args.index or s.INDEX_NAME
    es = Elasticsearch(hosts=[s.ES_HOST], basic_auth=(s.ES_USER, s.ES_PASSWORD),
                       verify_certs=s.ES_VERIFY_CERTS, ca_certs=s.ES_CA_CERTS or None)

    ensure_synonym_set(es, s.SYNONYM_SET_ID)

    if es.indices.exists(index=index):
        if not args.force:
            print(f"index {index!r} already exists (use --force to recreate).")
            return
        es.indices.delete(index=index)
        print(f"deleted index {index!r}.")

    es.indices.create(index=index, body=build_index_body(s.SYNONYM_SET_ID))
    print(f"created index {index!r} referencing synonym set {s.SYNONYM_SET_ID!r}.")


if __name__ == "__main__":
    main()
