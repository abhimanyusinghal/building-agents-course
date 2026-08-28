"""
===============================================================================
 P3  —  GENERATOR-VERIFIER: a quality loop drawn as a cycle in the graph
===============================================================================

    python p3_generator_verifier.py

USE CASE — a customer-facing incident notice. One agent drafts it; a second
agent holds the comms checklist (length, impact stated plainly, a next-update
time with timezone, no root-cause speculation) and accepts or rejects with
feedback. Quality-critical output + checkable criteria = this pattern.

THE LANGGRAPH — the loop is DRAWN, not written: generate -> verify -> a
conditional edge that either closes the cycle back to generate or exits.
The round cap lives in the routing function — a written condition, so a
stubborn pair can never loop forever.

Honest disclosure: the drafter is NOT given the checklist. The verifier owns
it. That split is the realistic one — and it is what makes round 1 fail.
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

from pydantic import BaseModel                               # noqa: E402
from langchain_openai import AzureChatOpenAI                 # noqa: E402
from langchain.agents import create_agent                    # noqa: E402
from langgraph.graph import StateGraph, START, END           # noqa: E402

# One client for the small fast model. Both agents in this file share it.
MODEL = os.environ.get("AZURE_OPENAI_DEPLOYMENT_FAST", "gpt-5.4-nano")
model = AzureChatOpenAI(azure_deployment=MODEL,
                        api_version=os.environ.get("OPENAI_API_VERSION",
                                                   "2025-04-01-preview"))

# The incident the notice must describe.
INCIDENT = ("Payments API returned errors for 18 minutes from 14:02; card "
            "payments in the EU region failed during that window. A fix is "
            "deployed; we are monitoring.")

MAX_ROUNDS = 3


# ---------------------------------------------------------------------------
# THE STATE — the draft, the feedback that travels back, and the counters.
# ---------------------------------------------------------------------------
class Flow(TypedDict):
    incident: str
    draft: str
    feedback: str
    round: int
    accepted: bool


# The verifier answers in a fixed shape: accepted yes/no, plus feedback.
class Verdict(BaseModel):
    accepted: bool
    feedback: str


# ---------------------------------------------------------------------------
# THE TWO AGENTS. Note the split: the generator does NOT get the checklist —
# the verifier owns it. That is realistic, and it is why round 1 fails.
# ---------------------------------------------------------------------------
generator = create_agent(
    model=model, tools=[],
    system_prompt=("You write short customer-facing incident notices. "
                   "Plain language, no internal jargon."))

verifier = create_agent(
    model=model, tools=[],
    system_prompt=("You verify incident notices against the comms checklist: "
                   "(1) under 120 words, (2) customer impact stated plainly, "
                   "(3) a concrete next-update time WITH timezone, "
                   "(4) no speculation about root cause, no blame. "
                   "Reject with one line of concrete feedback if ANY item "
                   "fails."),
    response_format=Verdict)


# ---------------------------------------------------------------------------
# THE TWO NODES.
# ---------------------------------------------------------------------------
def generate(state: Flow):
    n = state["round"] + 1
    if state["feedback"]:
        # A rejected round: give the drafter its previous draft plus ONLY
        # the feedback — revise, don't rewrite from scratch.
        ask = (f"Your previous notice:\n{state['draft']}\n\nReviewer "
               f"feedback:\n{state['feedback']}\n\nApply ONLY this feedback "
               f"and return the full corrected notice.")
    else:
        # Round 1: just the incident.
        ask = f"Write the notice for:\n{state['incident']}"
    result = generator.invoke({"messages": [("user", ask)]})
    count_tokens(result)
    draft = str(result["messages"][-1].content)
    print(f"ROUND {n}   generator: {len(draft.split())} words")
    return {"draft": draft, "round": n}


def verify(state: Flow):
    # Show the verifier the incident and the draft; it applies the checklist.
    ask = f"Incident:\n{state['incident']}\n\nNotice to verify:\n{state['draft']}"
    result = verifier.invoke({"messages": [("user", ask)]})
    count_tokens(result)
    v: Verdict = result["structured_response"]
    print(f"          verifier:  "
          f"{'ACCEPTED' if v.accepted else 'REJECTED — ' + v.feedback[:64]}")
    return {"accepted": v.accepted, "feedback": v.feedback}


# ---------------------------------------------------------------------------
# THE PATTERN IS THIS FUNCTION + ONE conditional edge: the cycle.
# Accepted -> exit. Rejected -> back to generate. And the round cap is a
# WRITTEN condition, right here, so a stubborn pair can never loop forever.
# ---------------------------------------------------------------------------
def route_after_verify(state: Flow):
    if state["accepted"]:
        return "done"
    if state["round"] >= MAX_ROUNDS:
        print(f"          round cap ({MAX_ROUNDS}) — the written condition "
              f"that ends a stubborn loop")
        return "done"
    return "revise"


def build_graph():
    b = StateGraph(Flow)
    b.add_node("generate", generate)
    b.add_node("verify", verify)
    b.add_edge(START, "generate")
    b.add_edge("generate", "verify")
    b.add_conditional_edges("verify", route_after_verify,
                            {"revise": "generate",   # <- the cycle, drawn
                             "done": END})
    return b.compile()


def main():
    print("P3 · generator-verifier — an incident notice through a drawn "
          "quality loop\n")

    # One invoke runs the whole loop: draft, verify, revise, verify, ...
    started = time.time()
    final = build_graph().invoke({"incident": INCIDENT, "draft": "",
                                  "feedback": "", "round": 0,
                                  "accepted": False})
    seconds = round(time.time() - started, 1)

    print("\nNOTICE")
    for line in final["draft"].splitlines()[:6]:
        if line.strip():
            print(f"   {line.strip()[:86]}")
    outcome = (f"accepted-round-{final['round']}" if final["accepted"]
               else "round-cap")
    print("\nNOTE   the drafter never saw the checklist — the verifier owns "
          "it.\n       The feedback travelled through STATE, along a drawn "
          "edge.")
    record("p3-notice", "generator-verifier", USAGE, seconds, outcome=outcome,
           note=f"{final['round']} round(s)")
    print(f"recorded ({outcome}) · {USAGE['input_tokens']} in / "
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
