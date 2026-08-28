"""
===============================================================================
 P2  —  CONCURRENT: parallel branches in one LangGraph superstep
===============================================================================

    python p2_concurrent.py

USE CASE — one pull-request diff, three independent review lenses: security,
performance, style. None needs the others' output, so making them wait in
line would be pure waste. This is the shape that wants parallel branches.

THE LANGGRAPH — three edges LEAVING the same point. LangGraph runs nodes
that become ready in the same superstep IN PARALLEL, and the reducer
(operator.add on the reviews field) merges their writes — no thread pool,
no locks: the graph owns the concurrency. The join is free too: "digest"
has three incoming edges, so it runs once, after all three finish.
===============================================================================
"""
import json
import operator
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Annotated, TypedDict

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

# The pull-request diff all three lenses will review. It hides real problems:
# string-built SQL, a token logged, a pointless loop.
DIFF = '''--- a/portal/auth/reset.py
+++ b/portal/auth/reset.py
@@ def request_reset(email):
-    user = db.find_user(email)
+    user = db.query(f"SELECT * FROM users WHERE email = '{email}'")
     token = make_token(user.id)
-    log.info("reset requested")
+    log.info(f"reset requested for {email} token={token}")
+    for attempt in range(len(RESET_LOG)):
+        if RESET_LOG[attempt].email == email:
+            history.append(RESET_LOG[attempt])
     send_mail(email, RESET_URL + token)'''


# ---------------------------------------------------------------------------
# THE STATE. The reviews field has a REDUCER: when parallel branches write
# to it, LangGraph MERGES the lists instead of letting one write clobber
# another. Any field written by parallel branches needs one.
# ---------------------------------------------------------------------------
class Review(TypedDict):
    diff: str
    reviews: Annotated[list, operator.add]


# ---------------------------------------------------------------------------
# THE THREE LENSES — one agent each, same diff, different brief.
# ---------------------------------------------------------------------------
security_reviewer = create_agent(
    model=model, tools=[],
    system_prompt=("Review ONLY for security problems (injection, secrets "
                   "in logs). Max 2 findings, one line each: "
                   "SEVERITY - finding."))

perf_reviewer = create_agent(
    model=model, tools=[],
    system_prompt=("Review ONLY for performance problems (needless work, "
                   "bad loops). Max 2 findings, one line each: "
                   "SEVERITY - finding."))

style_reviewer = create_agent(
    model=model, tools=[],
    system_prompt=("Review ONLY for readability/style problems. Max 2 "
                   "findings, one line each: SEVERITY - finding."))


# ---------------------------------------------------------------------------
# THE THREE NODES — identical shape, written out in full. Each runs its
# reviewer on the diff and APPENDS one entry to the shared reviews list.
# Each entry carries its own token counts: parallel branches must not share
# a counter, so the numbers travel through the state and are added up later.
# ---------------------------------------------------------------------------
def security(state: Review):
    started = time.time()
    result = security_reviewer.invoke({"messages": [("user", state["diff"])]})
    secs = round(time.time() - started, 1)
    tokens_in = tokens_out = 0
    for m in result["messages"]:
        u = getattr(m, "usage_metadata", None)
        if u:
            tokens_in += u.get("input_tokens", 0)
            tokens_out += u.get("output_tokens", 0)
    print(f"  DONE   {'security':<9} in {secs}s")
    return {"reviews": [{"lens": "security",
                         "text": str(result["messages"][-1].content),
                         "secs": secs, "input_tokens": tokens_in,
                         "output_tokens": tokens_out}]}


def perf(state: Review):
    started = time.time()
    result = perf_reviewer.invoke({"messages": [("user", state["diff"])]})
    secs = round(time.time() - started, 1)
    tokens_in = tokens_out = 0
    for m in result["messages"]:
        u = getattr(m, "usage_metadata", None)
        if u:
            tokens_in += u.get("input_tokens", 0)
            tokens_out += u.get("output_tokens", 0)
    print(f"  DONE   {'perf':<9} in {secs}s")
    return {"reviews": [{"lens": "perf",
                         "text": str(result["messages"][-1].content),
                         "secs": secs, "input_tokens": tokens_in,
                         "output_tokens": tokens_out}]}


def style(state: Review):
    started = time.time()
    result = style_reviewer.invoke({"messages": [("user", state["diff"])]})
    secs = round(time.time() - started, 1)
    tokens_in = tokens_out = 0
    for m in result["messages"]:
        u = getattr(m, "usage_metadata", None)
        if u:
            tokens_in += u.get("input_tokens", 0)
            tokens_out += u.get("output_tokens", 0)
    print(f"  DONE   {'style':<9} in {secs}s")
    return {"reviews": [{"lens": "style",
                         "text": str(result["messages"][-1].content),
                         "secs": secs, "input_tokens": tokens_in,
                         "output_tokens": tokens_out}]}


def digest(state: Review):
    # THE JOIN. This node has three incoming edges, so LangGraph runs it
    # once, after ALL three lenses have finished. No model here — just
    # printing the first finding from each lens.
    print("\nDIGEST  all three lenses are in:")
    for r in sorted(state["reviews"], key=lambda r: r["lens"]):
        first = next((l for l in r["text"].splitlines() if l.strip()), "")
        print(f"   [{r['lens']:<8}] {first.strip()[:74]}")
    return {}


def build_graph():
    b = StateGraph(Review)
    b.add_node("security", security)
    b.add_node("perf", perf)
    b.add_node("style", style)
    b.add_node("digest", digest)

    # ---- THE PATTERN: three edges out of START, drawn at build time. ------
    b.add_edge(START, "security")
    b.add_edge(START, "perf")
    b.add_edge(START, "style")
    # Three edges INTO digest = the join, for free.
    b.add_edge("security", "digest")
    b.add_edge("perf", "digest")
    b.add_edge("style", "digest")
    b.add_edge("digest", END)
    # -----------------------------------------------------------------------
    return b.compile()


def main():
    print("P2 · concurrent — one diff, three lenses, one superstep\n")

    # One invoke. LangGraph sees three nodes become ready at once and runs
    # them in parallel; the wall clock below proves it.
    started = time.time()
    final = build_graph().invoke({"diff": DIFF, "reviews": []})
    wall = round(time.time() - started, 1)

    # Add up what the branches spent (their numbers travelled in the state).
    agent_time = round(sum(r["secs"] for r in final["reviews"]), 1)
    usage = {"input_tokens": sum(r["input_tokens"] for r in final["reviews"]),
             "output_tokens": sum(r["output_tokens"] for r in final["reviews"])}
    print(f"\nTHE CLOCK  {agent_time}s of agent time inside {wall}s of wall "
          f"clock —\n           LangGraph ran the ready nodes in parallel; "
          f"the reducer merged the writes.")
    record("p2-review", "concurrent", usage, wall, note="3 lenses, 1 superstep")
    print(f"recorded · {usage['input_tokens']} in / "
          f"{usage['output_tokens']} out · {wall}s")


# ---------------------------------------------------------------------------
# Bookkeeping — nothing below is part of the pattern.
# ---------------------------------------------------------------------------
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
