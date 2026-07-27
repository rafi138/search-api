"""Bulk indexer: Postgres ``places`` (+ places_bangla) -> ES ``places`` index.

Server-side cursor + bulk index in chunks, with a tqdm progress bar. Applies the
popularity scheme; writes one doc per place with ``_id = uCode``. Skips poles.

Usage:
    python scripts/index_places.py                  # full reindex
    python scripts/index_places.py --batch 5000
    python scripts/index_places.py --limit 10000    # cap (for testing)
    python scripts/index_places.py --index places
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import psycopg2
from psycopg2.extras import RealDictCursor
from elasticsearch import Elasticsearch, helpers
from tqdm import tqdm

from app.config import get_settings
from app.indexing import build_doc

SQL = """
    SELECT p.*,
           ST_AsText(ST_SimplifyPreserveTopology(p.bounds, 0.0001)) AS bounds_geom,
           pb.address AS address_bn, pb.area AS area_bn, pb.city AS city_bn
    FROM places p
    LEFT JOIN places_bangla pb ON p.place_code = pb.place_code
    WHERE p.sub_type NOT ILIKE '%%pole%%'
    ORDER BY p.id
"""


def stream_rows(conn, batch):
    """Server-side cursor yielding rows in batches (low memory for 2M+ rows)."""
    cur = conn.cursor(name="places_cursor", cursor_factory=RealDictCursor)
    cur.itersize = batch
    cur.execute(SQL)
    while True:
        rows = cur.fetchmany(batch)
        if not rows:
            break
        yield rows
    cur.close()


def scan_alter_names(es, index):
    """Return {place_code: alter_names} for every doc that has alter_names."""
    out = {}
    query = {"_source": ["place_code", "alter_names"],
             "query": {"exists": {"field": "alter_names"}}}
    for hit in helpers.scan(es, index=index, query=query, size=5000, scroll="2m"):
        src = hit["_source"]
        pc = src.get("place_code") or hit["_id"]
        out[pc] = src.get("alter_names")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", default=None)
    ap.add_argument("--batch", type=int, default=10000)
    ap.add_argument("--limit", type=int, default=None, help="cap rows (testing)")
    ap.add_argument("--alter-names-json", default=None,
                    help="load {place_code: alter_names} from FILE (overrides live scan)")
    ap.add_argument("--dump-alter-names", default=None,
                    help="dump current alter_names to FILE and exit (migration helper)")
    args = ap.parse_args()

    s = get_settings()
    index = args.index or s.INDEX_NAME
    es = Elasticsearch(hosts=[s.ES_HOST], basic_auth=(s.ES_USER, s.ES_PASSWORD),
                       verify_certs=s.ES_VERIFY_CERTS, ca_certs=s.ES_CA_CERTS or None,
                       request_timeout=120)

    if args.dump_alter_names:
        preserve = scan_alter_names(es, index)
        with open(args.dump_alter_names, "w") as fh:
            json.dump(preserve, fh)
        print(f"dumped {len(preserve)} alias docs to {args.dump_alter_names}")
        return

    if args.alter_names_json:
        with open(args.alter_names_json) as fh:
            preserve = json.load(fh)
        print(f"loaded {len(preserve)} alias docs from {args.alter_names_json}")
    else:
        preserve = scan_alter_names(es, index)
        print(f"preserving {len(preserve)} alias docs from live index")

    conn = psycopg2.connect(host=s.DB_HOST, port=s.DB_PORT, user=s.DB_USER,
                            password=s.DB_PASSWORD, dbname=s.DB_NAME)

    total = None
    try:
        c = conn.cursor()
        c.execute("SELECT count(*) FROM places WHERE sub_type NOT ILIKE '%%pole%%'")
        total = c.fetchone()[0]
        c.close()
    except Exception:
        pass
    if args.limit:
        total = min(total or args.limit, args.limit)

    print(f"Indexing into {index!r} (batch={args.batch}"
          + (f", total≈{total:,}" if total else "") + ")")

    done = errors = 0
    pbar = tqdm(total=total, unit="docs", desc="index")
    for chunk in stream_rows(conn, args.batch):
        if args.limit and done >= args.limit:
            break
        if args.limit and done + len(chunk) > args.limit:
            chunk = chunk[: args.limit - done]
        actions = ({"_index": index, "_id": r["place_code"],
                    "_source": build_doc(dict(r), existing_alter_names=preserve.get(r["place_code"]))}
                   for r in chunk if r.get("place_code"))
        ok, errs = helpers.bulk(es, actions, raise_on_error=False, stats_only=False,
                                chunk_size=args.batch, request_timeout=120)
        done += len(chunk)
        if errs:
            errors += len(errs)
        pbar.update(len(chunk))
    pbar.close()
    conn.close()
    print(f"done: indexed≈{done:,}  errors={errors}")
    es.indices.refresh(index=index)


if __name__ == "__main__":
    main()
