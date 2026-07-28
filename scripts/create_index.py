"""Ensure the managed synonym set exists + create the ``places`` index.

The index uses the ``synonym_graph`` filter with INLINE synonyms (synonym_graph can't
reference a managed/updated set). The managed ``places_synonyms`` set is kept as the
source of truth; this script reads its rules and bakes them into the index. So to
APPLY synonym edits, recreate the index (``--force``) — there is no live reload.

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

    # synonym_graph can't use a managed set, so bake the managed set's rules inline.
    synonyms = [r["synonyms"]
                for r in es.synonyms.get_synonym(id=s.SYNONYM_SET_ID)["synonyms_set"]]
    print(f"baking {len(synonyms)} synonym rule(s) inline (synonym_graph):")
    for r in synonyms[:8]:
        print(f"  {r[:100]}")

    if es.indices.exists(index=index):
        if not args.force:
            print(f"index {index!r} already exists (use --force to recreate).")
            return
        es.indices.delete(index=index)
        print(f"deleted index {index!r}.")

    es.indices.create(index=index, body=build_index_body(synonyms))
    print(f"created index {index!r} with {len(synonyms)} inline synonym rule(s).")
    print("note: to apply future synonym edits, re-run with --force (recreate).")


if __name__ == "__main__":
    main()
