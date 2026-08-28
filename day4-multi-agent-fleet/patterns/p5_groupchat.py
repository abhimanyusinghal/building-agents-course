"""
===============================================================================
 P5  —  GROUP CHAT: a moderator node the graph keeps returning to
===============================================================================

    python p5_groupchat.py

USE CASE — a ship/no-ship call. Friday's release carries a known auth bug.
Dev, QA and PM each hold real, conflicting stakes; a moderator runs the
meeting: it picks WHO speaks next (whoever can add something new) and ends
the meeting when a decision WITH its condition is on the table.

THE LANGGRAPH — a cycle with a deciding node at its centre. Every speaker's
edge leads BACK to the moderator; the moderator's conditional edge picks
the next speaker or END. The transcript lives in state; the turn cap is a
written condition in the routing function — a meeting of models does not
run out of breath on its own.
===============================================================================
"""
import json
import os
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

# One client for the small fast model. Every agent in this file shares it.
MODEL = os.environ.get("AZURE_OPENAI_DEPLOYMENT_FAST", "gpt-5.4-nano")
model = AzureChatOpenAI(azure_deployment=MODEL,
                        api_version=os.environ.get("OPENAI_API_VERSION",
                                                   "2025-04-01-preview"))

# The question the meeting must settle.
QUESTION = ("Do we ship Friday's portal release? It fixes the invoice-export "
            "bug many customers want, but QA found the password-reset flow "
            "returns a success page even when the reset mail fails to send.")

MAX_TURNS = 5


# ---------------------------------------------------------------------------
# THE STATE — the transcript everyone reads, and the meeting's counters.
# ---------------------------------------------------------------------------
class Chat(TypedDict):
    question: str
    transcript: Annotated[list, operator.add]
    turns: int
    next_speaker: str
    decision: str


# The moderator answers in a fixed shape: who speaks next, or done + closing.
class Pick(BaseModel):
    next: Literal["dev", "qa", "pm", "done"]
    why: str = Field(description="one short clause")
    closing: str = Field(default="", description="if done: restate the full "
                         "decision WITH its condition, in one sentence")


# ---------------------------------------------------------------------------
# THE FOUR AGENTS — a deciding moderator, and three speakers with real,
# conflicting stakes.
# ---------------------------------------------------------------------------
moderator = create_agent(
    model=model, tools=[],
    system_prompt=("You moderate a release meeting. Read the transcript. "
                   "Pick the next speaker: whoever can ADD something new — "
                   "never someone who would only repeat the transcript. dev "
                   "knows effort and mitigations, qa knows risk, pm owns "
                   "the call and should speak once the sides are on the "
                   "table. THE MOMENT the pm has stated a decision with "
                   "its condition, you MUST answer done."),
    response_format=Pick)

# Each speaker gets a ROLE, its own KNOWLEDGE, and what it is ACCOUNTABLE
# for — never an opinion or a move. The positions (and the debate) emerge
# from the stakes, the same way grounding worked on days 2 and 3.
dev_agent = create_agent(
    model=model, tools=[],
    system_prompt=("You are the dev lead in a release meeting. Your "
                   "context: this release carries the invoice-export fix "
                   "your team committed this sprint. On the password-reset "
                   "bug, the root cause is a missing error path — a proper "
                   "fix is about a day of work plus regression tests; "
                   "hiding the reset entry point behind the existing "
                   "feature flag is about an hour. You answer for the "
                   "release date. Speak from this knowledge. 2 lines max."))

qa_agent = create_agent(
    model=model, tools=[],
    system_prompt=("You are the QA lead in a release meeting. Your "
                   "context: your team found the password-reset flow shows "
                   "a success page even when the reset mail fails to send; "
                   "it reproduces on every mail failure; the portal sees "
                   "roughly 200 reset attempts a day, and silent failures "
                   "surface as 'I never got the mail' support tickets. You "
                   "answer for escaped defects. Speak from this knowledge. "
                   "2 lines max."))

pm_agent = create_agent(
    model=model, tools=[],
    system_prompt=("You are the product manager in a release meeting; the "
                   "ship/no-ship call is yours, and so is the "
                   "accountability for it. Your context: the invoice-export "
                   "bug this release fixes has 40+ open customer "
                   "complaints and one enterprise renewal waiting on it; "
                   "after last quarter's incident the stated quality bar "
                   "is 'no known customer-facing silent failures'. Make "
                   "the call, with its condition. 2 lines max."))


# ---------------------------------------------------------------------------
# THE MODERATOR NODE — reads the whole transcript, picks who speaks next,
# or declares the meeting done with a closing decision.
# ---------------------------------------------------------------------------
def run_moderator(state: Chat):
    ask = (f"Question: {state['question']}\n\nTranscript so far:\n"
           + ("\n".join(state["transcript"]) or "(empty)"))
    result = moderator.invoke({"messages": [("user", ask)]})
    count_tokens(result)
    pick: Pick = result["structured_response"]

    # THE HOUSE RULE, written down (day 2's lesson): the pm speaks LAST —
    # no decision and no closing until dev AND qa have been heard. A real
    # meeting has this rule on paper; so does this graph. The moderator
    # still owns the order, the "who adds", and the closing.
    heard = {line.split(":")[0] for line in state["transcript"]}
    if pick.next in ("pm", "done") and not {"dev", "qa"} <= heard:
        must_hear = "qa" if "qa" not in heard else "dev"
        print(f"\nMODERATOR  wants {pick.next} — HOUSE RULE: the pm speaks "
              f"last,\n           every voice first. turn "
              f"{state['turns'] + 1}: {must_hear} speaks")
        return {"next_speaker": must_hear}

    # And the rule's second half: the pm speaks LAST — so once the pm has
    # spoken, the call is made and the meeting closes. Debate after the
    # decision is repetition by design.
    if "pm" in heard and pick.next != "done":
        print(f"\nMODERATOR  wants {pick.next} — HOUSE RULE: the call is "
              f"made; the meeting closes")
        pm_lines = [l for l in state["transcript"] if l.startswith("pm:")]
        closing = pm_lines[-1][4:] if pm_lines else ""
        print(f"MODERATOR  done — {closing[:70]}")
        return {"next_speaker": "done", "decision": closing}

    if pick.next == "done":
        closing = pick.closing.strip()
        if len(closing) < 25:
            # Lazy closing from the model: fall back to the decision
            # exactly as the pm stated it in the transcript.
            pm_lines = [l for l in state["transcript"] if l.startswith("pm:")]
            if pm_lines:
                closing = pm_lines[-1][4:]
        print(f"\nMODERATOR  done — {closing[:70]}")
        return {"next_speaker": "done", "decision": closing}
    print(f"\nMODERATOR  turn {state['turns'] + 1}: {pick.next} speaks "
          f"({pick.why[:48]})")
    return {"next_speaker": pick.next}


# ---------------------------------------------------------------------------
# THE THREE SPEAKER NODES — identical shape, written out in full. Each
# reads the whole transcript, speaks once, appends to the transcript.
# ---------------------------------------------------------------------------
def dev(state: Chat):
    ask = (f"Question: {state['question']}\n\nTranscript so far:\n"
           + ("\n".join(state["transcript"]) or "(empty)"))
    result = dev_agent.invoke({"messages": [("user", ask)]})
    count_tokens(result)
    text = " ".join(str(result["messages"][-1].content).split())
    print(f"   {'DEV':<4} {text[:82]}")
    if len(text) > 82:
        print(f"        {text[82:164]}")
    return {"transcript": [f"dev: {text}"], "turns": state["turns"] + 1}


def qa(state: Chat):
    ask = (f"Question: {state['question']}\n\nTranscript so far:\n"
           + ("\n".join(state["transcript"]) or "(empty)"))
    result = qa_agent.invoke({"messages": [("user", ask)]})
    count_tokens(result)
    text = " ".join(str(result["messages"][-1].content).split())
    print(f"   {'QA':<4} {text[:82]}")
    if len(text) > 82:
        print(f"        {text[82:164]}")
    return {"transcript": [f"qa: {text}"], "turns": state["turns"] + 1}


def pm(state: Chat):
    ask = (f"Question: {state['question']}\n\nTranscript so far:\n"
           + ("\n".join(state["transcript"]) or "(empty)"))
    result = pm_agent.invoke({"messages": [("user", ask)]})
    count_tokens(result)
    text = " ".join(str(result["messages"][-1].content).split())
    print(f"   {'PM':<4} {text[:82]}")
    if len(text) > 82:
        print(f"        {text[82:164]}")
    return {"transcript": [f"pm: {text}"], "turns": state["turns"] + 1}


# ---------------------------------------------------------------------------
# THE PATTERN: two routing rules make the meeting.
# ---------------------------------------------------------------------------
def route_moderator(state: Chat):
    """The moderator's pick becomes the edge — or the meeting ends."""
    return "done" if state["next_speaker"] == "done" else state["next_speaker"]


def back_or_cap(state: Chat):
    """Every voice returns to the moderator — unless the written turn cap
    has been reached. A meeting of models does not end on its own."""
    if state["turns"] >= MAX_TURNS:
        print(f"\nTURN CAP   {MAX_TURNS} turns — the written condition ends "
              f"the meeting")
        return "cap"
    return "moderator"


def build_graph():
    b = StateGraph(Chat)
    b.add_node("moderator", run_moderator)
    b.add_node("dev", dev)
    b.add_node("qa", qa)
    b.add_node("pm", pm)
    # Every speaker returns to the moderator — or hits the cap.
    b.add_conditional_edges("dev", back_or_cap,
                            {"moderator": "moderator", "cap": END})
    b.add_conditional_edges("qa", back_or_cap,
                            {"moderator": "moderator", "cap": END})
    b.add_conditional_edges("pm", back_or_cap,
                            {"moderator": "moderator", "cap": END})
    b.add_edge(START, "moderator")
    # The moderator's pick becomes the edge.
    b.add_conditional_edges("moderator", route_moderator,
                            {"dev": "dev", "qa": "qa", "pm": "pm",
                             "done": END})
    return b.compile()


def main():
    print("P5 · group chat — a moderated cycle with a turn cap\n")
    print(f"QUESTION   {QUESTION[:82]}...")

    # One invoke runs the whole meeting.
    started = time.time()
    final = build_graph().invoke(
        {"question": QUESTION, "transcript": [], "turns": 0,
         "next_speaker": "", "decision": ""},
        {"recursion_limit": 30})
    seconds = round(time.time() - started, 1)

    ended = "decision" if final["decision"] else "turn-cap"
    print(f"\nNOTE       every edge leads back to the moderator — the shape "
          f"IS the meeting.\n           ended by: {ended} · "
          f"{final['turns']} speaker turns")
    record("p5-releasechat", "group-chat", USAGE, seconds, outcome=ended,
           note=f"{final['turns']} turns")
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
