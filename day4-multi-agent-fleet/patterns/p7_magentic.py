"""
===============================================================================
 P7  —  MAGENTIC: a manager node the graph keeps returning to, with a ledger
===============================================================================

    python p7_magentic.py

USE CASE — an open-ended bug investigation. BUG-3411: some customers on the
annual upgrade get charged twice, ~3 tickets a day. Nobody can write the
step sequence down in advance — which specialist to consult next depends on
what the last one found. That open-endedness is what Magentic is FOR.

THE LANGGRAPH — a supervisor cycle. The manager keeps a LEDGER (facts so
far + plan) in the graph state, picks the next specialist, reads what came
back, updates the ledger, re-plans. The EDGES are fixed — every specialist
returns to the manager — but the PATH through them is the model's, chosen
step by step from evidence. Two things stay machinery, on day 2's rule
that anything you can write down is never sent to a model: COMPLETION
("a fix plan exists" ends the run, in the routing function) and the step
cap (LangGraph's own recursion_limit).

Honest disclosure: the fix-planner refuses to plan until the ledger holds
BOTH log evidence and code evidence. A manager that jumps to the fix too
early gets caught and must re-plan — that discipline is written in a brief,
and it is realistic: your best engineers refuse to fix what they have not
seen.
===============================================================================
"""
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Annotated, Literal, TypedDict
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
from langgraph.errors import GraphRecursionError             # noqa: E402

# One client for the small fast model. Every agent in this file shares it.
MODEL = os.environ.get("AZURE_OPENAI_DEPLOYMENT_FAST", "gpt-5.4-nano")
model = AzureChatOpenAI(azure_deployment=MODEL,
                        api_version=os.environ.get("OPENAI_API_VERSION",
                                                   "2025-04-01-preview"))

# The goal — deliberately open-ended.
GOAL = ("BUG-3411: customers upgrading to the annual plan are sometimes "
        "charged twice (~3 tickets/day, e.g. ORD-58112). Find the likely "
        "cause and produce a fix plan with a test that proves it.")

# The evidence the specialists can actually look at (canned, like a fixture).
LOGS = """14:31:02 charge.request  cart=c-99231 amount=8900 req=r-771
14:31:10 WARN gateway timeout after 8000ms  req=r-771
14:31:12 charge.request  cart=c-99231 amount=8900 req=r-802   <- same cart
14:31:13 charge.created  provider_id=ch_1a  req=r-771         <- both landed
14:31:14 charge.created  provider_id=ch_1b  req=r-802"""

CODE = '''@retry(times=3, backoff_seconds=10)
def charge(cart):
    payload = {"cart_id": cart.id, "amount": cart.total}
    return post(PROVIDER + "/charge", json=payload, timeout=8)
    # note: no idempotency key in the payload'''


# ---------------------------------------------------------------------------
# THE STATE — the manager's ledger lives HERE, in the graph state.
# ---------------------------------------------------------------------------
class Flow(TypedDict):
    goal: str
    ledger: str                              # the manager's living memory
    instruction: str
    next: str
    evidence: Annotated[list, operator.add]
    fix_plan: str


# The manager answers in a fixed shape: updated ledger, next step,
# one-line instruction for that specialist.
class Decision(BaseModel):
    ledger: str = Field(description="FACTS so far + PLAN, max 5 short lines")
    next: Literal["read_logs", "read_code", "propose_fix", "finish"]
    instruction: str = Field(description="one line for that specialist")


# ---------------------------------------------------------------------------
# THE FOUR AGENTS — a deciding manager and three specialists.
# ---------------------------------------------------------------------------
manager = create_agent(
    model=model, tools=[],
    system_prompt=("You manage a bug investigation. Keep a ledger: FACTS "
                   "(from evidence only — never invent) and PLAN. Each turn "
                   "pick ONE next step: read_logs (what happened), "
                   "read_code (why), propose_fix (needs evidence), finish "
                   "(only when a fix plan exists). Re-plan from what comes "
                   "back; do not repeat a step you already took. The ONLY "
                   "evidence in this case is one log excerpt and one code "
                   "snippet — there are no webhooks or other systems to "
                   "check. The moment FACTS explain the double charge, go "
                   "to propose_fix."),
    response_format=Decision)

log_reader = create_agent(
    model=model, tools=[],
    system_prompt=("Read the log excerpt and answer the instruction. Report "
                   "ONLY what the lines show, max 3 lines."))

code_reader = create_agent(
    model=model, tools=[],
    system_prompt=("Read the code and answer the instruction. Report what "
                   "it does and the risk you see, max 3 lines."))

fix_planner = create_agent(
    model=model, tools=[],
    system_prompt=("You write fix plans. IF the material contains BOTH log "
                   "evidence and code evidence, answer with exactly three "
                   "lines — 'CAUSE: ...', 'FIX: ...' (minimal), "
                   "'TEST: ...' (proves it). IF EITHER is missing, answer "
                   "exactly 'INSUFFICIENT: <what is missing>' and nothing "
                   "else."))


# ---------------------------------------------------------------------------
# THE MANAGER NODE — reads goal + ledger + fresh evidence, updates the
# ledger, picks ONE next step. This runs again after every specialist.
# ---------------------------------------------------------------------------
def run_manager(state: Flow):
    # Tell the manager which steps it already took (evidence carries tags).
    taken = [e.split("]")[0].strip("[") for e in state["evidence"]]
    ask = (f"Goal: {state['goal']}\n\nLedger:\n"
           f"{state['ledger'] or '(first turn)'}\n\nSteps already taken: "
           f"{', '.join(taken) or 'none'}\n\nNew evidence:\n"
           + ("\n".join(state["evidence"][-2:]) or "(none yet)"))
    result = manager.invoke({"messages": [("user", ask)]})
    count_tokens(result)
    d: Decision = result["structured_response"]
    head = " ".join(l.strip() for l in d.ledger.splitlines() if l.strip())
    print(f"\nMANAGER  ledger: {head[:64] or '(empty)'}")
    print(f"         next -> {d.next}   ({d.instruction[:56]})")
    SNAP.update({"ledger": d.ledger, "next": d.next})
    return {"ledger": d.ledger, "next": d.next,
            "instruction": d.instruction}


# ---------------------------------------------------------------------------
# THE THREE SPECIALIST NODES — same shape, written out in full. Each gets
# the manager's instruction plus its own material, reports back as evidence.
# ---------------------------------------------------------------------------
def read_logs(state: Flow):
    ask = f"Instruction: {state['instruction']}\n\nMaterial:\n{LOGS}"
    result = log_reader.invoke({"messages": [("user", ask)]})
    count_tokens(result)
    text = " ".join(str(result["messages"][-1].content).split())
    print(f"   {'READ_LOGS':<11} {text[:70]}")
    SNAP.setdefault("evidence", []).append(f"[read_logs] {text}")
    return {"evidence": [f"[read_logs] {text}"]}


def read_code(state: Flow):
    ask = f"Instruction: {state['instruction']}\n\nMaterial:\n{CODE}"
    result = code_reader.invoke({"messages": [("user", ask)]})
    count_tokens(result)
    text = " ".join(str(result["messages"][-1].content).split())
    print(f"   {'READ_CODE':<11} {text[:70]}")
    SNAP.setdefault("evidence", []).append(f"[read_code] {text}")
    return {"evidence": [f"[read_code] {text}"]}


def propose_fix(state: Flow):
    # This specialist gets EVERYTHING gathered so far as its material —
    # and by its brief it refuses unless both kinds of evidence are there.
    material = "\n".join(state["evidence"])
    ask = f"Instruction: {state['instruction']}\n\nMaterial:\n{material}"
    result = fix_planner.invoke({"messages": [("user", ask)]})
    count_tokens(result)
    text = " ".join(str(result["messages"][-1].content).split())
    print(f"   {'PROPOSE_FIX':<11} {text[:70]}")
    SNAP.setdefault("evidence", []).append(f"[propose_fix] {text}")
    update = {"evidence": [f"[propose_fix] {text}"]}
    if not text.startswith("INSUFFICIENT"):
        update["fix_plan"] = text
        SNAP["fix_plan"] = text
    return update


# ---------------------------------------------------------------------------
# THE PATTERN: fixed edges, model-chosen path — and a WRITTEN finish.
# ---------------------------------------------------------------------------
def route_manager(state: Flow):
    return state["next"]


def fix_or_back(state: Flow):
    # Day 2's lesson, again: "a fix plan exists" is a rule you can write
    # down — so completion is machinery's call, not the model's.
    if state["fix_plan"]:
        print("\nROUTE    a fix plan exists — the written rule ends the run")
        return "done"
    return "back"                  # INSUFFICIENT -> manager must re-plan


def build_graph():
    b = StateGraph(Flow)
    b.add_node("manager", run_manager)
    b.add_node("read_logs", read_logs)
    b.add_node("read_code", read_code)
    b.add_node("propose_fix", propose_fix)
    # Evidence returns to the manager — every step leads back.
    b.add_edge("read_logs", "manager")
    b.add_edge("read_code", "manager")
    # ...except a successful fix plan, which the WRITTEN rule sends to END.
    b.add_conditional_edges("propose_fix", fix_or_back,
                            {"done": END, "back": "manager"})
    b.add_edge(START, "manager")
    # The manager's pick becomes the edge.
    b.add_conditional_edges("manager", route_manager,
                            {"read_logs": "read_logs",
                             "read_code": "read_code",
                             "propose_fix": "propose_fix",
                             "finish": END})
    return b.compile()


def main():
    print("P7 · magentic — a supervisor cycle with a ledger in the state\n")
    print(f"GOAL   {GOAL[:80]}...")
    started = time.time()
    state = {"goal": GOAL, "ledger": "", "instruction": "", "next": "",
             "evidence": [], "fix_plan": ""}
    try:
        # The step cap is langgraph's own: recursion_limit counts SUPERSTEPS.
        final = build_graph().invoke(state, {"recursion_limit": 40})
        capped = False
    except GraphRecursionError:
        print("\nSTEP CAP  recursion_limit hit — the platform's own "
              "off-switch, same lesson as every cap today")
        final, capped = {**state, **SNAP}, True
    seconds = round(time.time() - started, 1)

    # Print the fix plan as three labelled lines.
    if final.get("fix_plan"):
        print("\nFIX PLAN")
        parts = [p.strip() for p in
                 re.split(r"(?=CAUSE:|FIX:|TEST:)", final["fix_plan"])
                 if p.strip()]
        for p in parts[-3:]:
            print(f"   {p[:84]}")
    outcome = "step-cap" if capped else "fix-plan"
    print("\nNOTE   the PATH was the model's, chosen step by step from "
          "evidence. Completion\n       and the cap were WRITTEN rules — "
          "judgement to the model, rules to the graph.")
    record("p7-bugmanager", "magentic", USAGE, seconds, outcome=outcome,
           note=f"{len(final['evidence'])} steps")
    print(f"recorded ({outcome}) · {USAGE['input_tokens']} in / "
          f"{USAGE['output_tokens']} out · {seconds}s")


# ---------------------------------------------------------------------------
# Bookkeeping — nothing below is part of the pattern.
# ---------------------------------------------------------------------------
USAGE = {"input_tokens": 0, "output_tokens": 0}
SNAP = {}      # mirror of the state, so a capped run still shows its work


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
