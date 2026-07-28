"""List / inspect the managed synonym set in Elasticsearch.

Usage:
    python scripts/check_synonyms.py                      # list all rules
    python scripts/check_synonyms.py --filter hq          # rules containing 'hq'
    python scripts/check_synonyms.py --analyze "pathao hq"  # show name_search_analyzer expansion
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from elasticsearch import Elasticsearch

from app.config import get_settings


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--filter", default=None,
                    help="show only rules whose text contains this substring (case-insensitive)")
    ap.add_argument("--analyze", default=None,
                    help="show how the index's name_search_analyzer expands this text")
    args = ap.parse_args()

    s = get_settings()
    es = Elasticsearch(
        hosts=[s.ES_HOST],
        basic_auth=(s.ES_USER, s.ES_PASSWORD),
        verify_certs=s.ES_VERIFY_CERTS,
        ca_certs=s.ES_CA_CERTS or None,
    )

    rules = es.synonyms.get_synonym(id=s.SYNONYM_SET_ID).get("synonyms_set", [])
    needle = (args.filter or "").lower()
    shown = [r for r in rules
             if (not needle) or (needle in (r.get("synonyms") or "").lower())]

    label = f", {len(shown)} matching {needle!r}" if needle else ""
    print(f"synonym set {s.SYNONYM_SET_ID!r}: {len(rules)} rule(s){label}")
    for r in shown:
        text = r.get("synonyms", "")
        kind = "one-way" if "=>" in text else "equiv  "
        print(f"  [{r.get('id')}] {kind}  {text}")

    if args.analyze is not None:
        out = es.indices.analyze(
            index=s.INDEX_NAME,
            body={"analyzer": "name_search_analyzer", "text": args.analyze},
        )
        toks = [t["token"] for t in out["tokens"]]
        print(f"\nname_search_analyzer({args.analyze!r}) -> {toks}")

    es.close()


if __name__ == "__main__":
    main()
