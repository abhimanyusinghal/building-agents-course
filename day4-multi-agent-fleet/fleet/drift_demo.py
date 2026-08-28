"""
===============================================================================
 DRIFT DEMO  —  the agent that was quietly wrong, caught by its records
===============================================================================

    python fleet/drift_demo.py

One tiny agent, three prompt versions, three runs each — every run recorded
with a VALIDATOR verdict:

    v1  the original brief: summarize in AT MOST 20 words          (passes)
    v2  someone "improved" it to a 2-3 sentence detailed summary    (drifts)
    v3  the fix: the 20-word constraint restored                    (proved)

The point: watch the v2 outputs scroll past and they look FINE — fluent,
helpful, wrong against the contract. Nothing on the screen says so. The
validator column in the run record says so, every single run. That is what
"quietly wrong" means, and why records exist.

v2 -> v3 is also the day's "one proved change": the fix is not an opinion,
it is a pass-rate you can read off the fleet view.
===============================================================================
"""
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).parent))

from langchain_openai import AzureChatOpenAI       # noqa: E402
from langchain.agents import create_agent          # noqa: E402
from record import record                          # noqa: E402  <- the C2 artifact itself

FAST = os.environ.get("AZURE_OPENAI_DEPLOYMENT_FAST", "gpt-5.4-nano")


def agent(system):
    model = AzureChatOpenAI(azure_deployment=FAST,
                            api_version=os.environ.get("OPENAI_API_VERSION",
                                                       "2025-04-01-preview"))
    return create_agent(model=model, tools=[], system_prompt=system)


def run(agent_obj, text):
    t0 = time.time()
    result = agent_obj.invoke({"messages": [("user", text)]})
    secs = round(time.time() - t0, 1)
    usage = {"input_tokens": 0, "output_tokens": 0}
    for m in result["messages"]:
        u = getattr(m, "usage_metadata", None)
        if u:
            usage["input_tokens"] += u.get("input_tokens", 0)
            usage["output_tokens"] += u.get("output_tokens", 0)
    return result["messages"][-1].content, usage, secs


def say(tag, text, indent=0):
    print(f"{'   ' * indent}{tag:<12} {text}")

NOTE = ("Customer called about the delayed delivery. Courier confirmed the "
        "parcel left the depot Tuesday. Customer was offered a voucher and "
        "accepted. Follow-up booked for Friday to confirm arrival.")

BRIEFS = {
    "v1": "Summarize the case note in AT MOST 20 words. Never add facts.",
    "v2": "Write a detailed, helpful 2-3 sentence summary of the case note.",   # the quiet change
    "v3": "Summarize the case note in AT MOST 20 words. Never add facts.",      # the fix
}


def validate(text):
    """The contract, as code: at most 20 words. A validator is what turns
    'looks fine' into pass/fail a record can carry."""
    words = len(str(text).split())
    return words <= 20, words


def main():
    print("drift demo — same agent, three prompt versions, validated runs\n")
    for version, brief in BRIEFS.items():
        a = agent(brief)
        say("VERSION", f"{version}  ({brief[:58]})")
        for i in range(3):
            out, usage, secs = run(a, NOTE)
            ok, words = validate(out)
            verdict = "pass" if ok else "FAIL"
            say("", f"run {i + 1}: {words:>2} words -> {verdict}   "
                    f"\"{' '.join(str(out).split())[:58]}...\"", indent=1)
            record("note-summarizer", "single-agent", FAST, usage, secs,
                   outcome=verdict, prompt_version=version,
                   note=f"{words} words vs cap 20")
        print()
    say("NOTE", "every v2 output read fine on screen. The validator in the")
    say("", "record is the only place the drift is visible — and the fleet")
    say("", "view will read it straight from records.jsonl.")


if __name__ == "__main__":
    main()
