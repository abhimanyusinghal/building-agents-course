"""
===============================================================================
 ASK  —  RAG inside an agent: the same loop as every agent this week
===============================================================================

    python ask.py "What should tests cover for password reset?"

The agent is assembled from the same four parts as every agent in this course:
a model, its tools, a brief, and the shape of the answer. The ONLY new thing
is what the one tool returns: search results from the knowledge index.

    the loop:   read question -> search_knowledge (as often as it decides)
                -> enough context? -> answer, citing chunk ids

Every search the agent runs is printed AS IT HAPPENS, so the room watches the
agent plan its own retrieval - nobody scripts those queries. The full run is
saved to out/ afterwards, as the record and the rescue.
===============================================================================
"""
import json
import re
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

HERE = Path(__file__).parent
load_dotenv(HERE / ".env")

from pydantic import BaseModel, Field                       # noqa: E402
from langchain_openai import AzureChatOpenAI                # noqa: E402
from langchain.agents import create_agent                   # noqa: E402
from langchain_core.tools import tool                       # noqa: E402

import os                                                    # noqa: E402
import search as searchmod                                   # noqa: E402  <- the hybrid search you just watched

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# =============================================================================
#  THE SHAPE OF THE ANSWER  -  grounding is enforced by the schema
# =============================================================================
class Grounded(BaseModel):
    """The agent cannot hand back free prose. It must return this shape - and
    the sources field is the whole point: every answer names the chunks it
    stands on, which is what makes it checkable afterwards."""
    answer: str = Field(description="The answer, as short numbered points where natural.")
    sources: list[str] = Field(description="The chunk ids the answer stands on. Only ids "
                                           "that came back from search_knowledge.")


# =============================================================================
#  THE ONE TOOL  -  retrieval, wrapped so the model can call it
# =============================================================================
@tool
def search_knowledge(query: str) -> str:
    """Search the engineering knowledge index. Returns the top matching chunks
    with their ids and labels. Call it as often as you need, with different
    queries, until you have enough to answer."""
    # Printed live so the audience sees each search the moment the agent
    # decides to run it. This line is the visible half of "agentic RAG".
    print(f'   -> search_knowledge("{query}")')
    hits, how, _, _ = searchmod.search(query, k=3)
    # What the model receives: id + labels + the chunk text itself. The ids
    # matter - they are what the model must cite back in 'sources'.
    out = []
    for _, score, _, c in hits:
        out.append(f"[{c['id']}] ({c['service']} · {c['doc_type']} · v{c['version']}, score {score:.2f})\n{c['text']}")
    return "\n\n".join(out)


# =============================================================================
#  THE BRIEF  -  search before answering, answer only from what came back
# =============================================================================
SYSTEM = """You answer engineering questions for a QA team.

Call search_knowledge before answering — more than once, with different queries,
when the question has more than one aspect. Answer ONLY from what the searches
return. Every number and rule in your answer must appear in a retrieved chunk,
and every chunk you used goes in sources. If the knowledge does not cover
something, say so rather than filling the gap."""


def main():
    question = sys.argv[1] if len(sys.argv) > 1 else "What should tests cover for password reset?"

    # ---- assemble the agent: model + tools + brief + answer shape.
    #      Identical construction to the judge, the designer and triage -
    #      the loop never changes; only these four inputs do.
    agent = create_agent(
        model=AzureChatOpenAI(
            azure_deployment=os.environ["AZURE_OPENAI_DEPLOYMENT"],
            api_version=os.environ.get("OPENAI_API_VERSION", "2025-04-01-preview"),
        ),
        tools=[search_knowledge],
        system_prompt=SYSTEM,
        response_format=Grounded,
    )

    print(f'question: "{question}"\n')
    print("the agent plans its own retrieval:")
    started = time.time()
    # One invoke runs the WHOLE loop: search(es), judgement, structured answer.
    result = agent.invoke({"messages": [("user", question)]})
    seconds = round(time.time() - started, 1)

    # ---- add up what the run cost, from the usage stamped on each message
    usage = {"input_tokens": 0, "output_tokens": 0}
    for m in result["messages"]:
        u = getattr(m, "usage_metadata", None)
        if u:
            usage["input_tokens"] += u.get("input_tokens", 0)
            usage["output_tokens"] += u.get("output_tokens", 0)

    # ---- the answer, already forced into the Grounded shape by the framework
    out: Grounded = result["structured_response"]
    print(f"\nanswer ({seconds}s):\n")
    for line in out.answer.splitlines():
        print(f"  {line}")
    print(f"\nsources — the chunks the answer stands on:")
    for s in out.sources:
        print(f"  [{s}]")
    cost = usage["input_tokens"] / 1e6 * 2.0 + usage["output_tokens"] / 1e6 * 8.0
    print(f"\n{usage['input_tokens']} in / {usage['output_tokens']} out tokens · ~${cost:.4f}")

    # ---- keep the record: the transcript in out/ is the rescue for a live
    #      session and the evidence afterwards.
    slug = re.sub(r"[^a-z0-9]+", "-", question.lower())[:48].strip("-")
    rec = HERE / "out" / f"ask-{slug}.json"
    rec.write_text(json.dumps({"question": question, "seconds": seconds, "usage": usage,
                               "answer": out.answer, "sources": out.sources}, indent=2),
                   encoding="utf-8")
    print(f"saved to out/{rec.name}")


if __name__ == "__main__":
    main()
