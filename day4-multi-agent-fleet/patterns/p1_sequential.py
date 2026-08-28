"""
===============================================================================
 P1  —  SEQUENTIAL: a pipeline of agents, wired as a LangGraph chain
===============================================================================

    python p1_sequential.py

USE CASE — support-mail intake. A raw customer e-mail becomes, in order:
a structured case record, then a drafted reply, then a reviewed reply.
Each step NEEDS the previous step's output — the shape that wants a
sequential graph and nothing fancier.

THE LANGGRAPH — three nodes, plain edges. The state is the conveyor belt:
every node reads one field and writes the next. The whole pattern is four
add_edge lines — the same StateGraph you built on days 2 and 3.
===============================================================================
"""
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import TypedDict

from dotenv import load_dotenv

# Load the Azure OpenAI credentials from this fixture's own .env file.
ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from langchain_openai import AzureChatOpenAI                 # noqa: E402
from langchain.agents import create_agent                    # noqa: E402
from langgraph.graph import StateGraph, START, END           # noqa: E402

# One client for the small fast model. Every agent in this file shares it.
MODEL = os.environ.get("AZURE_OPENAI_DEPLOYMENT_FAST", "gpt-5.4-nano")
model = AzureChatOpenAI(azure_deployment=MODEL,
                        api_version=os.environ.get("OPENAI_API_VERSION",
                                                   "2025-04-01-preview"))

# The raw customer e-mail that will travel down the pipeline.
EMAIL = ("Subject: charged twice?!  Hi, I bought the annual plan yesterday "
         "and my bank app shows two identical charges of EUR 89. Order said "
         "ORD-58112. Please fix this quickly, I need the invoice for "
         "expenses. - K. Tanaka")


# ---------------------------------------------------------------------------
# THE STATE — one field per stage. Each node's output is the next's input.
# ---------------------------------------------------------------------------
class Flow(TypedDict):
    email: str
    case: str
    draft: str
    reviewed: str


# ---------------------------------------------------------------------------
# THE THREE AGENTS — one per stage, each with its own small brief.
# ---------------------------------------------------------------------------
extractor = create_agent(
    model=model, tools=[],
    system_prompt=("Turn the customer e-mail into a structured case record: "
                   "customer, order id, issue (one line), severity "
                   "(low/med/high), asks (list). Terse key: value lines only."))

drafter = create_agent(
    model=model, tools=[],
    system_prompt=("Draft a short, warm support reply for the case record "
                   "given: acknowledge, say what happens next, no promises "
                   "about refund timing. Max 60 words."))

reviewer = create_agent(
    model=model, tools=[],
    system_prompt=("Review the draft reply. Fix anything wrong, keep the "
                   "tone, return ONLY the final reply text."))


# ---------------------------------------------------------------------------
# THE THREE NODES — the same three moves each time, written out in full:
# read one state field, run one agent on it, write the next state field.
# The coordination lives in the EDGES below, never in these functions.
# ---------------------------------------------------------------------------
def extract(state: Flow):
    # Read the raw e-mail, ask the extractor for a structured case record.
    result = extractor.invoke({"messages": [("user", state["email"])]})
    count_tokens(result)
    case = str(result["messages"][-1].content)
    print(f"NODE  {'extract':<8} reads 'email'  ->  writes 'case': "
          f"{' '.join(case.split())[:58]}")
    return {"case": case}


def draft(state: Flow):
    # Read the case record the previous node wrote, draft a reply from it.
    result = drafter.invoke({"messages": [("user", state["case"])]})
    count_tokens(result)
    text = str(result["messages"][-1].content)
    print(f"NODE  {'draft':<8} reads 'case'  ->  writes 'draft': "
          f"{' '.join(text.split())[:58]}")
    return {"draft": text}


def review(state: Flow):
    # Read the draft, return the final reviewed reply.
    result = reviewer.invoke({"messages": [("user", state["draft"])]})
    count_tokens(result)
    text = str(result["messages"][-1].content)
    print(f"NODE  {'review':<8} reads 'draft'  ->  writes 'reviewed': "
          f"{' '.join(text.split())[:58]}")
    return {"reviewed": text}


def build_graph():
    b = StateGraph(Flow)
    b.add_node("extract", extract)
    b.add_node("draft", draft)
    b.add_node("review", review)

    # ---- THE PATTERN IS THESE FOUR LINES: plain edges, always-next. -------
    b.add_edge(START, "extract")
    b.add_edge("extract", "draft")
    b.add_edge("draft", "review")
    b.add_edge("review", END)
    # -----------------------------------------------------------------------
    return b.compile()


def main():
    print("P1 · sequential — a support mail through a three-node chain\n")
    print(f"INPUT  {EMAIL[:80]}...\n")

    # One invoke runs the whole chain: extract, then draft, then review.
    started = time.time()
    final = build_graph().invoke({"email": EMAIL})
    seconds = round(time.time() - started, 1)

    print("\nREPLY")
    for line in final["reviewed"].splitlines()[:4]:
        if line.strip():
            print(f"   {line.strip()[:86]}")
    print("\nNOTE  zero coordination decisions at runtime — the order was "
          "fixed\n      when the edges were drawn, before any model ran.")
    record("p1-intake", "sequential", USAGE, seconds, note="3-node chain")
    print(f"recorded · {USAGE['input_tokens']} in / "
          f"{USAGE['output_tokens']} out · {seconds}s")


# ---------------------------------------------------------------------------
# Bookkeeping — nothing below is part of the pattern.
# ---------------------------------------------------------------------------
USAGE = {"input_tokens": 0, "output_tokens": 0}


def count_tokens(result):
    """Add this call's token usage to the running total for the run record."""
    for m in result["messages"]:
        u = getattr(m, "usage_metadata", None)
        if u:
            USAGE["input_tokens"] += u.get("input_tokens", 0)
            USAGE["output_tokens"] += u.get("output_tokens", 0)


def record(agent_name, pattern, usage, seconds, outcome="ok", note=""):
    """One JSON line per run to fleet/records.jsonl — same shape as
    fleet/record.py, inlined so this demo stays one self-contained file."""
    pin, pout = {"gpt-5.4": (2.00, 8.00)}.get(MODEL, (0.05, 0.40))
    rec = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"),
           "run_id": uuid.uuid4().hex[:8], "agent": agent_name,
           "pattern": pattern, "prompt_version": "v1", "model": MODEL,
           "input_tokens": usage["input_tokens"],
           "output_tokens": usage["output_tokens"],
           "cost_usd": round(usage["input_tokens"] / 1e6 * pin
                             + usage["output_tokens"] / 1e6 * pout, 6),
           "seconds": seconds, "outcome": outcome, "note": note}
    with (ROOT / "fleet" / "records.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


if __name__ == "__main__":
    main()
