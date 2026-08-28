"""
===============================================================================
 THE RUNNER  —  the ways work arrives, and the ways we operate the pipeline
===============================================================================

WHAT THIS FILE IS, IN ONE SENTENCE
    graph.py describes the process; this file is everything AROUND it - what
    starts a run, what to do when one is waiting, and how to see what it cost.

THE THREE ARRIVALS - and the whole of Chapter 2 is in this list

    run    a person asks for one story, now.          (a manual arrival)
    sweep  go through every open story.               (the schedule's arrival)
    watch  sit and wait for something to happen.      (the event arrival)

    Notice that the last two overlap on purpose. You want the WATCHER because
    it is fast - it reacts within seconds. You want the SWEEP because it is a
    safety net - it catches whatever the watcher missed while it was down.

    The moment both exist, the same story can arrive twice. That is not
    carelessness, it is arithmetic. What you would like from a delivery system
    is "exactly once". What every real system actually offers is "at least
    once". So: twice is not an accident. Twice is a promise.

    The answer is NOT to be careful with triggers. It is to make the process
    safe to run twice - which is what the guard in graph.py does, once, for
    every trigger anyone will ever add.

THE OPERATIONS - what you do to a running system

    answer       a person's decision, typed instead of mailed
    resume       pick a run back up: after a crash, or after a fix
    stall-sweep  find runs that have been waiting too long and raise the alarm
    bill         what today actually cost
    mail-test    one round trip, to prove the mail leg works before you need it

EVERY COMMAND, IN FULL
  python pipeline.py run --story 4471      one story, now (a manual arrival)
  python pipeline.py sweep                 every open story (the schedule's arrival)
  python pipeline.py watch                 live: new issues + approval replies (the event arrival)
  python pipeline.py answer --story N --approve|--reject     resume a waiting run by hand
  python pipeline.py resume --story N      resume after a crash or a fixed failure
  python pipeline.py stall-sweep           alert on runs waiting past the clock
  python pipeline.py bill                  the ledger, totalled
  python pipeline.py mail-test             pre-flight: one round-trip mail
==============================================================================="""
import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

# The step lines use ⏸ ✗ ○. On a console they render; redirected to a file on Windows
# they fall back to the ANSI code page and raise UnicodeEncodeError — and the ⏸ print
# sits inside _drive's try, so a parked run would be recorded as failed instead of
# waiting. One line makes the output encoding-safe wherever it is pointed.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))

import os                                    # noqa: E402  (env first, then adapters)
import gh                                    # noqa: E402
import ledger                                # noqa: E402
from graph import build_graph, CAPS          # noqa: E402
from langgraph.checkpoint.sqlite import SqliteSaver   # noqa: E402
from langgraph.types import Command          # noqa: E402

RUNS = Path(__file__).with_name("runs.json")
DB = Path(__file__).with_name("checkpoints.db")


# =============================================================================
#  RUN HISTORY  -  a small note of where each story got to
# =============================================================================
#
# Deliberately separate from the ledger. The ledger is the accountant's record
# - every step, forever. This is the operator's record - the current status of
# each story, so that "which runs are waiting?" is a question we can answer.
def _load_runs():
    return json.loads(RUNS.read_text()) if RUNS.exists() else {}


def _save_run(story, **fields):
    runs = _load_runs()
    entry = runs.get(str(story), {})
    entry.update(fields)
    # A run that has since succeeded must not keep wearing its old error. Without
    # this, runs.json shows status "posted" beside the failure from two attempts
    # ago — confusing on a screen, and wrong in a record.
    if fields.get("status") not in (None, "failed"):
        entry.pop("error", None)
    runs[str(story)] = entry
    RUNS.write_text(json.dumps(runs, indent=2))


# =============================================================================
#  THE GRAPH, WITH A MEMORY ATTACHED
# =============================================================================
def _graph():
    """Build the process, and give it somewhere to write its position down.

    The "checkpointer" is an ordinary database file on disk. After every step,
    the run's exact position is saved into it. That one detail is what makes
    two things possible:

        - a run can PARK at the gate for a weekend, costing nothing
        - a run that CRASHES can be picked up at the step it died on

    Without it, an interrupted run has nowhere to be resumed from, and the only
    honest option is to start the whole thing again.
    """
    checkpointer = SqliteSaver(sqlite3.connect(DB, check_same_thread=False))
    return build_graph(checkpointer=checkpointer)


def _config(thread):
    return {"configurable": {"thread_id": thread}}


def _drive(graph, payload, config, story):
    """
    RUN ONE STORY THROUGH THE PROCESS, narrating each step as it happens.

    The step lines you see on screen are printed from here. So are the three
    endings a run can have:

        (blank)  it finished
        parked   it stopped at the gate, waiting for a person
        FAILED   it broke, and we say at which step

    That last one is worth pausing on. When something breaks we do not retry
    blindly and we do not carry on regardless. We stop, name the step, and
    print the exact command that resumes once the cause is fixed. A failure
    that tells you where it happened is worth ten that quietly recover.
    """
    started = time.time()
    interrupted, values = False, {}
    try:
        for mode, chunk in graph.stream(payload, config, stream_mode=["updates", "values"]):
            if mode == "values":
                values = chunk
                continue
            for node, update in chunk.items():
                if node == "__interrupt__":
                    interrupted = True
                    print(f"  ⏸  gate — approval mail sent; run parked, waiting for the reply")
                else:
                    stamp = time.time() - started
                    extra = ""
                    if isinstance(update, dict):
                        if "review" in update and update["review"]:
                            extra = f"→ {update['review']['verdict']}"
                        if node == "post_review":
                            extra = "→ comment posted on the issue"
                    print(f"  {stamp:5.1f}s  {node:<12} {extra}")
                    # The wall clock, enforced. Declared in graph.py, checked here.
                    if stamp > CAPS["max_run_seconds"]:
                        raise TimeoutError(
                            f"run passed the {CAPS['max_run_seconds']}s cap at step {node}")
    except Exception as error:
        _save_run(story, status="failed", error=str(error)[:300], updated=time.strftime("%H:%M:%S"))
        print(f"  ✗ FAILED at a step: {error}")
        print(f"    fix the cause, then: python pipeline.py resume --story {story}")
        return "failed"
    if interrupted:
        _save_run(story, status="waiting", since=time.time(), updated=time.strftime("%H:%M:%S"))
        return "waiting"
    outcome = "posted" if values.get("posted") else ("held" if values.get("approved") is False else "done")
    if values.get("state") not in (None, "new") and not values.get("posted") and values.get("review") is None:
        outcome = f"skipped at guard (state:{values.get('state')})"
        print(f"  ○  run ended at the guard — state is {values.get('state')}, not ours")
    _save_run(story, status=outcome, updated=time.strftime("%H:%M:%S"))
    return outcome


def run_story(graph, story, source="manual", issue_number=None):
    if issue_number is None:
        issue_number = gh.find_by_key(story)["number"]
    thread = f"SC-{story}-{int(time.time())}"
    _save_run(story, thread=thread, status="running", source=source, updated=time.strftime("%H:%M:%S"))
    print(f"STORY-{story}  (#{issue_number} · {source})  thread {thread}")
    return _drive(graph, {"story": story, "issue": issue_number, "source": source,
                          "review": None, "posted": False}, _config(thread), story)


def resume_story(graph, story, value=None):
    runs = _load_runs()
    entry = runs.get(str(story))
    if not entry or "thread" not in entry:
        print(f"No recorded run for STORY-{story}.")
        return
    payload = Command(resume=value) if value is not None else None
    print(f"STORY-{story}  resuming thread {entry['thread']}"
          + (f" with answer: {value}" if value else " from its checkpoint"))
    return _drive(graph, payload, _config(entry["thread"]), story)


# ---------------------------------------------------------------- the arrivals
def sweep(graph):
    """
    THE SCHEDULE'S ARRIVAL - the safety net. Hand EVERY open story to the pipeline.

    Read that again, because the design decision is inside it: the sweep is
    deliberately stupid. It does not try to work out what has already been
    done. It just offers everything, every time.

    It can afford to be stupid because the PROCESS is responsible for knowing
    what is already finished - the guard turns away anything that is not new.
    Put the cleverness in the trigger and you must repeat it in the next
    trigger, and the one after that. Put it in the process and it is done once.

    A safety net is allowed to be paranoid. That is what makes it a safety net.

    (The one thing it skips: stories parked on state:hold, which a human being
    has deliberately taken out of play.)
    """
    issues = [i for i in gh.list_open_issues() if gh.state_of(i) != "hold"]
    print(f"sweep: {len(issues)} open stories")
    for issue in issues:
        run_story(graph, gh.story_key(issue), source="sweep", issue_number=issue["number"])


def watch(graph):
    """
    THE EVENT ARRIVAL - and the gatekeeper. This one does two jobs.

        1. Every few seconds, ask the tracker: any new stories? Start them.
        2. Every few seconds, check the mailbox: any approval replies? Wake
           the runs that were waiting for them.

    This is the loop that makes the three-in-the-morning story work. Nobody is
    at a keyboard; a story is filed from a phone in a corridor; seconds later
    it has been judged and the result is on the tracker.

    Ctrl+C stops it. That is not an inconvenience - it is the kill switch, and
    every unattended process should have one you can reach without thinking.

    ONE THING TO KNOW: it stamps the time when it starts, and only asks about
    things that changed AFTER that moment. A story that changed before the
    watcher was running is already behind it, and will not be seen.
    """
    import mailer
    interval = int(os.environ.get("WATCH_SECONDS", "15"))
    since_issues = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    since_mail = mailer.now_iso()
    seen = set()
    print(f"watching for new stories and approval replies every {interval}s — Ctrl+C stops it")
    while True:
        time.sleep(interval)
        for issue in gh.list_open_issues(since=since_issues):
            number = issue["number"]
            if number in seen or gh.state_of(issue) not in ("new",):
                continue
            seen.add(number)
            run_story(graph, gh.story_key(issue), source="watcher", issue_number=number)
        try:
            answers = mailer.poll_replies(since_mail)
        except Exception as error:
            print(f"  mail poll hiccup: {error}")
            continue
        runs = _load_runs()
        for story, answer in answers.items():
            entry = runs.get(str(story), {})
            if entry.get("status") == "waiting":
                resume_story(graph, story, value=answer)


def stall_sweep():
    """
    THE CLOCK. Any run waiting too long becomes somebody's mail.

    This is one of the smallest functions in the repo and it carries one of the
    biggest rules: EVERY WAITING STATE HAS A CLOCK AND AN OWNER.

    A process that is patiently waiting and a process that is completely lost
    look identical from outside - for hours, sometimes for weeks. The only
    thing that separates them is a clock. Without one, "waiting" quietly
    becomes "forgotten", and nobody can tell you when it happened.
    """
    import mailer
    clock = int(os.environ.get("STALL_MINUTES", "2"))
    stalled = 0
    for story, entry in _load_runs().items():
        if entry.get("status") == "waiting":
            minutes = int((time.time() - entry.get("since", time.time())) // 60)
            if minutes >= clock:
                mailer.send_stall_alert(story, minutes)
                print(f"STORY-{story}: waiting {minutes} min → alert sent")
                stalled += 1
    print(f"stall-sweep: {stalled} stalled run(s)" if stalled else "stall-sweep: nothing waiting past the clock")


# ---------------------------------------------------------------- entry
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("verb", choices=["run", "sweep", "watch", "answer", "resume", "stall-sweep", "bill", "mail-test"])
    parser.add_argument("--story", type=int)
    parser.add_argument("--approve", action="store_true")
    parser.add_argument("--reject", action="store_true")
    args = parser.parse_args()

    # An answer is a decision about the world; a forgotten flag must not quietly
    # become one. Without this, `answer --story N` holds the story and stamps
    # state:held — a rejection nobody chose.
    if args.verb == "answer" and args.approve == args.reject:
        parser.error("answer needs exactly one of --approve or --reject")

    if args.verb == "bill":
        runs = {s: e.get("status", "") for s, e in _load_runs().items()}
        ledger.bill(runs=runs)
        return
    if args.verb == "stall-sweep":
        stall_sweep()
        return
    if args.verb == "mail-test":
        import mailer
        mailer.send("[story-pipeline] mail test", "If you can read this, the mail leg works.")
        print("sent — check the inbox")
        return

    graph = _graph()
    if args.verb == "run":
        run_story(graph, args.story)
    elif args.verb == "sweep":
        sweep(graph)
    elif args.verb == "watch":
        watch(graph)
    elif args.verb == "answer":
        resume_story(graph, args.story, value="approve" if args.approve else "reject")
    elif args.verb == "resume":
        resume_story(graph, args.story)


if __name__ == "__main__":
    main()
