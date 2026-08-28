"""
===============================================================================
 SEARCH  —  hybrid lookup over the index: meaning + exact symbols + labels
===============================================================================

    python search.py "tests for users trying too many login attempts"
    python search.py "payment validation rules" --service checkout --version 4.2
    python search.py "ERR_AUTH_1042"

Three kinds of looking, and each wins somewhere:

    SEMANTIC   the query is embedded and joins the chunks on the meaning-map;
               nearest neighbours win. Wins on PARAPHRASE - "too many login
               attempts" finds "throttled after five failures" with barely a
               shared word.
    SYMBOL     an exact identifier (ERR_AUTH_1042, INC-2214) found verbatim in
               a chunk is marked and boosted. Wins on IDENTIFIERS - for an
               error code, "similar meaning" is precisely what nobody wants.
    METADATA   --service / --doc-type / --version narrow the field BEFORE any
               ranking happens. Wins by SCOPING - version 3.1 never competes.

One query runs all three at once; results merge, then rank. Nothing in this
file reasons - it is arithmetic, milliseconds, fractions of a cent.
===============================================================================
"""
import argparse
import json
import math
import re
import sys
import time
from pathlib import Path

import requests
from dotenv import dotenv_values

HERE = Path(__file__).parent
ENV = dotenv_values(HERE / ".env")
ENDPOINT = ENV["AZURE_OPENAI_ENDPOINT"].rstrip("/")
KEY = ENV.get("AZURE_OPENAI_API_KEY") or ENV.get("AZURE_OPENAI_KEY")
EMBED = ENV.get("AZURE_EMBEDDING_DEPLOYMENT", "text-embedding-3-large")
CACHE = HERE / "query-cache.json"

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# =============================================================================
#  THE QUERY TAKES THE SAME TRIP AS EVERY CHUNK
# =============================================================================
def embed_query(text):
    """Chunks were embedded once, at indexing. The query is embedded NOW, with
    the same model - so it lands on the same map, and 'nearby' means the same
    thing. Every query this file has ever embedded is cached on disk, which is
    why a rehearsed demo still works with the network down."""
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    if text in cache:
        return cache[text], "cached"
    r = requests.post(
        f"{ENDPOINT}/openai/deployments/{EMBED}/embeddings?api-version=2023-05-15",
        headers={"api-key": KEY}, json={"input": [text]}, timeout=30)
    r.raise_for_status()
    v = r.json()["data"][0]["embedding"]
    cache[text] = v
    CACHE.write_text(json.dumps(cache), encoding="utf-8")
    return v, "embedded live"


def cosine(a, b):
    """Similarity = how close two points sit on the meaning-map.

    Mechanically it is the angle between two vectors; all you need on stage:
    higher = closer in meaning. Same direction = 1.0, unrelated drifts toward
    zero. Our top hits land around 0.4-0.6 - what matters is the RANKING."""
    dot = sum(x * y for x, y in zip(a, b))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


def symbols_in(query):
    """Exact identifiers: ERR_AUTH_1042, INC-2214, ADR-007.

    The pattern says 'CAPITALS joined by _ or -', which is what engineering
    identifiers look like. For these, a conceptually-related match is a WRONG
    match - a related error code is a different error - so they are handled
    by exact string containment, not by the map."""
    return re.findall(r"[A-Z][A-Z0-9]*[_-][A-Z0-9_-]+", query)


# =============================================================================
#  THE HYBRID SEARCH ITSELF: scope -> rank by meaning -> boost exact symbols
# =============================================================================
def search(query, k=3, service=None, doc_type=None, version=None):
    index = json.loads((HERE / "index.json").read_text(encoding="utf-8"))
    pool = index["chunks"]

    # ---- 1. METADATA first: filter the field BEFORE ranking. The labels from
    #         ingest earn their keep here - out-of-scope chunks never compete.
    scoped = [c for c in pool
              if (not service or c["service"] == service)
              and (not doc_type or c["doc_type"] == doc_type)
              and (not version or c["version"] == version)]

    # ---- 2. SEMANTIC: embed the query, measure similarity to every chunk.
    qv, how = embed_query(query)
    syms = symbols_in(query)
    ranked = []
    for c in scoped:
        score = cosine(qv, c["vector"])
        # ---- 3. SYMBOL: an exact identifier present verbatim in the chunk
        #         gets a flat boost - exact beats approximate, by design.
        exact = any(s in c["text"] for s in syms)
        ranked.append((score + (0.5 if exact else 0.0), score, exact, c))
    ranked.sort(key=lambda t: -t[0])
    return ranked[:k], how, len(pool), len(scoped)


def main():
    ap = argparse.ArgumentParser(description="Hybrid search over the knowledge index.")
    ap.add_argument("query")
    ap.add_argument("-k", type=int, default=3)
    ap.add_argument("--service")
    ap.add_argument("--doc-type")
    ap.add_argument("--version")
    args = ap.parse_args()

    started = time.time()
    hits, how, total, scoped = search(args.query, args.k, args.service, args.doc_type, args.version)
    ms = (time.time() - started) * 1000

    # The scope line is worth reading aloud: "2 of 17 chunks in scope" means
    # the filter ran before the ranking - the rest never competed.
    scope_note = f"{scoped} of {total} chunks in scope" if scoped != total else f"{total} chunks"
    print(f'query: "{args.query}"   ({how} · {scope_note} · {ms:.0f} ms)\n')
    for rank, (boosted, score, exact, c) in enumerate(hits, 1):
        tag = "  EXACT SYMBOL MATCH" if exact else ""
        head = c["text"].splitlines()[0].lstrip("# ")
        print(f"  {rank}.  {score:.3f}  {c['id']}{tag}")
        print(f"       [{c['service']} · {c['doc_type']} · v{c['version']}]  {head}")
        body = " ".join(c["text"].splitlines()[1:]).strip()
        print(f"       {body[:96]}...")
        print()


if __name__ == "__main__":
    main()
