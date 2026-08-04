"""End-to-end endpoint evaluation harness.

Tests /v1/suggest and /v1/search with and without a focus point (lat/lon),
comparing results against expectations defined in a CSV file.

Usage:
    python scripts/eval_endpoints.py                    # default localhost:8101
    python scripts/eval_endpoints.py --host localhost --port 8101 --key YOUR_KEY
    python scripts/eval_endpoints.py --csv eval_queries.csv --suggest-only
    python scripts/eval_endpoints.py --csv eval_queries.csv --search-only

CSV format (header row required):
    SL,q,latitude,longitude,params_to_check,explanation

    - q:               search text
    - latitude/longitude: focus point (empty = test without geo)
    - params_to_check:  comma-separated expectations, each is key=value. Supports:
                        place_code=XXXX      → that place_code must be in top N
                        place_code_in_top5=XX → must be in first 5 results
                        min_results=N        → at least N results returned
                        has_area=Mirpur       → at least one result has area=Mirpur
                        has_type=Bank         → at least one result has type=Bank
                        place_detail_check=place_code:field=value
    - explanation:      human-readable note

The script tests BOTH /v1/suggest and /v1/search for each row (unless --suggest-only
or --search-only). If lat/lon are present, it also tests with the focus point.
Results are printed as a table and summary.

Requires: httpx (pip install httpx)
"""
import argparse
import csv
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

try:
    import httpx
except ImportError:
    print("ERROR: pip install httpx")
    sys.exit(1)

try:
    from tqdm import tqdm
except ImportError:
    tqdm = None

# ── ANSI colors ─────────────────────────────────────────────────────────────
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


def fetch(client, base, endpoint, q, lat=None, lon=None, key=None):
    """Hit an endpoint, return (places_list, error)."""
    params = {"q": q, "limit": "10"}
    if lat is not None and lon is not None:
        params["latitude"] = lat
        params["longitude"] = lon
    url = f"{base}/v1/{endpoint}?{urlencode(params)}"
    headers = {"x-api-key": key} if key else {}
    try:
        r = client.get(url, headers=headers, timeout=30)
        if r.status_code != 200:
            return [], f"HTTP {r.status_code}: {r.text[:100]}"
        return r.json().get("places", []), None
    except Exception as e:
        return [], str(e)


def fetch_detail(client, base, place_code, key=None):
    """Get full place details by place_code."""
    url = f"{base}/v1/places/{place_code}"
    headers = {"x-api-key": key} if key else {}
    try:
        r = client.get(url, headers=headers, timeout=15)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return {}


def check_condition(condition, places, client, base, key):
    """Evaluate a single condition string. Returns (bool, message)."""
    condition = condition.strip()
    if not condition:
        return True, ""

    codes = [p.get("place_code") or "" for p in places]

    if condition.startswith("min_results="):
        n = int(condition.split("=", 1)[1])
        ok = len(places) >= n
        return ok, f"{len(places)}/{n}"

    if condition.startswith("place_code_in_top5="):
        pc = condition.split("=", 1)[1].strip()
        top5 = codes[:5]
        ok = pc in top5
        pos = top5.index(pc) + 1 if ok else "-"
        return ok, f"rank #{pos}" if ok else f"not in top 5 ({codes[:3]})"

    if condition.startswith("place_code="):
        pc = condition.split("=", 1)[1].strip()
        ok = pc in codes
        pos = codes.index(pc) + 1 if ok else "-"
        return ok, f"rank #{pos}" if ok else f"missing ({codes[:3]})"

    if condition.startswith("has_area="):
        val = condition.split("=", 1)[1].strip().lower()
        ok = any((p.get("area") or "").lower() == val for p in places)
        return ok, f"area={val} found" if ok else f"area={val} not found"

    if condition.startswith("has_type="):
        val = condition.split("=", 1)[1].strip()
        ok = any(p.get("type") == val for p in places)
        return ok, f"type={val} found" if ok else f"type={val} not found"

    if condition.startswith("place_detail_check="):
        # format: place_detail_check=PLACE_CODE:field=value
        rest = condition.split("=", 1)[1]
        parts = rest.split(":")
        if len(parts) != 2:
            return False, "malformed"
        pc, fieldval = parts[0], parts[1]
        field, expected = fieldval.split("=", 1)
        detail = fetch_detail(client, base, pc, key)
        actual = str(detail.get(field, ""))
        ok = expected.strip().lower() in actual.lower()
        return ok, f"{field}={actual!r}" if ok else f"{field}={actual!r} (expected {expected})"

    return False, f"unknown condition: {condition}"


def run_tests(csv_path, base, key, suggest=True, search=True):
    rows = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)

    total = pass_count = 0
    results = []
    row_pass = [0] * len(rows)  # for progress bar

    # build a flat list of (row_idx, endpoint, geo_variant) for tqdm
    test_items = []
    for ri, row in enumerate(rows):
        if not row.get("q", "").strip():
            continue
        endpoints = []
        if suggest:
            endpoints.append("suggest")
        if search:
            endpoints.append("search")
        lat = row.get("latitude", "").strip() or None
        lon = row.get("longitude", "").strip() or None
        geo_variants = [(None, None, "(no geo)")]
        if lat and lon:
            geo_variants.append((lat, lon, f"({lat},{lon})"))
        for ep in endpoints:
            for glat, glon, glabel in geo_variants:
                test_items.append((ri, row, ep, glat, glon, glabel))

    iterator = tqdm(test_items, desc="Testing", unit="test") if tqdm else test_items

    with httpx.Client() as client:
        for ri, row, endpoint, glat, glon, glabel in iterator:
            sl = row.get("SL", "").strip()
            q = row.get("q", "").strip()
            conditions_raw = row.get("params_to_check", "").strip()
            explanation = row.get("explanation", "").strip()
            conditions = [c.strip() for c in conditions_raw.split(",") if c.strip()]

            # fetch with or without geo
            if glat:
                places, err = fetch(client, base, endpoint, q, lat=glat, lon=glon, key=key)
            else:
                places, err = fetch(client, base, endpoint, q, key=key)

            test_id = f"#{sl} {endpoint} {glabel}"

            if err:
                total += 1
                results.append((test_id, RED + "ERROR" + RESET, err, q, explanation))
                continue

            all_ok = True
            messages = []
            for cond in conditions:
                ok, msg = check_condition(cond, places, client, base, key)
                if not ok:
                    all_ok = False
                messages.append(f"{cond}: {msg}")

            total += 1
            if all_ok:
                pass_count += 1
                status = GREEN + "PASS" + RESET
            else:
                status = RED + "FAIL" + RESET

            name_summary = ", ".join(
                (p.get("name") or "?")[:20] for p in places[:3])
            detail = f"{' | '.join(messages)} | top: [{name_summary}]"
            results.append((test_id, status, detail, q, explanation))

    # ── Print results ──────────────────────────────────────────────────────
    print(f"\n{'='*100}")
    print(f"{BOLD}Endpoint Evaluation: {Path(csv_path).name}{RESET}")
    print(f"Base: {base} | {pass_count}/{total} passed ({pass_count*100//max(total,1)}%)")
    print(f"{'='*100}\n")

    for test_id, status, detail, q, explanation in results:
        print(f"  {status:20} {test_id}")
        print(f"  {'':22} q={q!r}")
        if explanation:
            print(f"  {'':22} note: {explanation}")
        print(f"  {'':22} {detail}")
        print()

    failed = [r for r in results if RED in r[1]]
    print(f"{'='*100}")
    print(f"{GREEN}PASSED: {pass_count}{RESET}  {RED}FAILED: {len(failed)}{RESET}  TOTAL: {total}")
    if failed:
        print(f"\n{RED}Failures:{RESET}")
        for test_id, _, detail, q, _ in failed:
            print(f"  {test_id}: q={q!r}")
            print(f"    {detail}")
    return pass_count, total


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Test suggest/search endpoints against expectations")
    ap.add_argument("--csv", default="scripts/eval_queries.csv", help="CSV file with test cases")
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--port", default="8101", type=int)
    ap.add_argument("--key", default=None, help="x-api-key value")
    ap.add_argument("--suggest-only", action="store_true")
    ap.add_argument("--search-only", action="store_true")
    args = ap.parse_args()

    base = f"http://{args.host}:{args.port}"
    suggest = not args.search_only
    search = not args.suggest_only

    csv_path = args.csv
    if not Path(csv_path).exists():
        print(f"CSV not found: {csv_path}")
        sys.exit(1)

    start = time.time()
    passed, total = run_tests(csv_path, base, args.key, suggest=suggest, search=search)
    elapsed = time.time() - start
    print(f"\nCompleted in {elapsed:.1f}s")
    sys.exit(0 if passed == total else 1)
