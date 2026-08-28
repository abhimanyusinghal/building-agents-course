"""
===============================================================================
 THE TRACKER  —  how the pipeline reads and writes the real issue tracker
===============================================================================

WHAT THIS FILE IS, IN ONE SENTENCE
    A thin translator between "read the story" / "post the comment" and the
    actual web requests GitHub expects.

WHY IT IS A SEPARATE FILE - THE PART WORTH SAYING TO THE ROOM
    The process (graph.py) never mentions GitHub. It says "fetch the story"
    and "post the comment", and this file is the only place that knows those
    happen to be GitHub calls today.

    Swap your tracker for Jira, Azure DevOps or a SharePoint list and you
    rewrite THIS file. The process, the judge, the gate, the ledger and every
    lesson from today are untouched. That is what an adapter is for, and it is
    the difference between a pipeline you can move and a pipeline you cannot.

NOTHING HERE IS MOCKED
    Every function below makes a real call over the internet to a real
    repository. When a comment appears on the projector, it appeared because
    one of these ran.

WHERE THE STATE LIVES - the idea the whole day rests on
    The pipeline keeps no memory of its own. What it has done to a story is
    recorded as a LABEL on the story itself: state:new, state:checked,
    state:posted, and so on.

    So the workers stay stateless and disposable; the work item remembers.
    Kill every process on the machine and the truth is still sitting on the
    tracker, where a human being can also read it.

AUTHENTICATION
    A token in the .env file, never in this code. It is scoped to exactly two
    powers - read and write issues on one repository, nothing else. In
    Chapter 3 we deliberately swap it for a read-only one to watch what a
    genuine permission failure looks like.
===============================================================================
"""
import os
import requests

API = "https://api.github.com"


# =============================================================================
#  PLUMBING  -  the three small helpers every call below uses
# =============================================================================


def _headers():
    """Who we are, on every request.

    The token comes from the environment - so it can be rotated, or broken on
    purpose, without touching a line of code.
    """
    return {
        "Authorization": f"Bearer {os.environ['GH_TOKEN']}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _repo():
    """Which repository, in "owner/name" form. Also from the environment."""
    return os.environ["GH_REPO"]


def _check(resp):
    """DID THAT WORK? If not, stop immediately and say exactly what went wrong.

    This one function is why a wrong token produces "403: Resource not
    accessible by personal access token" rather than a silent failure three
    steps later. Failing loudly, at the point of failure, with the real
    message, is a feature - not an inconvenience.
    """
    if resp.status_code >= 400:
        raise RuntimeError(f"GitHub said {resp.status_code}: {resp.json().get('message', resp.text[:200])}")
    return resp


# =============================================================================
#  READING
# =============================================================================


def list_open_issues(since=None):
    """Every open story, oldest first.

    'since' narrows it to stories changed after a given moment - which is how
    the watcher asks "anything new since I last looked?" rather than dragging
    back the whole board every few seconds.

    Pull requests are filtered out: GitHub returns them alongside issues, and
    they are not stories.
    """
    params = {"state": "open", "per_page": 100, "direction": "asc"}
    if since:
        params["since"] = since
    resp = _check(requests.get(f"{API}/repos/{_repo()}/issues", headers=_headers(), params=params))
    return [i for i in resp.json() if "pull_request" not in i]


def story_key(issue):
    """The number humans say out loud - 4471 - pulled out of the title.

    The tracker has its own internal numbering (#1, #2, #3...) which nobody in
    a refinement meeting uses. This bridges the two.
    """
    import re as _re
    match = _re.search(r"STORY-(\d+)", issue.get("title", ""))
    return int(match.group(1)) if match else issue["number"]


def find_by_key(key):
    """Go the other way: from "4471" to the actual issue on the tracker."""
    for issue in list_open_issues():
        if story_key(issue) == int(key):
            return issue
    raise RuntimeError(f"No open issue titled STORY-{key}")


def get_issue(number):
    """One story, in full - title, body and labels."""
    return _check(requests.get(f"{API}/repos/{_repo()}/issues/{number}", headers=_headers())).json()


# =============================================================================
#  THE STATE  -  the pipeline's memory, stored on the work item
# =============================================================================


def state_of(issue):
    """WHAT HAS ALREADY BEEN DONE TO THIS STORY?

    Look through the story's labels for one starting "state:" and return the
    rest of it. No such label means nobody has touched it - so, "new".

    That default matters: a story someone files by hand, with no labels at
    all, is correctly treated as new work.
    """
    for label in issue.get("labels", []):
        name = label["name"] if isinstance(label, dict) else label
        if name.startswith("state:"):
            return name.removeprefix("state:")
    return "new"


def set_state(number, state):
    """RECORD WHAT WE JUST DID.  This is the state write.

    Replace whichever "state:" label is there with the new one, and carefully
    keep every other label - priority, team, component - exactly as it was.
    A pipeline that quietly deletes a human being's labels will not be trusted
    twice, and should not be.
    """
    issue = get_issue(number)
    keep = [l["name"] for l in issue.get("labels", []) if not l["name"].startswith("state:")]
    _check(requests.put(f"{API}/repos/{_repo()}/issues/{number}/labels",
                        headers=_headers(), json={"labels": keep + [f"state:{state}"]}))


# =============================================================================
#  WRITING
# =============================================================================


def post_comment(number, body):
    """THE STEP THAT TOUCHES THE WORLD: a real comment, on a real story.

    Everything else in this pipeline is thinking. This is the line that other
    people actually see - which is why, from Chapter 3, a named person is
    asked before it runs.
    """
    return _check(requests.post(f"{API}/repos/{_repo()}/issues/{number}/comments",
                                headers=_headers(), json={"body": body})).json()


def create_issue(title, body, labels=None):
    """File a new story. Used by the seed script, and by the phone during the demo."""
    payload = {"title": title, "body": body}
    if labels:
        payload["labels"] = labels
    return _check(requests.post(f"{API}/repos/{_repo()}/issues", headers=_headers(), json=payload)).json()


def search_similar(query):
    """THE JUDGE'S SECOND TOOL: has somebody already filed this?

    The agent chooses for itself whether to reach for this on any given story.
    When it does, the ledger shows an extra tool call - which is the in-run
    planning, visible as a number.
    """
    resp = _check(requests.get(f"{API}/search/issues", headers=_headers(),
                               params={"q": f"repo:{_repo()} in:title,body {query}", "per_page": 5}))
    items = resp.json().get("items", [])
    return [f"#{i['number']} {i['title']}" for i in items]


# =============================================================================
#  HOUSEKEEPING  -  used by the seed and reset scripts, never during a run
# =============================================================================


def ensure_labels():
    """Create the six state labels once, with their colours. Leaves existing ones alone.

    These six ARE the state machine, and there is nothing grander to it than
    this list:

        new           nobody has touched it
        checked       judged, comment posted
        needs-human   escalated, waiting on a person
        posted        finished and authorised
        hold          deliberately parked, not in play
        held          a person said no - visible, owned, not silently dropped
    """
    wanted = {
        "state:new": "0e8a16", "state:checked": "1d76db", "state:needs-human": "b96c12",
        "state:posted": "5319e7", "state:hold": "cccccc", "state:held": "d93f0b",
    }
    existing = {l["name"] for l in _check(requests.get(
        f"{API}/repos/{_repo()}/labels", headers=_headers(), params={"per_page": 100})).json()}
    for name, color in wanted.items():
        if name not in existing:
            _check(requests.post(f"{API}/repos/{_repo()}/labels", headers=_headers(),
                                 json={"name": name, "color": color}))


def delete_pipeline_comments(number, marker="<!-- story-pipeline -->"):
    """Remove only the comments THIS pipeline wrote. Reset-time only.

    Every comment we post carries a hidden marker, invisible to a reader. That
    marker is how the reset can clean up after the demo without ever touching
    a comment written by a human being.
    """
    comments = _check(requests.get(f"{API}/repos/{_repo()}/issues/{number}/comments",
                                   headers=_headers(), params={"per_page": 100})).json()
    for c in comments:
        if marker in c.get("body", ""):
            _check(requests.delete(f"{API}/repos/{_repo()}/issues/comments/{c['id']}",
                                   headers=_headers()))
