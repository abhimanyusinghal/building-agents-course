"""
===============================================================================
 THE PEOPLE  —  how the pipeline asks a human being, and hears the answer back
===============================================================================

WHAT THIS FILE IS, IN ONE SENTENCE
    The pipeline's way of talking to a person: it sends a real mail to a real
    inbox, and watches for the reply.

WHY MAIL, AND NOT A DASHBOARD
    Because the reviewer is not sitting in our tool. They are in a corridor,
    on a phone, between two meetings. The cheapest approval mechanism in the
    world is the one already on their home screen.

    Note what that buys: no new app to install, no account to create, no
    training. A one-word reply from a phone is the entire human interface of
    this pipeline.

THE RULE THIS FILE FOLLOWS: CONTEXT, NOT HOMEWORK
    Look at what goes into the approval mail below - the verdict, every
    finding, and the exact comment that would be posted. Everything the
    reviewer needs to decide is in the message itself.

    No link to click, nothing to go and look up, no context to reconstruct.
    An approval request that requires research is an approval request that
    sits unread until Monday.

HOW A REPLY FINDS ITS WAY BACK TO THE RIGHT RUN
    Every mail carries a marker in its subject, like [SC-4512]. When somebody
    replies, that marker travels with it - so the pipeline can tell which of
    the parked runs this answer belongs to. It is a job number, and it works
    for the same reason job numbers have always worked.

SIGNING IN
    Happens once, by hand, at rehearsal - you type a code shown on screen.
    After that a token is cached on disk and every later run is silent. You
    never sign in during the session.

IF THE ORGANISATION'S MAIL WILL NOT COOPERATE
    The very last lines of this file swap the whole leg out for Gmail. Same
    pipeline, same demonstration, no dependency on the tenant. Adapters again:
    change the messenger, not the process.
==============================================================================="""
import atexit
import os
import time
import requests
import msal

GRAPH = "https://graph.microsoft.com/v1.0"
SCOPES = ["Mail.Send", "Mail.Read"]
CACHE_FILE = os.path.join(os.path.dirname(__file__), ".msal_cache.json")


def _token():
    """Get permission to use the mailbox - from the cache if we already have it.

    First run: it prints a code, you type it into a browser once, and the
    result is saved to disk. Every run after that reads the cache and is
    completely silent. This is why nobody watches a sign-in during the demo.
    """
    cache = msal.SerializableTokenCache()
    if os.path.exists(CACHE_FILE):
        cache.deserialize(open(CACHE_FILE).read())
    atexit.register(lambda: open(CACHE_FILE, "w").write(cache.serialize())
                    if cache.has_state_changed else None)
    app = msal.PublicClientApplication(
        os.environ["MAIL_CLIENT_ID"],
        authority=f"https://login.microsoftonline.com/{os.environ['MAIL_TENANT']}",
        token_cache=cache,
    )
    accounts = app.get_accounts()
    result = app.acquire_token_silent(SCOPES, account=accounts[0]) if accounts else None
    if not result:
        flow = app.initiate_device_flow(scopes=SCOPES)
        print(flow["message"])  # one-time sign-in, done at rehearsal, never live
        result = app.acquire_token_by_device_flow(flow)
    if "access_token" not in result:
        raise RuntimeError(f"Mail sign-in failed: {result.get('error_description')}")
    open(CACHE_FILE, "w").write(cache.serialize())
    return result["access_token"]


def _headers():
    return {"Authorization": f"Bearer {_token()}"}


def send(subject, body_text, to=None):
    """Send one mail. Used by everything below.

    Note it goes TO the reviewer named in the .env file - not to whoever the
    pipeline feels like. Who gets asked is a configuration decision, made once,
    outside the code.
    """
    payload = {
        "message": {
            "subject": subject,
            "body": {"contentType": "Text", "content": body_text},
            "toRecipients": [{"emailAddress": {"address": to or os.environ["REVIEWER_EMAIL"]}}],
        },
        "saveToSentItems": True,
    }
    resp = requests.post(f"{GRAPH}/me/sendMail", headers=_headers(), json=payload)
    if resp.status_code != 202:
        raise RuntimeError(f"Graph sendMail said {resp.status_code}: {resp.text[:200]}")


def send_approval_request(story, review, escalated):
    """
    THE ASK. Everything the reviewer needs, in one message.

    Read the message this builds and notice there is nothing to go and find:

        - the verdict
        - every finding, quoting the rule it failed
        - the exact comment that will be posted, word for word
        - and, when the judge raised its hand, the reason in the first line,
          so the seriousness is visible before anything else is read

    Then one instruction: reply Approve, or reply Reject.

    That is the entire human interface. One word, from a phone.
    """
    marker = f"[SC-{story}]"
    head = ("ESCALATED — do not decide alone: " + review.get("escalate_reason", "") + "\n\n"
            if escalated else "")
    send(
        f"{marker} Review ready to post for STORY-{story}",
        head
        + f"Verdict: {review['verdict']}\n\n"
        + "Findings:\n" + ("\n".join(f"- {f}" for f in review["findings"]) or "- none") + "\n\n"
        + f"Drafted comment:\n{review['comment']}\n\n"
        + "Reply Approve to post, or Reject to hold.",
    )


def send_stall_alert(story, waiting_minutes):
    """
    THE ALARM. Sent when a review has been waiting past its clock.

    This is what makes "waiting" different from "lost". Nothing in this
    pipeline is allowed to sit silently forever - if a person has not answered,
    that becomes an event with a name on it, addressed to somebody.
    """
    send(
        f"[STALL] STORY-{story} review is waiting with no answer",
        f"The review for STORY-{story} has been waiting {waiting_minutes} minutes.\n"
        "Nothing was posted. Please answer the approval mail or look at the run history.",
    )


# Where a reply stops being the reviewer's words and starts being the quoted
# original. That matters: our own approval mail contains the sentence "Reply
# Approve to post, or Reject to hold" - so if we read the quoted part too, every
# Reject would look like an Approve.
QUOTE_MARKERS = ("sent from", "-----original", "________", "from:", "> ")


def answer_in(preview):
    """What the reviewer actually said: "approve", "reject", or None.

    None means "I could not read an answer in this" - NOT "no". The caller
    leaves the run parked and looks again on the next poll.

    That distinction is the whole point of this function. Treating an
    unreadable reply as a rejection would hold real work on the strength of a
    mail that had not finished indexing yet.
    """
    text = (preview or "")
    lowered = text.lower()
    cut = len(lowered)
    for marker in QUOTE_MARKERS:
        found = lowered.find(marker)
        if found != -1:
            cut = min(cut, found)
    head = lowered[:cut]
    if "approve" in head:
        return "approve"
    if "reject" in head:
        return "reject"
    return None


def poll_replies(since_iso):
    """
    LISTEN FOR THE ANSWER. Check the mailbox for replies to our approval mails.

    Returns a simple lookup: which story, and what the person said.

        {4512: "approve", 4488: "reject"}

    Three checks before an answer is accepted, and each one is a small piece of
    safety:

        1. The subject must carry our marker, [SC-nnnn] - so we know which
           parked run this is about.
        2. The subject must start with "Re" - it must be a REPLY to our ask,
           not a new mail that happens to mention a story.
        3. It must come from the named reviewer. Anyone can send mail to this
           address; not everyone can authorise a post.

    Anything failing those checks is ignored, silently and on purpose. An
    approval mechanism that accepts approvals from strangers is not one.
    """
    url = (f"{GRAPH}/me/messages?$filter=receivedDateTime ge {since_iso}"
           "&$orderby=receivedDateTime desc&$top=25&$select=subject,bodyPreview,from")
    resp = requests.get(url, headers=_headers())
    if resp.status_code != 200:
        raise RuntimeError(f"Graph list messages said {resp.status_code}: {resp.text[:200]}")
    answers = {}
    me = os.environ["REVIEWER_EMAIL"].lower()
    for message in resp.json().get("value", []):
        subject = message.get("subject") or ""
        if "[SC-" not in subject or not subject.lower().startswith("re"):
            continue
        sender = ((message.get("from") or {}).get("emailAddress") or {}).get("address", "")
        if sender.lower() != me:
            continue  # first answer wins, but only from the named reviewer
        story = int(subject.split("[SC-")[1].split("]")[0])
        answer = answer_in(message.get("bodyPreview"))
        if answer and story not in answers:  # newest first; keep the latest answer
            answers[story] = answer
        # No recognisable answer? Say nothing. The run stays parked, and the next
        # poll looks again - which is the safe direction to fail in.
    return answers


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# =============================================================================
#  THE ESCAPE HATCH
# =============================================================================
#
# Some organisations will not let an app like this touch their mail, and you
# find out at the worst possible moment. So the whole mail leg can be swapped
# for an ordinary Gmail account by changing one line in the .env file.
#
# Same pipeline, same gate, same demonstration - a different messenger. Which
# is the point of putting the messenger in its own file in the first place.
if os.environ.get("MAIL_BACKEND", "graph").lower() == "gmail":
    from mailer_gmail import (send, send_approval_request, send_stall_alert,  # noqa: F401,E402
                              poll_replies, now_iso)
