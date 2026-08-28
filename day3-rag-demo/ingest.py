"""
===============================================================================
 INGEST  —  build the index once, before any question exists
===============================================================================

    knowledge/*.md  ->  parse  ->  chunk  ->  label  ->  embed  ->  index.json

This file is the whole "getting knowledge in" pipeline:

    PARSE   read each markdown file and its three labels (service, type, version)
    CHUNK   cut on MEANING: every '## ' heading starts a new chunk, so a chunk
            is one self-contained fact - a rule, an incident, a decision
    LABEL   attach the labels to every chunk, for filtering at query time
    EMBED   turn each chunk into 3,072 numbers - a point on the meaning-map
    STORE   write vector + text + labels together into index.json

It runs ONCE. Questions never rebuild the index; only changed knowledge does.

    python ingest.py
===============================================================================
"""
import json
import sys
import time
from pathlib import Path

import requests
from dotenv import dotenv_values

# ---------------------------------------------------------------------------
# Configuration comes from .env: the Azure endpoint, the key, and the name of
# the EMBEDDING deployment. Note it is a different model from the chat model -
# small, cheap, and it does exactly one thing: text in, coordinates out.
# ---------------------------------------------------------------------------
HERE = Path(__file__).parent
ENV = dotenv_values(HERE / ".env")
ENDPOINT = ENV["AZURE_OPENAI_ENDPOINT"].rstrip("/")
KEY = ENV.get("AZURE_OPENAI_API_KEY") or ENV.get("AZURE_OPENAI_KEY")
EMBED = ENV.get("AZURE_EMBEDDING_DEPLOYMENT", "text-embedding-3-large")

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# =============================================================================
#  STEP 1 - PARSE: the three labels at the top of every knowledge file
# =============================================================================
def front_matter(text):
    """Every file starts with a tiny header between two '---' lines:

        service: auth
        doc_type: spec
        version: 2.3

    These labels are what stop retrieval drowning in look-alikes later:
    "payment validation" exists in every service and every version - the
    labels are how a query says WHICH one it means."""
    meta = {}
    if text.startswith("---"):
        head, _, body = text[3:].partition("---")
        for line in head.strip().splitlines():
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip()
        return meta, body.strip()
    return meta, text


# =============================================================================
#  STEP 2 - CHUNK: cut where the meaning cuts, never at a character count
# =============================================================================
def chunk(body):
    """One '## ' section = one chunk.

    The test a chunk must pass: handed to you alone - no filename, no
    neighbouring text - could you still act on it? A section heading plus its
    own paragraphs passes that test. Half a class glued to half another file
    does not (one blurry vector), and a bare line like 'maxLength: 4000'
    does not either (whose field? which endpoint?).

    A query never brings back a document. It brings back chunks - so the
    chunk is what the model will eventually read."""
    parts, current = [], []
    for line in body.splitlines():
        if line.startswith("## ") and current:
            parts.append("\n".join(current).strip())   # a section ended: close the chunk
            current = [line]                           # ...and start the next at the heading
        else:
            current.append(line)
    if current:
        parts.append("\n".join(current).strip())
    # The H1 title block names the document; it is not a fact. Drop it.
    return [p for p in parts if p.startswith("## ")]


# =============================================================================
#  STEP 3 - EMBED: every chunk becomes a point on the meaning-map
# =============================================================================
def embed(texts):
    """One call carries ALL the chunks. Back comes one vector per chunk:
    3,072 numbers, best read as coordinates. The only property that matters:
    texts with similar MEANING land near each other - regardless of spelling.

    That is the entire mechanism. There is nothing more inside an embedding
    than 'similar meaning, nearby point'."""
    r = requests.post(
        f"{ENDPOINT}/openai/deployments/{EMBED}/embeddings?api-version=2023-05-15",
        headers={"api-key": KEY}, json={"input": texts}, timeout=60)
    r.raise_for_status()
    data = r.json()
    # The API may answer out of order; 'index' says which vector belongs where.
    vectors = [d["embedding"] for d in sorted(data["data"], key=lambda d: d["index"])]
    tokens = data.get("usage", {}).get("total_tokens", 0)
    return vectors, tokens


# =============================================================================
#  THE PIPELINE, END TO END
# =============================================================================
def main():
    started = time.time()
    files = sorted((HERE / "knowledge").rglob("*.md"))
    print(f"{len(files)} knowledge files\n")

    # ---- parse + chunk + label: every chunk carries its text AND its labels
    chunks = []
    for f in files:
        meta, body = front_matter(f.read_text(encoding="utf-8"))
        sections = chunk(body)
        for sec in sections:
            title = sec.splitlines()[0].lstrip("# ").strip()
            chunks.append({
                "id": f"{f.stem}::{title.lower().replace(' ', '-')[:40]}",
                "text": sec,
                "service": meta.get("service", "-"),
                "doc_type": meta.get("doc_type", "-"),
                "version": meta.get("version", "-"),
                "source": f.name,
            })
        print(f"  {f.name:<28} -> {len(sections)} chunks   [{meta.get('service','-')} · {meta.get('doc_type','-')} · v{meta.get('version','-')}]")

    # ---- show ONE chunk in full: this is the unit search returns and the
    #      unit the model eventually reads. Everything hangs off its quality.
    print(f"\n{len(chunks)} chunks. One of them, in full — the unit everything else works on:\n")
    sample = next(c for c in chunks if "throttling" in c["id"])
    print("  " + "-" * 72)
    for line in sample["text"].splitlines():
        print(f"  {line}")
    print("  " + "-" * 72)
    print(f"  labels: service={sample['service']}  doc_type={sample['doc_type']}"
          f"  version={sample['version']}  source={sample['source']}\n")

    # ---- embed: one API call, all chunks -> one point on the map each
    print(f"embedding {len(chunks)} chunks with {EMBED} ...")
    vectors, tokens = embed([c["text"] for c in chunks])
    for c, v in zip(chunks, vectors):
        c["vector"] = v
    dims = len(vectors[0])
    cost = tokens / 1_000_000 * 0.13          # embedding price: pennies per MILLION tokens
    print(f"  {len(vectors)} vectors x {dims} numbers each · {tokens} tokens · ${cost:.4f}\n")

    # ---- store: vector + text + labels together. That trio IS the index.
    index = {"model": EMBED, "dims": dims, "built": time.strftime("%Y-%m-%d %H:%M"),
             "chunks": chunks}
    out = HERE / "index.json"
    out.write_text(json.dumps(index), encoding="utf-8")
    print(f"written to {out.name} ({out.stat().st_size // 1024} KB) in {time.time()-started:.1f}s")
    print("\nThe index is built. It does not need building again until the knowledge changes.")


if __name__ == "__main__":
    main()
