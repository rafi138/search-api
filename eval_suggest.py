"""Eval /v1/suggest ranking across admin levels + a POI, with and without a focus.

For each subtype, pick one prominent doc of that subtype, query its name, and show
the top-3 results (a) without focus and (b) focused at the target doc's location.
Run:  python eval_suggest.py
"""
import sys, os
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from elasticsearch import Elasticsearch
from app.config import get_settings
from app.queries.suggest import build_suggestion_query

SUBTYPES = ["Division", "District", "City", "Sub District", "Thana", "Union",
            "Area", "Subarea", "Supersubarea", "Road"]
DHAKA = (23.8103, 90.4124)


def doc_name(s):
    return (s.get("business_name") or s.get("place_name") or s.get("area")
            or (s.get("new_address") or "").split(",")[0].strip() or "?")


def show(label, hits, target_id):
    print(f"   {label}:")
    for i, h in enumerate(hits, 1):
        s = h["_source"]
        mark = "  <== TARGET" if h["_id"] == target_id else ""
        print(f"      {i}. {s.get('pType')}/{s.get('subType')} pop={s.get('popularity_ranking')} "
              f"{doc_name(s)[:28]}{mark}")
    top = hits[0]["_id"] if hits else None
    print(f"      => #1 {'is TARGET' if top == target_id else ('(target not #1)' if target_id else '')}")


def main():
    s = get_settings()
    es = Elasticsearch(hosts=[s.ES_HOST], basic_auth=(s.ES_USER, s.ES_PASSWORD),
                       verify_certs=s.ES_VERIFY_CERTS, ca_certs=s.ES_CA_CERTS or None)
    idx = s.INDEX_NAME

    for st in SUBTYPES + ["__POI__"]:
        # pick one example doc
        if st == "__POI__":
            ex = es.search(index=idx, body={"size": 1, "query": {"term": {"pType": "Bank"}},
                                            "sort": [{"popularity_ranking": "desc"}]})["hits"]["hits"]
        else:
            ex = es.search(index=idx, body={"size": 1, "query": {"bool": {"filter": [
                {"term": {"pType": "Admin"}}, {"term": {"subType": st}}]}},
                "sort": [{"popularity_ranking": "desc"}]})["hits"]["hits"]
        if not ex:
            print(f"\n### {st}: no example doc found"); continue
        d = ex[0]["_source"]; tid = ex[0]["_id"]
        q = (d.get("place_name") or d.get("area") or doc_name(d)).split(",")[0].strip()
        gl = d.get("geo_location") or {}
        lat = gl.get("lat") if isinstance(gl, dict) else None
        lon = gl.get("lon") if isinstance(gl, dict) else None
        print(f"\n### {st}  q={q!r}  target={tid} ({d.get('district')}) pop={d.get('popularity_ranking')}")

        nof = es.search(index=idx, body=build_suggestion_query(q, limit=3))["hits"]["hits"]
        show("no focus", nof, tid)

        if lat is not None and lon is not None:
            wf = es.search(index=idx, body=build_suggestion_query(q, limit=3, lat=lat, lon=lon))["hits"]["hits"]
            show(f"focus @ target ({lat:.4f},{lon:.4f})", wf, tid)
        else:
            print("   focus @ target: (no geo on target doc)")


if __name__ == "__main__":
    main()
