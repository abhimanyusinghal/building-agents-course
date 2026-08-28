"""Gmail fallback for the mail leg — used only when MAIL_BACKEND=gmail in .env.

For tenants where the Graph app registration or consent is blocked. Same five
functions as mailer.py, same real round-trip: SMTP out, IMAP back in. Needs a
Gmail account with 2-Step Verification and an app password (16 characters).
"""
import calendar
import email
import imaplib
import os
import smtplib
import time
from email.message import EmailMessage
from email.utils import parsedate_to_datetime


def _creds():
    return os.environ["GMAIL_ADDRESS"], os.environ["GMAIL_APP_PASSWORD"]


def send(subject, body_text, to=None):
    address, password = _creds()
    message = EmailMessage()
    message["From"] = address
    message["To"] = to or os.environ.get("REVIEWER_EMAIL", address)
    message["Subject"] = subject
    message.set_content(body_text)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(address, password)
        smtp.send_message(message)


def send_approval_request(story, review, escalated):
    head = ("ESCALATED — do not decide alone: " + review.get("escalate_reason", "") + "\n\n"
            if escalated else "")
    send(
        f"[SC-{story}] Review ready to post for STORY-{story}",
        head
        + f"Verdict: {review['verdict']}\n\n"
        + "Findings:\n" + ("\n".join(f"- {f}" for f in review["findings"]) or "- none") + "\n\n"
        + f"Drafted comment:\n{review['comment']}\n\n"
        + "Reply Approve to post, or Reject to hold.",
    )


def send_stall_alert(story, waiting_minutes):
    send(
        f"[STALL] STORY-{story} review is waiting with no answer",
        f"The review for STORY-{story} has been waiting {waiting_minutes} minutes.\n"
        "Nothing was posted. Please answer the approval mail or look at the run history.",
    )


def poll_replies(since_iso):
    """Replies since since_iso whose subject carries an [SC-n] marker."""
    address, password = _creds()
    # since_iso is UTC, so it must be read as UTC. time.mktime() would read it as local
    # time and slide the window by the machine's offset — in India that opens the window
    # 5.5 hours in the past and a rehearsal's "Approve" resumes a run you have not asked
    # about yet; west of UTC it puts the floor in the future and no reply ever matches.
    floor = calendar.timegm(time.strptime(since_iso, "%Y-%m-%dT%H:%M:%SZ"))
    answers = {}
    with imaplib.IMAP4_SSL("imap.gmail.com", 993) as imap:
        imap.login(address, password)
        imap.select("INBOX")
        day = time.strftime("%d-%b-%Y", time.gmtime(floor))
        _, data = imap.search(None, f'(SINCE "{day}" SUBJECT "[SC-")')
        ids = data[0].split()
        for message_id in reversed(ids[-25:]):
            _, parts = imap.fetch(message_id, "(RFC822)")
            message = email.message_from_bytes(parts[0][1])
            received = parsedate_to_datetime(message["Date"]).timestamp()
            subject = message.get("Subject", "")
            if received < floor or "[SC-" not in subject or not subject.lower().startswith("re"):
                continue
            story = int(subject.split("[SC-")[1].split("]")[0])
            if story in answers:
                continue
            body = ""
            if message.is_multipart():
                for part in message.walk():
                    if part.get_content_type() == "text/plain":
                        body = part.get_payload(decode=True).decode(errors="ignore")
                        break
            else:
                body = message.get_payload(decode=True).decode(errors="ignore")
            first_line = body.strip().splitlines()[0].lower() if body.strip() else ""
            # Same rule as the Graph backend: only an explicit word counts.
            # Anything we cannot read leaves the run parked, never rejected.
            answer = ("approve" if "approve" in first_line
                      else "reject" if "reject" in first_line else None)
            if answer:
                answers[story] = answer
    return answers


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
