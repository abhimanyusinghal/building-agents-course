"""
===============================================================================
 THE LEDGER  —  the pipeline keeping a record of itself
===============================================================================

WHAT THIS FILE IS, IN ONE SENTENCE
    Every time any step runs, one line is written to a spreadsheet: what ran,
    how long it took, what it consumed, and what that cost in real money.

WHY IT EXISTS
    Because at the end of the day somebody asks "so what does this actually
    cost?" - and there are only two possible answers. One is an estimate with
    a shrug attached. The other is a number the process computed about itself
    while you watched.

    This file is how we get the second answer.

WHAT IT MAKES POSSIBLE, BEYOND THE BILL
    The same record is the evidence needed to move a process from "suggests
    things" to "does things on its own". You do not decide to trust a process;
    you run out of reasons not to - and the reasons come from here.

    Worth saying out loud: the evidence machine is not extra work you do
    afterwards. It ran all session, one line at a time.

THE HONEST BIT
    Machinery steps are recorded too, and they all say 0.0000. That is not
    padding. Showing the free steps beside the paid ones is exactly what makes
    the shape of the cost visible: nearly everything is free, and the one step
    that thinks is the one step you pay for.
===============================================================================
"""
import csv
import os
import time
from pathlib import Path

# The record itself: an ordinary spreadsheet file, sitting next to the code.
# Anyone can open it. That is deliberate - proof nobody can read is not proof.
LEDGER = Path(__file__).with_name("ledger.csv")

# The columns, in order. One row = one step of one run.
FIELDS = ["ts", "story", "node", "seconds", "input_tokens", "output_tokens", "tool_calls", "cost_usd", "note"]


def _prices():
    """What a thousand tokens costs us, going in and coming out.

    These come from the .env file, not from this code, because they are OUR
    deployment's prices - off our own Azure pricing page. Your numbers will
    differ; the arithmetic will not.
    """
    return (float(os.environ.get("PRICE_IN_PER_1K", "0")),
            float(os.environ.get("PRICE_OUT_PER_1K", "0")))


def cost_of(usage):
    """WHAT ONE STEP'S THINKING COST, IN DOLLARS.

    Tokens are what a model charges by - roughly, pieces of words, counted
    both going in and coming out. So: (tokens / 1000) x (price per 1000), for
    each direction, added together.

    Machinery steps consume no tokens at all, so this returns exactly zero for
    them. That zero is the whole argument for doing the cheap checks first.
    """
    usage = usage or {}
    p_in, p_out = _prices()
    return (usage.get("input_tokens", 0) / 1000) * p_in + (usage.get("output_tokens", 0) / 1000) * p_out


def record(story, node, seconds, usage=None, note=""):
    """WRITE ONE LINE. Called by every step, as it finishes.

    Note that it appends immediately rather than gathering rows and saving at
    the end. If the process dies halfway through, everything it had already
    done is still on disk and still countable. A record that only survives a
    clean shutdown is not a record.
    """
    usage = usage or {}
    cost = cost_of(usage)
    new = not LEDGER.exists()
    with LEDGER.open("a", newline="") as f:          # "a" = add to the end, never overwrite
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            writer.writeheader()                     # column titles, first time only
        writer.writerow({
            "ts": time.strftime("%H:%M:%S"), "story": story, "node": node,
            "seconds": f"{seconds:.2f}",
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "tool_calls": usage.get("tool_calls", 0),
            "cost_usd": f"{cost:.4f}", "note": note,
        })


def timed(story, node, fn, note=""):
    """Convenience: run something, time it, record it, and pass its result on."""
    start = time.time()
    result = fn()
    usage = result[1] if isinstance(result, tuple) and isinstance(result[1], dict) else None
    record(story, node, time.time() - start, usage, note)
    return result


def bill(accepted_states=("posted",), runs=None):
    """
    THE BILL  -  add up what the day actually cost.

    Prints two things:

      1. A row per story: how many steps it took, tokens in and out, and cost.

      2. COST PER ACCEPTED OUTCOME - the only number that really means
         anything. Total spend divided by the number of stories that actually
         reached a finished, posted result.

    Why that second number rather than simply "total cost"? Because total cost
    rewards doing less. Cost per accepted outcome asks the honest question:
    what did it cost to get one piece of work genuinely done? A story that was
    abandoned halfway is spend with nothing to show for it, and this number
    refuses to hide that.

    Set it beside what the same review costs in human minutes today, and you
    have the entire business case on one line.
    """
    if not LEDGER.exists():
        print("No ledger yet.")
        return

    rows = list(csv.DictReader(LEDGER.open()))
    total = sum(float(r["cost_usd"]) for r in rows)
    tokens_in = sum(int(r["input_tokens"]) for r in rows)
    tokens_out = sum(int(r["output_tokens"]) for r in rows)
    stories = sorted({r["story"] for r in rows})

    # A row per story.
    print(f"{'story':>8} {'steps':>6} {'in_tok':>8} {'out_tok':>8} {'cost':>9}")
    for s in stories:
        mine = [r for r in rows if r["story"] == s]
        print(f"{s:>8} {len(mine):>6} {sum(int(r['input_tokens']) for r in mine):>8} "
              f"{sum(int(r['output_tokens']) for r in mine):>8} "
              f"{sum(float(r['cost_usd']) for r in mine):>9.4f}")

    print(f"\nTotal: {len(rows)} steps · {tokens_in} in / {tokens_out} out tokens · ${total:.4f}")

    # And the number that matters.
    if runs:
        accepted = [s for s, state in runs.items() if state in accepted_states]
        if accepted:
            print(f"Accepted outcomes (posted): {len(accepted)} → cost per accepted outcome: ${total / len(accepted):.4f}")
        else:
            print("Accepted outcomes (posted): 0 — nothing posted yet.")
