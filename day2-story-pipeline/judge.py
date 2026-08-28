"""
===============================================================================
 THE JUDGE  —  Chapter 3.  It can now raise its hand.
===============================================================================

WHAT CHANGED SINCE CHAPTER 1 - the contract grew two fields, and the
instructions grew one paragraph. That is the entirety of "building escalation".

    escalate         - does this story touch something consequential?
    escalate_reason  - one line naming what it touches.

The judge still judges. What it does NOT do is decide alone: when it sets that
flag, the process routes the story to a person before anything is posted.

WHAT AN AGENT ACTUALLY IS, HERE
    Three things, and no magic:
        - INSTRUCTIONS : a paragraph telling it what job it is doing.
        - TOOLS        : things it may go and look at if it decides to.
        - A CONTRACT   : the fixed shape its answer must come back in.
                         (in this chapter, that shape gains the raised hand)

    Give it those three and it will work out its own route. On one story it
    might read the Definition of Ready and stop. On another it might read the
    Definition of Ready, then search the backlog for a near-duplicate, then
    answer. We never told it which to do. That is the freedom that makes it
    useful on stories nobody anticipated.

THE BOUNDARY - THE WHOLE POINT OF THE DAY
    Inside this file, the agent plans its own route.
    Outside this file, it has no say at all: the process decides when it runs,
    what it is given, and what it must hand back.

    Freedom inside the box. Fixed shape at the door.
===============================================================================
"""
import os
from pathlib import Path
from pydantic import BaseModel, Field
from langchain_openai import AzureChatOpenAI
from langchain.agents import create_agent
from langchain_core.tools import tool

import gh

# THE TURN LIMIT. The agent chooses its own route - but not an unlimited one.
# It gets a budget of turns, not a blank cheque. Without this, a confused agent
# can circle forever, and you find out from the bill.
MAX_JUDGE_STEPS = 8


# =============================================================================
#  THE CONTRACT  -  the only door out of the judgement box
# =============================================================================
#
# Yesterday this same judge answered in three paragraphs, because the next
# reader was a human being. Today the next reader is code - so the same three
# things become three named fields.
#
# Nothing else gets out. However the agent reasoned, whatever it read, whatever
# it considered and discarded, what leaves this box is exactly this shape. That
# is what makes the rest of the pipeline possible to write.
#
class Review(BaseModel):
    """The contract. However the agent got there, this is the only door out."""

    # Was it ready, or not? One of two words.
    verdict: str = Field(description="Ready or Not ready")

    # What failed, and against which numbered rule. Quoting the number is what
    # makes a finding checkable by the author instead of arguable.
    findings: list[str] = Field(description="One line per failed criterion, quoting the DoR number and the exact words that failed it. Empty when Ready.")

    # The note that will actually be posted to the story's author.
    comment: str = Field(description="Refinement comment to the author, under 80 words.")

    # --- ADDED IN CHAPTER 3: ESCALATION -------------------------------------
    #
    # These two fields are how the judge raises its hand.
    #
    # Read what they are asking for, because it is the design point of the
    # whole chapter: NOT "how confident are you?" A model's stated confidence
    # is a sentence, not a measurement, and it is not a safe thing to route on.
    #
    # Instead we ask about what the story TOUCHES - card data, money, legal
    # wording. Those are properties you can know before the run even starts,
    # and they are the same properties a sensible organisation would want a
    # person to sign off on regardless of who did the work.
    #
    # Consequence routes upward. Not mood.
    escalate: bool = Field(default=False, description="True when the story touches security, payments, card or personal data, or legal wording.")
    escalate_reason: str = Field(default="", description="One line naming what it touches. Empty when escalate is false.")


# =============================================================================
#  THE TOOLS  -  what the agent is allowed to go and look at
# =============================================================================
#
# Two of them. The agent decides for itself whether to use either, both, or
# neither on any given story. Notice how small the list is: an agent's tools
# are a permission list, and every one you add is something it can now do.


@tool
def read_definition_of_ready() -> str:
    """Read the team's Definition of Ready — the only standard stories are judged against."""
    # Our written standard, as a file. The agent has to ask for it; it is not
    # baked into the model. Change this file and the judge's standard changes -
    # no retraining, no redeployment.
    return Path(__file__).with_name("definition-of-ready.md").read_text()


@tool
def search_backlog(query: str) -> str:
    """Search existing stories in the tracker for near-duplicates of a phrase."""
    # Lets the agent check whether somebody already filed this story. It uses
    # this one only sometimes - which is exactly the in-run planning we keep
    # pointing at in the ledger.
    hits = gh.search_similar(query)
    return "\n".join(hits) if hits else "No matches."


# =============================================================================
#  THE INSTRUCTIONS  -  the agent's job description, in plain English
# =============================================================================
#
# Read this aloud and it is simply how you would brief a new reviewer on their
# first morning. Note what it does NOT say: it does not describe a procedure,
# step by step. It sets the job, the standard, and the limits - and leaves the
# route to the agent.
#
SYSTEM_PROMPT = """You check a single user story against the team's Definition of Ready and draft
the refinement comment that goes back to the author. You do not edit the story, and you
do not decide whether it is picked up.

Judge the story only against the Definition of Ready from your tool. If a rule is not
in that document, it is not a rule. Quote the criterion number for every finding.

Never call a story ready if any acceptance criterion cannot be observed and tested by
somebody other than the author.

If the story touches security, payments, card or personal data, or legal wording, set
escalate to true with a one-line reason. You still judge it — you do not decide alone.
"""
# ^ Three sentences worth noticing:
#     1. "You do not edit / you do not decide"     - the limits of its authority.
#     2. "If a rule is not in that document..."    - no inventing standards.
#     3. "Never call a story ready if..."          - the one hard line it may not cross.


# =============================================================================
#  ASSEMBLY  -  putting the agent together and running it once
# =============================================================================


def _model():
    """Which model, and where it lives.

    This points at our own deployment on our own Azure subscription - the
    credentials come from the .env file, never from this code.
    """
    return AzureChatOpenAI(
        azure_deployment=os.environ["AZURE_OPENAI_DEPLOYMENT"],
        api_version=os.environ.get("OPENAI_API_VERSION", "2025-04-01-preview"),
    )


def build_judge():
    """Assemble the agent from its four parts: a model, its tools, its
    instructions, and the shape its answer must take."""
    return create_agent(
        model=_model(),
        tools=[read_definition_of_ready, search_backlog],
        system_prompt=SYSTEM_PROMPT,
        response_format=Review,        # <- the contract, enforced by the framework
    )


def run_judge(title, body):
    """
    ONE JUDGEMENT, START TO FINISH.

    Hand in a story; get back two things:
        - the review, in the contract's fixed shape
        - a count of what it used: tokens in, tokens out, and how many times it
          reached for a tool

    That second thing is what makes the bill at the end of the day possible.
    We are not estimating the cost of judgement; we are counting it.
    """
    agent = build_judge()

    result = agent.invoke(
        {"messages": [{"role": "user", "content": f"Story {title}\n\n{body}"}]},
        # THE TURN LIMIT, ENFORCED. The agent may plan its own route, but it
        # runs out of road here rather than circling forever.
        config={"recursion_limit": MAX_JUDGE_STEPS * 2},
    )

    # Add up what the whole conversation actually consumed. The agent may have
    # taken several turns internally; we want the total for the story, because
    # the total is what we are billed for.
    usage = {"input_tokens": 0, "output_tokens": 0, "tool_calls": 0}
    for message in result["messages"]:
        meta = getattr(message, "usage_metadata", None)
        if meta:
            usage["input_tokens"] += meta.get("input_tokens", 0)
            usage["output_tokens"] += meta.get("output_tokens", 0)
        usage["tool_calls"] += len(getattr(message, "tool_calls", []) or [])

    # 'structured_response' is the answer already forced into the Review shape.
    return result["structured_response"], usage
