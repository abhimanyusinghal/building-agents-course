"""
===============================================================================
 P4  —  HANDOFF: the agent's answer IS the edge (langgraph Command)
===============================================================================

    python p4_handoff.py

USE CASE — a support front desk. It reads the ticket, then hands the WHOLE
conversation to the right specialist desk — auth, billing, or outage — and
is out of the loop. Control moves; it is not delegated-and-returned.

THE LANGGRAPH — the front desk node returns Command(goto=...): the model's
structured answer becomes the graph's routing, directly. Compare day 2's
router: there a plain function read the state and picked the edge. Here the
DECIDING AGENT picks the edge. Notice build_graph draws NO edge out of
front_desk — the edge does not exist until the model answers.
===============================================================================
"""
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Literal, TypedDict

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
from langgraph.types import Command                          # noqa: E402

# One client for the small fast model. Every agent in this file shares it.
MODEL = os.environ.get("AZURE_OPENAI_DEPLOYMENT_FAST", "gpt-5.4-nano")
model = AzureChatOpenAI(azure_deployment=MODEL,
                        api_version=os.environ.get("OPENAI_API_VERSION",
                                                   "2025-04-01-preview"))

# The ticket to route — our week's own scenario.
TICKET = ("Customer says the password reset e-mail never arrives, and when "
          "they retry they see error ERR_AUTH_1042 on screen.")


# ---------------------------------------------------------------------------
# THE STATE — the ticket, the handoff note, and the specialist's resolution.
# ---------------------------------------------------------------------------
class Flow(TypedDict):
    ticket: str
    handoff_note: str
    resolution: str


# The front desk answers in a fixed shape: which desk, and a one-line note.
class Route(BaseModel):
    target: Literal["auth", "billing", "outage"]
    note: str = Field(description="one-line handoff note for the specialist")


# ---------------------------------------------------------------------------
# THE FOUR AGENTS — the deciding front desk, and three specialist desks.
# ---------------------------------------------------------------------------
front = create_agent(
    model=model, tools=[],
    system_prompt=("You are the support front desk. Decide which desk owns "
                   "this ticket: auth (sign-in, passwords, tokens), billing "
                   "(charges, invoices), outage (many customers, service "
                   "down). Write a one-line handoff note."),
    response_format=Route)

auth_desk = create_agent(
    model=model, tools=[],
    system_prompt=("Auth desk. Resolve the ticket: likely cause and next "
                   "action for the customer, 2 lines max."))

billing_desk = create_agent(
    model=model, tools=[],
    system_prompt=("Billing desk. Resolve the ticket: likely cause and "
                   "next action, 2 lines max."))

outage_desk = create_agent(
    model=model, tools=[],
    system_prompt=("Outage desk. Resolve the ticket: scope check and next "
                   "action, 2 lines max."))


# ---------------------------------------------------------------------------
# THE PATTERN IS THIS NODE'S RETURN VALUE: Command(goto=<the model's choice>).
# The model's structured answer becomes the edge, at runtime.
# ---------------------------------------------------------------------------
def front_desk(state: Flow) -> Command[Literal["auth", "billing", "outage"]]:
    result = front.invoke({"messages": [("user", state["ticket"])]})
    count_tokens(result)
    route: Route = result["structured_response"]
    print(f"FRONT DESK   handoff -> {route.target.upper()}   ({route.note})")
    return Command(goto=route.target,             # the answer IS the edge
                   update={"handoff_note": route.note})


# ---------------------------------------------------------------------------
# THE THREE DESK NODES — identical shape, written out in full. Each gets
# the ticket plus the handoff note, resolves, and the run ends there.
# ---------------------------------------------------------------------------
def auth(state: Flow):
    ask = f"Ticket: {state['ticket']}\nHandoff note: {state['handoff_note']}"
    result = auth_desk.invoke({"messages": [("user", ask)]})
    count_tokens(result)
    text = str(result["messages"][-1].content)
    print(f"{'AUTH':<12} now owns the ticket. The front desk is "
          f"out of the loop.")
    for line in text.splitlines()[:2]:
        if line.strip():
            print(f"   {line.strip()[:84]}")
    return {"resolution": text}


def billing(state: Flow):
    ask = f"Ticket: {state['ticket']}\nHandoff note: {state['handoff_note']}"
    result = billing_desk.invoke({"messages": [("user", ask)]})
    count_tokens(result)
    text = str(result["messages"][-1].content)
    print(f"{'BILLING':<12} now owns the ticket. The front desk is "
          f"out of the loop.")
    for line in text.splitlines()[:2]:
        if line.strip():
            print(f"   {line.strip()[:84]}")
    return {"resolution": text}


def outage(state: Flow):
    ask = f"Ticket: {state['ticket']}\nHandoff note: {state['handoff_note']}"
    result = outage_desk.invoke({"messages": [("user", ask)]})
    count_tokens(result)
    text = str(result["messages"][-1].content)
    print(f"{'OUTAGE':<12} now owns the ticket. The front desk is "
          f"out of the loop.")
    for line in text.splitlines()[:2]:
        if line.strip():
            print(f"   {line.strip()[:84]}")
    return {"resolution": text}


def build_graph():
    b = StateGraph(Flow)
    b.add_node("front_desk", front_desk)
    b.add_node("auth", auth)
    b.add_node("billing", billing)
    b.add_node("outage", outage)
    b.add_edge(START, "front_desk")
    b.add_edge("auth", END)
    b.add_edge("billing", END)
    b.add_edge("outage", END)
    # No edge out of front_desk is drawn here: Command(goto=...) creates it
    # at runtime, from the model's structured answer.
    return b.compile()


def main():
    print("P4 · handoff — the front desk's answer becomes the graph's edge\n")
    print(f"TICKET       {TICKET}\n")

    # One invoke: the front desk decides, control MOVES to that desk.
    started = time.time()
    build_graph().invoke({"ticket": TICKET, "handoff_note": "",
                          "resolution": ""})
    seconds = round(time.time() - started, 1)

    print("\nNOTE         the transfer and its reason are in the state — "
          "auditable later.")
    record("p4-frontdesk", "handoff", USAGE, seconds, note="Command(goto=...)")
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
