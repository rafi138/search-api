"""Push synonyms (Postgres places_synonyms + MongoDB eLocations.synonyms) into the
ES managed synonym set (source of truth), then apply them to the index via
close/reopen (the inline synonym_graph filter can't use a managed set; no reindex).

- Postgres: ``places_synonyms(barikoi_phrase, synonym)`` -> one-way "synonym => barikoi_phrase".
- MongoDB:  ``{synonyms: [equivalent spellings...]}`` -> multi-way "t1, t2, ...".

Usage:
    python scripts/manage_synonyms.py --preview          # show rule count + samples
    python scripts/manage_synonyms.py --apply            # PUT set + reload analyzers
    python scripts/manage_synonyms.py --apply --no-mongo # only Postgres
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from elasticsearch import Elasticsearch

from app.config import get_settings


def load_db_synonyms() -> list[str]:
    import psycopg2
    s = get_settings()
    conn = psycopg2.connect(host=s.DB_HOST, port=s.DB_PORT, user=s.DB_USER,
                            password=s.DB_PASSWORD, dbname=s.DB_NAME)
    try:
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT barikoi_phrase, synonym FROM places_synonyms "
                    "WHERE barikoi_phrase IS NOT NULL AND synonym IS NOT NULL")
        rules = [f"{syn} => {phrase}" for phrase, syn in cur.fetchall()]
    finally:
        conn.close()
    return rules


def load_mongo_synonyms() -> list[str]:
    s = get_settings()
    if not s.MONGO_URI:
        return []
    from pymongo import MongoClient
    client = MongoClient(s.MONGO_URI, serverSelectionTimeoutMS=10000)
    rules, seen = [], set()
    try:
        for doc in client[s.MONGO_DB]["synonyms"].find({}, {"synonyms": 1}):
            uniq, ulow = [], set()
            for t in (doc.get("synonyms") or []):
                t = str(t).strip()
                if t and t.lower() not in ulow:
                    ulow.add(t.lower())
                    uniq.append(t)
            if len(uniq) < 2:
                continue
            rule = ", ".join(uniq)
            if rule.lower() not in seen:
                seen.add(rule.lower())
                rules.append(rule)
    finally:
        client.close()
    return rules


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--no-mongo", action="store_true")
    ap.add_argument("--no-db", action="store_true")
    args = ap.parse_args()
    if not (args.preview or args.apply):
        ap.print_help(); return

    rules = []
    if not args.no_db:
        rules += load_db_synonyms()
    if not args.no_mongo:
        rules += load_mongo_synonyms()
    print(f"{len(rules)} synonym rules (db={not args.no_db}, mongo={not args.no_mongo}).")
    for r in rules[:8]:
        print("  ", r[:110])

    if not args.apply:
        return

    s = get_settings()
    es = Elasticsearch(hosts=[s.ES_HOST], basic_auth=(s.ES_USER, s.ES_PASSWORD),
                       verify_certs=s.ES_VERIFY_CERTS, ca_certs=s.ES_CA_CERTS or None)
    es.synonyms.put_synonym(id=s.SYNONYM_SET_ID,
                            body={"synonyms_set": [{"synonyms": r} for r in rules]})
    print(f"updated synonym set {s.SYNONYM_SET_ID!r} (source of truth).")
    # apply to the index: the inline synonym_graph filter can't use a managed set, so
    # close -> update the inline rules -> reopen (no reindex; brief unavailability).
    idx = s.INDEX_NAME
    try:
        es.indices.close(index=idx)
        es.indices.put_settings(index=idx, body={"analysis": {"filter": {"bangla_synonym": {
            "type": "synonym_graph", "synonyms": rules, "lenient": True}}}})
        es.indices.open(index=idx)
        es.cluster.health(index=idx, wait_for_status="yellow", timeout="60s")
        print(f"applied {len(rules)} rule(s) to {idx!r} via close/reopen (no reindex).")
    except Exception as e:
        try:
            es.indices.open(index=idx)
        except Exception:
            pass
        print(f"apply via close/reopen failed (set updated but NOT applied): {e}")


if __name__ == "__main__":
    main()
