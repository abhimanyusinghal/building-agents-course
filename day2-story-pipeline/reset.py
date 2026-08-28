"""Reset the demo to its session-start state. Run before every rehearsal and delivery.

Restores seeded labels, deletes every comment the pipeline posted, closes issues that
were filed live from the phone (4501, 4520), and clears local run state (checkpoints,
ledger, runs.json). The repo afterwards looks exactly like seed.py left it.
"""
import sys
from pathlib import Path

# reset.py prints -> and is run between every rehearsal. Redirected to a file (or on a
# cp1252 console) the arrow raises UnicodeEncodeError *mid-loop*, leaving some issues
# reset and others not. Same one-line guard the runner already carries.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))

import requests  # noqa: E402
import gh        # noqa: E402

START_STATES = {4471: "new", 4488: "hold", 4495: "new", 4512: "hold"}
FILED_LIVE = {4501, 4520}


def main():
    for issue in gh.list_open_issues():
        key = gh.story_key(issue)
        number = issue["number"]
        gh.delete_pipeline_comments(number)
        if key in FILED_LIVE:
            requests.patch(f"{gh.API}/repos/{gh._repo()}/issues/{number}",
                           headers=gh._headers(), json={"state": "closed"})
            print(f"closed #{number} (STORY-{key} — filed live)")
        elif key in START_STATES:
            gh.set_state(number, START_STATES[key])
            print(f"#{number} STORY-{key} → state:{START_STATES[key]}, pipeline comments removed")
    # checkpoints.db brings two SQLite sidecars with it. Leave them behind and the
    # next run inherits a stale write-ahead log — so they go with the parent.
    # .msal_cache.json deliberately stays: it holds the mail sign-in, and losing
    # it means a device-code prompt in the middle of a session.
    locked = []
    for name in ("checkpoints.db", "checkpoints.db-wal", "checkpoints.db-shm",
                 "ledger.csv", "runs.json"):
        path = Path(__file__).with_name(name)
        if not path.exists():
            continue
        try:
            path.unlink()
            print(f"removed {name}")
        except PermissionError:
            # Almost always a watcher still holding the file open.
            locked.append(name)

    if locked:
        print()
        print("COULD NOT REMOVE: " + ", ".join(locked))
        print("Something still has these open — usually a `pipeline.py watch`")
        print("running in another terminal. Stop it with Ctrl+C and run reset again.")
        print()
        print("THE RESET IS INCOMPLETE. Labels and comments are done; local run")
        print("state is not. Do not start a rehearsal from here.")
        raise SystemExit(1)

    print("reset complete — the repo is at session start")


if __name__ == "__main__":
    main()
