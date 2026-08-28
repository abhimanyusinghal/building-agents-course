# Building Agents — course demos

The complete, runnable demo set from the four-day **Building Agents** training:
every agent, graph, pattern and governance tool shown in the sessions, in its
final state. Each day is a self-contained folder with its own README, and the
session slides are in [`slides/`](slides/) as PDFs.

| Day | Folder | What you build / run |
|-----|--------|----------------------|
| 1 — Fundamentals | [`day1-agent-fundamentals/`](day1-agent-fundamentals/) | An agent assembled from its five parts inside a coding assistant (Copilot / Claude Code / Codex): a story-review agent with standards, an MCP tool server, and instructions. Labs included. |
| 2 — Processes | [`day2-story-pipeline/`](day2-story-pipeline/) | A LangGraph pipeline around one judgement agent: fetch → guard → rules gate → judge → **human approval gate (interrupt)** → post. Real GitHub Issues, real mail, a run ledger. |
| 3 — Testing | [`day3-test-pipeline/`](day3-test-pipeline/) | Agents write and triage tests for a real API: design (grounded in the OpenAPI contract) → run (machinery) → triage → audit. The line between agent and machinery, drawn in code. |
| 3 — RAG | [`day3-rag-demo/`](day3-rag-demo/) | Retrieval built from parts: chunking on semantic boundaries, embeddings, hybrid search, and RAG inside an agent that cites its sources. |
| 4 — Ecosystem | [`day4-multi-agent-fleet/`](day4-multi-agent-fleet/) | Eleven multi-agent coordination patterns, one self-contained LangGraph file each — plus governance: a linted agent inventory, run records, drift detection, a fleet view, and OpenTelemetry tracing into Phoenix/Grafana. |

## Setup (once)

1. **Python 3.11+** (the course ran on 3.13) and, optionally for Day 4's
   OpenTelemetry beat, **Docker**.

2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. **Azure OpenAI** — you need one Azure OpenAI resource with:
   - a **chat deployment** (any capable model; the course used `gpt-5.4`),
   - a **small/fast chat deployment** for Day 4's pattern demos (the course
     used `gpt-5.4-nano` — the patterns are the star, not the prose),
   - an **embedding deployment** for the RAG demo (`text-embedding-3-large`).

   The code never hard-codes model names — everything comes from `.env`.

4. **Per-folder `.env`** — every folder that calls a model has a
   `.env.example`. Copy it to `.env` in the same folder and fill in the
   values. **`.env` files are git-ignored; never commit them.**

5. Day 2 additionally needs a **GitHub repository you own** (the pipeline's
   work tracker) and a fine-grained PAT — and, optionally, a mailbox for the
   human-approval mail. Day 2's README walks through all of it; mail is
   optional, chapters 1–2 run without it.

## Verified versions

Everything in this repo was verified end-to-end on:
`langgraph 1.2.11 · langchain 1.3.17 · langchain-openai 1.x · Python 3.13`
(OTel extras: `arize-phoenix 20.4 · openinference-instrumentation-langchain 0.1.73`).

## Cost expectations

All demos run on small inputs. A full pass over every Day 4 pattern demo costs
well under **one US cent** on a nano-class deployment; the whole course's live
runs totalled roughly **$0.20**. Each folder's ledger/records show real numbers
— reading them is part of the course.

## Three ideas the code keeps repeating

1. **A rule you can write down is never sent to a model.** Routing, caps,
   completion checks and validators live in code; judgement lives in briefs.
2. **Ground every agent in real material** — contracts, knowledge files,
   canned evidence — and let structure (Pydantic shapes) carry the answers.
3. **A run that leaves no record did not happen.** Every demo writes a ledger
   line; Day 4's fleet view and OTel tracing are built on top of them.

## Repo hygiene

`.gitignore` excludes `.env`, token caches, checkpoints and `__pycache__`.
`.gitattributes` pins LF line endings (chapter diffs and cross-platform
checkouts depend on it).
