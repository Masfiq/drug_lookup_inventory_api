"""Measure what the search cache saves, end to end over HTTP.

Start the API first (python -m app.cli run), then:
    python scripts/measure_cache.py

For each popular search it times the first request (a cache MISS, which runs
the database query) and then 20 repeats (cache HITs, answered from memory).
Restart the API before running so the cache starts empty.
"""

from __future__ import annotations

import argparse
import statistics
import time

import httpx2

QUERIES = ["ibuprofen", "acetaminophen", "lisinopril", "metformin", "atorvastatin",
           "amoxicillin", "insulin", "omeprazole", "lipitor", "tylenol"]  # fmt: skip


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    parser.add_argument("--repeats", type=int, default=20)
    args = parser.parse_args()

    misses: list[float] = []
    hits: list[float] = []
    with httpx2.Client(base_url=args.base_url, timeout=30) as client:
        client.get("/health").raise_for_status()  # warm the connection
        for q in QUERIES:
            start = time.perf_counter()
            response = client.get("/drugs/search", params={"q": q})
            elapsed = (time.perf_counter() - start) * 1000
            if response.headers.get("X-Cache") != "MISS":
                raise SystemExit(f"'{q}' was already cached. Restart the API and run again.")
            misses.append(elapsed)
            for _ in range(args.repeats):
                start = time.perf_counter()
                response = client.get("/drugs/search", params={"q": q})
                hits.append((time.perf_counter() - start) * 1000)
                assert response.headers.get("X-Cache") == "HIT"

    miss, hit = statistics.median(misses), statistics.median(hits)
    print(f"queries: {len(QUERIES)}, repeats each: {args.repeats}")
    print(f"median MISS (database): {miss:.1f} ms")
    print(f"median HIT  (memory):   {hit:.1f} ms")
    print(f"speedup: {miss / hit:.1f}x")


if __name__ == "__main__":
    main()
