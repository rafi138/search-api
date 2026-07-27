"""Index (or refresh) a single place by uCode/place_code.

Usage:
    python scripts/index_single.py <place_code>
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import psycopg2
from psycopg2.extras import RealDictCursor
from elasticsearch import Elasticsearch, NotFoundError

from app.config import get_settings
from app.indexing import build_doc

SQL = """
    SELECT p.*,
           ST_AsText(ST_SimplifyPreserveTopology(p.bounds, 0.0001)) AS bounds_geom,
           pb.address AS address_bn, pb.area AS area_bn, pb.city AS city_bn
    FROM places p
    LEFT JOIN places_bangla pb ON p.place_code = pb.place_code
    WHERE p.place_code = %s
    LIMIT 1
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("place_code")
    ap.add_argument("--index", default=None)
    args = ap.parse_args()

    s = get_settings()
    index = args.index or s.INDEX_NAME
    es = Elasticsearch(hosts=[s.ES_HOST], basic_auth=(s.ES_USER, s.ES_PASSWORD),
                       verify_certs=s.ES_VERIFY_CERTS, ca_certs=s.ES_CA_CERTS or None)

    conn = psycopg2.connect(host=s.DB_HOST, port=s.DB_PORT, user=s.DB_USER,
                            password=s.DB_PASSWORD, dbname=s.DB_NAME)
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(SQL, (args.place_code,))
    row = cur.fetchone()
    conn.close()
    if not row:
        print(f"place_code {args.place_code!r} not found in DB."); sys.exit(1)

    # preserve alter_names already in ES (they're authored via the API, not the DB)
    existing_alter = None
    try:
        cur_doc = es.get(index=index, id=args.place_code)
        existing_alter = cur_doc["_source"].get("alter_names")
    except NotFoundError:
        existing_alter = None

    doc = build_doc(dict(row), existing_alter_names=existing_alter)
    res = es.index(index=index, id=args.place_code, document=doc)
    print(f"{res['result']}: {args.place_code} -> {doc.get('new_address')}"
          + (f" (kept {len(existing_alter)} alias(es))" if existing_alter else ""))


if __name__ == "__main__":
    main()
