"""
===============================================================================
 THE SPINE  —  the refinement process, written down as a diagram you can run
===============================================================================

WHAT THIS FILE IS, IN ONE SENTENCE
    It is the flowchart from the wall, turned into something a computer can
    execute: a list of steps, and the arrows that say which step follows which.

HOW TO READ IT (top to bottom, four parts)
    1. THE CAPS      - the limits. What this process is never allowed to exceed.
    2. THE WORK ITEM - the facts we carry about one story while it is being handled.
    3. THE STEPS     - four of them. Each is a small, named job.
    4. THE ARROWS    - which step leads to which. This is the process itself.

THE ONE DISTINCTION THAT MATTERS
    Three of the four steps are MACHINERY: they do the same thing every time,
    they cost nothing, and you could predict their output on paper. Exactly one
    step is JUDGEMENT: it asks a model to form an opinion, it costs money, and
    it will word things differently every time you run it.

    Machinery is fixed here, in the design. Judgement is free to plan its own
    route inside its own box - but it must hand back its answer in a fixed
    shape. That shape is called the contract, and it is the only way out of
    the judgement box.

WHERE THE THINKING HAPPENS
    Nowhere in this file does the computer decide what the process should be.
    We decided that. The model decides only one thing - whether a story is
    ready - and it is asked that question inside one clearly marked step.
===============================================================================
"""
import time
from typing import Optional
from typing_extensions import TypedDict

# LangGraph is the library that turns "steps and arrows" into a running process.
# StateGraph = the diagram itself. START and END = where a run begins and stops.
from langgraph.graph import StateGraph, START, END
from langgraph.types import RetryPolicy, interrupt      # CH3: interrupt = the pause

import gh        # our adapter for the tracker  (read a story, post a comment)
import judge as judge_mod   # the Day 1 agent, wrapped so this file can call it
import ledger    # the running record: one line per step, with time and cost
import mailer    # CH3: the people adapter - real mail, to a real inbox


# =============================================================================
#  1. THE CAPS  -  the limits, decided before anything runs
# =============================================================================
#
# Three numbers, and they are the cheapest three lines in the file.
#
#   - how many turns the judge is allowed to take before we stop it
#   - how long one story is allowed to take, in seconds
#   - how much one story is allowed to cost, in dollars
#
# Every one of them is enforced somewhere in the code below or in the runner.
# A limit that is written down but never checked is not a limit; it is a wish.
# And a process with no limit at all has not accepted a risk - it has simply
# not noticed one yet.
#
CAPS = {
    "max_judge_steps": judge_mod.MAX_JUDGE_STEPS,  # turns the judge may take (enforced in judge.py)
    "max_run_seconds": 120,                        # seconds per story  (enforced in pipeline.py)
    "max_cost_usd_per_run": 0.50,                  # dollars per story  (enforced below, in judge())
}

# Every comment this pipeline writes starts with this hidden marker. It is
# invisible to a reader on the tracker, but it lets the reset script find and
# remove exactly the comments we posted, and nobody else's.
MARKER = "<!-- story-pipeline -->"


# =============================================================================
#  2. THE WORK ITEM  -  what we know about one story, while it is being handled
# =============================================================================
#
# One of these exists per run. Think of it as the folder that travels with a
# story through the process: each step reads what it needs from the folder and
# drops its own result back in, for the steps that come after.
#
class Run(TypedDict):
    story: int                 # the story number people say out loud, e.g. 4471
    issue: int                 # the tracker's own internal number for that story
    title: str                 # the story's title, once we have fetched it
    body: str                  # the story's full text, once we have fetched it
    state: str                 # CH2: the story's label - the pipeline's memory
    review: Optional[dict]     # THE CONTRACT: verdict / findings / comment.
                               #   Empty until something decides. "Optional"
                               #   simply means "this may still be blank."
    source: str                # which arrival started this run (manual? scheduled?)
    escalated: bool            # CH3: did the judge raise its hand?
    approved: Optional[bool]   # CH3: what the person answered. blank until they reply
    posted: bool               # has the comment actually been written to the tracker?


# =============================================================================
#  3. THE STEPS  -  four named jobs
# =============================================================================
#
# Each one takes the folder, does its job, and returns only the facts it wants
# added to the folder. None of them knows what runs next; the arrows decide that.
# That separation is deliberate - it is why a step can be re-ordered, retried,
# or replaced without rewriting the others.


def fetch(run: Run):
    """
    STEP 1 - GO AND GET THE STORY.        [ machinery - no model, no cost ]

    In plain English: open the tracker and read the story this run is about.
    Nothing is judged here and nothing is decided. We are only collecting the
    words that the later steps will look at.

    We time it and write a line in the ledger, because we time and record every
    step - including the free ones. That is how the bill at the end of the day
    can be honest about which parts actually cost anything.
    """
    started = time.time()
    issue = gh.get_issue(run["issue"])                      # ask the tracker for the story
    ledger.record(run["story"], "fetch", time.time() - started)
    return {"title": issue["title"], "body": issue.get("body") or "",
            "state": gh.state_of(issue)}          # CH2: read the label too


def guard(run: Run):
    """CH2. STEP 2 - HAVE WE ALREADY DONE THIS ONE?      [ machinery ]

    Look at the label. "new" means nobody has touched this story, so it is ours.
    Anything else means the work is done or in hand, and this run stops now.

    The fix lives HERE, in the process - so every trigger anyone adds after
    today inherits it for free. No trigger discipline required, forever.
    """
    if run["state"] != "new":
        ledger.record(run["story"], "guard", 0.0, note=f"skipped: state is {run['state']}")
    return {}


def route_after_guard(run: Run) -> str:
    """Not new means not ours: end the run here, having changed nothing."""
    return "rules_gate" if run["state"] == "new" else END


def rules_gate(run: Run):
    """
    STEP 2 - THE FREE CHECK.              [ machinery - no model, no cost ]

    In plain English: before we pay anybody to think, ask the one question we
    can answer ourselves - does this story even have an "Acceptance criteria"
    section?

    If it does not, we already know the answer. The story cannot be ready,
    because there is nothing a tester could observe. We write the verdict
    ourselves, in fixed words, and the model is never called at all.

    THIS IS THE MONEY LESSON OF THE WHOLE PIPELINE:
        a rule you can write down should never be sent to a model.
        Rules are free. Judgement is not.
    """
    started = time.time()

    # The check itself: does the story text contain that heading anywhere?
    has_criteria = "acceptance criteria" in run["body"].lower()

    if not has_criteria:
        # No criteria section. We can answer this without help - so we do, and
        # this run will cost exactly nothing.
        review = {
            "verdict": "Not ready",
            "findings": ["2: no acceptance-criteria section present"],
            "comment": ("Refinement: the story has no Acceptance criteria section, so there is "
                        "nothing a tester could observe or verify (Definition of Ready, criterion 2). "
                        "Please add criteria and re-queue."),
        }
        ledger.record(run["story"], "rules_gate", time.time() - started, note="stopped: no criteria — model never called")
        # Putting a review in the folder is how this step says "I have already
        # answered - do not bother the model." The arrow below reads that.
        return {"review": review}

    # Criteria are present, so this is a genuine judgement call. Add nothing to
    # the folder and let the story carry on to the judge.
    ledger.record(run["story"], "rules_gate", time.time() - started, note="criteria present")
    return {}


def route_after_rules(run: Run) -> str:
    """
    THE FORK IN THE ROAD, after step 2.

    In plain English: "did the free check already answer this?"
        yes -> skip the judge entirely and go straight to posting
        no  -> send it to the judge

    This one line is the funnel from the slides. Cheap work first; expensive
    work only for the stories that actually need it.
    """
    return "gate_ask" if run["review"] else "judge"   # CH3: even free verdicts gate


def judge(run: Run):
    """
    STEP 3 - THE JUDGEMENT.       [ THE AMBER BOX - the only step that thinks ]

    In plain English: hand the story to the agent we built on Day 1 and ask it
    whether the story meets our Definition of Ready.

    This is the one step where we do not control the route. Inside this box the
    agent decides for itself: whether to open the Definition of Ready, whether
    to search the backlog for near-duplicates, how many turns to take. That
    freedom is the point - it is why it can handle stories we never anticipated.

    What we DO control is the door out. However it got to its answer, it must
    hand back the same three things every time: a verdict, a list of findings,
    and a drafted comment. That fixed shape is the contract. The next reader of
    this answer is code, and code cannot work with "mostly clear".

    Run this step twice on the same story and you will get the same verdict
    worded differently. That is not a defect. That is what judgement is.
    """
    started = time.time()

    # Ask the agent. It returns its answer, plus a count of what it used.
    review, usage = judge_mod.run_judge(f"STORY-{run['story']} — {run['title']}", run["body"])

    # What did that thinking actually cost, in real money?
    spent = ledger.cost_of(usage)
    ledger.record(run["story"], "judge", time.time() - started, usage,
                  note=f"{usage['tool_calls']} tool calls")

    # THE SPEND CAP, ENFORCED. If one story somehow costs more than we said any
    # single story may cost, the run stops here and says so. A cap that nothing
    # ever reads is decoration; this one is real.
    if spent > CAPS["max_cost_usd_per_run"]:
        raise RuntimeError(f"judgement cost ${spent:.4f}, over the "
                           f"${CAPS['max_cost_usd_per_run']:.2f} cap for one run")

    # Put the agent's answer in the folder, in the contract's fixed shape.
    return {"review": review.model_dump()}


def gate_ask(run: Run):
    """CH3. STEP 5a - THE ASK.   [ machinery, but it touches the outside world ]

    One mail to a named person, carrying everything they need to decide: the
    verdict, the findings, and the exact comment that would be posted. Context,
    not homework.

    Runs exactly ONCE per run - which is the only reason it is separate from
    the step below.
    """
    started = time.time()
    review = run["review"]
    escalated = bool(review.get("escalate"))     # routed on what it TOUCHES, not on mood
    if escalated:
        gh.set_state(run["issue"], "needs-human")
    mailer.send_approval_request(run["story"], review, escalated)
    ledger.record(run["story"], "gate:ask", time.time() - started,
                  note="escalated, mail sent" if escalated else "mail sent")
    return {"escalated": escalated}


def gate_wait(run: Run):
    """CH3. STEP 5b - THE WAIT.        [ this is where the run parks ]

    'interrupt' stops the run and writes its whole position to disk. Nothing
    loops, nothing polls, no tokens burn. The run simply is not running - until
    an answer arrives, at which point it carries on from this exact point.

    A step that parks is REPLAYED from its first line on resume. That is why
    the mail lives in the step above and nothing else lives in this one: merge
    them, and one approval sends two mails.
    """
    answer = interrupt({"story": run["story"], "verdict": run["review"]["verdict"],
                        "escalated": run.get("escalated", False)})
    return {"approved": str(answer).lower().startswith("approve")}


def route_after_gate(run: Run) -> str:
    """The person said yes -> post it. The person said no -> hold it."""
    return "post_review" if run["approved"] else "hold"


def post_review(run: Run):
    """
    STEP 4 - THE STEP THAT TOUCHES THE WORLD.   [ machinery - no model, no cost ]

    In plain English: take the verdict and the drafted comment, format them
    into a readable note, and write it on the real story in the real tracker,
    where the story's author will actually see it.

    Everything before this step was thinking. This is the only step that
    changes something outside this program - and that is exactly why, later in
    the session, this is the step a person gets asked about first.
    """
    started = time.time()
    review = run["review"]

    # Assemble the comment: a hidden marker, the verdict as a heading, each
    # finding as a bullet, then the drafted note to the author.
    body = (f"{MARKER}\n**Story Check — {review['verdict']}**\n\n"
            + ("\n".join(f"- {f}" for f in review["findings"]) or "_No findings._")
            + f"\n\n{review['comment']}")

    gh.post_comment(run["issue"], body)                     # the real write
    gh.set_state(run["issue"], "posted")    # CH3: the story is now finished
    ledger.record(run["story"], "post_review", time.time() - started, note="state -> posted")
    return {"posted": True}


def hold(run: Run):
    """CH3. STEP 6b - REJECTED. HOLD IT.        [ machinery ]

    A rejection is an outcome too, and it gets recorded like one. The failure
    this prevents is the quiet one: work a person declined that then simply
    disappears, because nobody wrote the refusal down anywhere.
    """
    gh.set_state(run["issue"], "held")
    ledger.record(run["story"], "hold", 0.0, note="rejected at review - held")
    return {"posted": False}


# =============================================================================
#  4. THE ARROWS  -  which step follows which. THIS is the process.
# =============================================================================
#
# Everything above was four jobs sitting in a drawer. This function is what
# turns them into a process, by saying what order they happen in.
#
# Read the arrows aloud and you have described the whole pipeline:
#
#       start -> fetch the story
#             -> apply the free rules check
#             -> then EITHER  judge it  OR  skip straight to posting
#             -> post the comment
#             -> done
#
def build_graph(checkpointer=None):
    builder = StateGraph(Run)

    # --- register the four steps by name -------------------------------------
    #
    # Note the retry on 'fetch' only. Reading a story is safe to repeat - if the
    # network hiccups, doing it again changes nothing. That safety is what earns
    # a step the right to be retried. We do not put a retry on posting, because
    # repeating a write means posting the comment twice.
    builder.add_node("fetch", fetch, retry_policy=RetryPolicy(max_attempts=3, retry_on=Exception))
    builder.add_node("guard", guard)                        # CH2
    builder.add_node("rules_gate", rules_gate)
    builder.add_node("judge", judge)
    builder.add_node("gate_ask", gate_ask)                  # CH3
    builder.add_node("gate_wait", gate_wait)                # CH3
    builder.add_node("post_review", post_review)
    builder.add_node("hold", hold)                          # CH3

    # --- draw the arrows -----------------------------------------------------
    builder.add_edge(START, "fetch")                # every run begins by fetching
    builder.add_edge("fetch", "guard")              # CH2: the guard sits first
    builder.add_conditional_edges("guard", route_after_guard,          # CH2
                                  {"rules_gate": "rules_gate", END: END})

    # The fork: route_after_rules picks one of these two names.
    builder.add_conditional_edges("rules_gate", route_after_rules,
                                  {"judge": "judge", "gate_ask": "gate_ask"})   # CH3

    builder.add_edge("judge", "gate_ask")           # CH3: judged, then ask a person
    builder.add_edge("gate_ask", "gate_wait")       # CH3: ask, then park
    builder.add_conditional_edges("gate_wait", route_after_gate,                # CH3
                                  {"post_review": "post_review", "hold": "hold"})
    builder.add_edge("post_review", END)            # and that is the end of a run
    builder.add_edge("hold", END)                   # CH3: the other ending

    # 'compile' checks the diagram makes sense and hands back something runnable.
    # The checkpointer, when supplied, is what lets a half-finished run be picked
    # up again later instead of started from scratch.
    return builder.compile(checkpointer=checkpointer)
