# day3-rag-demo — RAG, built in front of the room

Fully separate from `day3-build-fixture-v1` (own knowledge, own index, own .env).
No server needed. Three files, three commands, all positive path.

| file | what it is |
|---|---|
| `knowledge/` | 9 hand-written engineering docs: specs, incidents, runbook, ADR, standards |
| `ingest.py` | parse -> chunk (## sections) -> label (front-matter) -> embed -> `index.json` |
| `search.py` | hybrid lookup: meaning + exact symbols + metadata filters |
| `ask.py` | RAG inside an agent: one `search_knowledge` tool, answer cites chunk ids |

## The demo, in order

    python ingest.py
    python search.py "tests for users trying too many login attempts"
    python search.py "payment validation rules" --service checkout --version 4.2
    python search.py "ERR_AUTH_1042"
    python ask.py "What should tests cover for password reset?"

Query embeddings are cached in `query-cache.json`: every query above works even
offline once it has run once. Agent transcripts land in `out/` as the rescue kit.

Embedding model: text-embedding-3-large (3,072 dims). Chat model: from `.env`.
