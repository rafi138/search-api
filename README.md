# Search API

Async FastAPI autocomplete/geocoding/search API over Elasticsearch, for Bangladesh places.
Clean, versioned structure (drop in `v2` later), pydantic models + OpenAPI docs, managed
synonyms, and a proper chunked indexer.

## Highlights
- **Async** (`AsyncElasticsearch`) for high concurrency.
- **Default sort = popularity** (Typesense-style) + **admin boost** — single `places` index
  (no separate admin index; admin docs get a popularity uplift).
- **Improved mapping**: `business_name` & `place_name` get a `.complete` sub-field
  (edge-ngram autocomplete + a search analyzer using a **managed synonyms set**).
- **Managed synonyms** via ES `_synonyms` API — upsert/delete + `reload_search_analyzers`
  (no index close/reopen, no reindex).
- **Cleaned schema** — deduped legacy field sprawl.
- **IP/origin allowlist** middleware (opt-in via `ALLOWED_IPS` / `ALLOWED_ORIGINS`).
- v1 under `app/api/v1/`; add `app/api/v2/` later.

## Project layout
```
search-api/
├── app/
│   ├── main.py            # FastAPI app (lifespan, CORS, allowlist, /health)
│   ├── config.py          # pydantic-settings
│   ├── es.py              # async ES client
│   ├── security.py        # CORS + IP allowlist
│   ├── popularity.py      # ranking scheme (single source of truth)
│   ├── ranking.py         # photon-style blend + Python re-rank + admin boost
│   ├── indexing.py         # DB row -> cleaned ES doc (shared by indexers)
│   ├── schema/mapping.py  # analyzers + index mapping
│   ├── queries/           # autocomplete (name-first), search (geocoding), common fn_score
│   ├── models/            # pydantic response models
│   └── api/v1/            # versioned routers (autocomplete, search, places, synonyms)
├── scripts/               # create_index, index_places (chunked), index_single, manage_synonyms
├── requirements.txt
└── .env.example
```

## Setup
```bash
cd /mnt/ssd_disk/search/search-api
python -m venv .venv && source .venv/bin/activate   # or reuse an existing venv
pip install -r requirements.txt
cp .env.example .env       # then edit: ES_PASSWORD, DB_PASSWORD, MONGO_URI, ALLOWED_*
```

## Create index + synonyms + index data
```bash
python scripts/create_index.py              # creates synonym set + 'places' index
python scripts/manage_synonyms.py --preview # preview rules (DB + Mongo)
python scripts/manage_synonyms.py --apply   # push rules + reload analyzers
python scripts/index_places.py              # chunked DB->ES (2.16M docs, ~progress bar)
python scripts/index_single.py <uCode>      # index/refresh one place
```

## Run
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
# OpenAPI docs: http://localhost:8000/docs
```

## API (v1)
| Method | Path | Description |
|---|---|---|
| GET | `/v1/suggest?q=&latitude=&longitude=&bbox=&radius=&limit=` | Suggestions (business_name>place_name>address>area>district). `q` required; rest optional. Returns name+address+types. |
| GET | `/v1/search?q=&latitude=&longitude=&bbox=&radius=&limit=&debug=` | Geocoding search (two-pool + rescore when focused). Returns name+address+types. |
| GET | `/v1/places/{place_code}` | Full document (coords, bounds, everything). |
| GET/PUT/DELETE | `/v1/synonyms[/{set_id}[/rules/{rule_id}]]` | Managed synonym sets (ES `_synonyms`). |
| POST | `/v1/synonyms/{set_id}/reload` | Reload search analyzers (apply synonym changes live). |
| GET | `/health` | Liveness + ES version. |

- `q` is required on suggest/search; `latitude`/`longitude`/`bbox`/`radius`/`limit` are optional.
- `bbox` = `minlon,minlat,maxlon,maxlat` (west,south,east,north); `radius` needs lat/lon (e.g. `5` or `5km`).
- List endpoints return summaries only (no lat/lon). The public id is **`place_code`** (also the ES `_id`), so `/v1/places/{place_code}` is a direct GET.

## Ranking
- **Suggest/search queries**: `function_score` with **exact-name match** (high-boost `term` on lowercased `.raw` of `business_name`/`place_name`/`area`) + field-boosted text + `field_value_factor(popularity)` (encodes Division › … › Road) + an admin nudge. Exact match makes the place whose name *is* the query win over places whose name merely contains it (so "Barishal Division" → the Division, not a POI named "Barishal Division Shilpokola").
- **Focus queries** (`/v1/search` with lat/lon): re-ranked with `blend = 0.50·prox + 0.10·pop + 0.40·text`, per-query relevance gate. `&debug=true` returns `score_debug` (es_terms, rescore, rel_gate).
- Constants in `app/ranking.py` (`POP_BOOST`, `ADMIN_BOOST`, `EXACT_BOOST`).

## Notes
- Indexing reads `places` + `places_bangla` from Postgres (≈2.16M rows); skips poles.
- `_id = uCode` (place_code) — so `/v1/places/{uCode}` is a direct GET.
- The synonym filter references the managed set by id; updates never close the index.
