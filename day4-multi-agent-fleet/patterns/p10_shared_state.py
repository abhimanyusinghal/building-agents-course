"""
===============================================================================
 P10  —  SHARED STATE: the blackboard IS the graph state
===============================================================================

    python p10_shared_state.py

USE CASE — an incident hypothesis board. "Customers are intermittently
logged out since 09:10." Three specialists — auth, infra, qa — take turns
at a shared board: each reads EVERYTHING posted so far and either adds one
NEW finding that builds on the board, or passes. The incident commander is
nobody; the board is the coordination.

THE LANGGRAPH — this pattern needs no metaphor here, because LangGraph's
core idea is literally shared state: the board is a state field with an
operator.add reducer, every node reads it and appends to it, and the run
ends by WRITTEN CONDITION — everyone passes in one round (the board has
settled) or the round cap fires. The two rules ARE the two failure modes:
the pass rule kills padding, the cap kills endless loops.
===============================================================================
"""
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Annotated, TypedDict
import operator

from dotenv import load_dotenv

# Load the Azure OpenAI credentials from this fixture's own .env file.
ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from pydantic import BaseModel, Field                        # noqa: E402
from langchain_openai import AzureChatOpenAI                 # noqa: E402
from langchain.agents import create_agent                    # noqa: E402
from langgraph.graph import StateGraph, START, END           # noqa: E402

# One client for the small fast model. Every expert in this file shares it.
MODEL = os.environ.get("AZURE_OPENAI_DEPLOYMENT_FAST", "gpt-5.4-nano")
model = AzureChatOpenAI(azure_deployment=MODEL,
                        api_version=os.environ.get("OPENAI_API_VERSION",
                                                   "2025-04-01-preview"))

# The incident the board must explain.
INCIDENT = ("Customers are intermittently logged out since 09:10 UTC. "
            "Support sees ~40 tickets. A portal deploy went out at 09:05. "
            "Login itself works; sessions drop mid-use.")

MAX_ROUNDS = 3


# ---------------------------------------------------------------------------
# THE STATE. The board field IS the blackboard — an operator.add reducer,
# every node reads it and appends to it. LangGraph's core idea, used as
# the whole pattern.
# ---------------------------------------------------------------------------
class Board(TypedDict):
    incident: str
    board: Annotated[list, operator.add]
    passes_in_row: int
    rounds: int


# Every expert answers in a fixed shape: pass, or one new finding.
class Post(BaseModel):
    passing: bool = Field(description="true if you have nothing NEW")
    finding: str = Field(default="", description="ONE new finding that "
                         "builds on the board, if not passing")


# ---------------------------------------------------------------------------
# THE THREE EXPERTS — same rules, different angle on the incident.
# ---------------------------------------------------------------------------
auth_expert = create_agent(
    model=model, tools=[],
    system_prompt=("You are the auth/session specialist at an incident "
                   "board. Read the incident and the board. Post ONE NEW "
                   "auth/session-angle finding that BUILDS ON what is "
                   "already there — reference a board line if you can. If "
                   "you truly have nothing new, pass. Never repeat the "
                   "board."),
    response_format=Post)

infra_expert = create_agent(
    model=model, tools=[],
    system_prompt=("You are the infrastructure/deploy specialist at an "
                   "incident board. Read the incident and the board. Post "
                   "ONE NEW infrastructure/deploy-angle finding that BUILDS "
                   "ON what is already there — reference a board line if "
                   "you can. If you truly have nothing new, pass. Never "
                   "repeat the board."),
    response_format=Post)

qa_expert = create_agent(
    model=model, tools=[],
    system_prompt=("You are the QA/reproduction specialist at an incident "
                   "board. Read the incident and the board. Post ONE NEW "
                   "QA/reproduction-angle finding that BUILDS ON what is "
                   "already there — reference a board line if you can. If "
                   "you truly have nothing new, pass. Never repeat the "
                   "board."),
    response_format=Post)


# ---------------------------------------------------------------------------
# THE THREE EXPERT NODES — identical shape, written out in full. Each one:
# reads the WHOLE board, then adds ONE new finding, or passes.
# ---------------------------------------------------------------------------
def auth(state: Board):
    # auth opens each round, so it also advances the round counter.
    print(f"\nROUND {state['rounds'] + 1}")
    ask = (f"Incident: {state['incident']}\n\nBoard so far:\n"
           + ("\n".join(state["board"]) or "(empty)"))
    result = auth_expert.invoke({"messages": [("user", ask)]})
    count_tokens(result)
    post: Post = result["structured_response"]
    if post.passing or not post.finding.strip():
        print(f"   [{'auth':<5}] PASS")
        return {"passes_in_row": state["passes_in_row"] + 1,
                "rounds": state["rounds"] + 1}
    text = " ".join(post.finding.split())
    if text.lower().startswith("[auth]"):      # some models echo the tag
        text = text[6:].strip()
    print(f"   [{'auth':<5}] + {text[:74]}")
    return {"board": [f"[auth] {text}"], "passes_in_row": 0,
            "rounds": state["rounds"] + 1}


def infra(state: Board):
    ask = (f"Incident: {state['incident']}\n\nBoard so far:\n"
           + ("\n".join(state["board"]) or "(empty)"))
    result = infra_expert.invoke({"messages": [("user", ask)]})
    count_tokens(result)
    post: Post = result["structured_response"]
    if post.passing or not post.finding.strip():
        print(f"   [{'infra':<5}] PASS")
        return {"passes_in_row": state["passes_in_row"] + 1}
    text = " ".join(post.finding.split())
    if text.lower().startswith("[infra]"):
        text = text[7:].strip()
    print(f"   [{'infra':<5}] + {text[:74]}")
    return {"board": [f"[infra] {text}"], "passes_in_row": 0}


def qa(state: Board):
    ask = (f"Incident: {state['incident']}\n\nBoard so far:\n"
           + ("\n".join(state["board"]) or "(empty)"))
    result = qa_expert.invoke({"messages": [("user", ask)]})
    count_tokens(result)
    post: Post = result["structured_response"]
    if post.passing or not post.finding.strip():
        print(f"   [{'qa':<5}] PASS")
        return {"passes_in_row": state["passes_in_row"] + 1}
    text = " ".join(post.finding.split())
    if text.lower().startswith("[qa]"):
        text = text[4:].strip()
    print(f"   [{'qa':<5}] + {text[:74]}")
    return {"board": [f"[qa] {text}"], "passes_in_row": 0}


# ---------------------------------------------------------------------------
# THE PATTERN: a cycle over shared state + a WRITTEN end condition, twice:
# everyone passed in one round (the board settled), or the round cap.
# ---------------------------------------------------------------------------
def settled_or_next(state: Board):
    if state["passes_in_row"] >= 3:
        print("\nENDED   everyone passed in one round — the board has "
              "SETTLED. That is the\n        written condition; no manager "
              "declared it done.")
        return "end"
    if state["rounds"] >= MAX_ROUNDS:
        print(f"\nENDED   round cap ({MAX_ROUNDS}) — the other written "
              f"condition. Termination is\n        a rule, never a hope.")
        return "end"
    return "again"


def build_graph():
    b = StateGraph(Board)
    b.add_node("auth", auth)
    b.add_node("infra", infra)
    b.add_node("qa", qa)
    # The turn order, drawn: auth -> infra -> qa.
    b.add_edge(START, "auth")
    b.add_edge("auth", "infra")
    b.add_edge("infra", "qa")
    # After qa the round is over: settle, cap, or go again.
    b.add_conditional_edges("qa", settled_or_next,
                            {"again": "auth",    # <- the cycle
                             "end": END})
    return b.compile()


def main():
    print("P10 · shared state — three specialists, one board, no commander")
    print(f"\nINCIDENT  {INCIDENT[:78]}...")

    # One invoke runs the whole board session.
    started = time.time()
    final = build_graph().invoke(
        {"incident": INCIDENT, "board": [], "passes_in_row": 0, "rounds": 0},
        {"recursion_limit": 40})
    seconds = round(time.time() - started, 1)

    print(f"\nTHE BOARD  {len(final['board'])} findings — each written "
          f"against the board its author read:")
    for line in final["board"][:4]:
        print(f"   {line[:82]}")

    # Keep the finished board as an artifact.
    out = ROOT / "out"
    out.mkdir(exist_ok=True)
    (out / "blackboard.json").write_text(
        json.dumps({"incident": INCIDENT, "board": final["board"]},
                   indent=2), encoding="utf-8")
    print("\nNOTE   the board IS the graph state — LangGraph's own name for "
          "this idea.\n       saved to out/blackboard.json")
    record("p10-incidentboard", "shared-state", USAGE, seconds,
           note=f"{len(final['board'])} findings, {final['rounds']} rounds")
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
