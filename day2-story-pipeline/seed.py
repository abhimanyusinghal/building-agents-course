"""Seed the demo repo: labels plus the story issues, in their session-start states.

Run once against a fresh repo. STORY-4501 and STORY-4520 are NOT seeded — they are
filed live from the phone during the session (their texts are in the presenter pack).
"""
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))

import gh  # noqa: E402

STORIES = Path(__file__).with_name("stories")

SEED = [
    # (number-in-title, title, session-start state)
    ("STORY-4471", "Show recent orders on the case screen", "new"),
    ("STORY-4488", "Cap case-note length at 4,000 characters", "hold"),   # spare / stall demo
    ("STORY-4495", "Export case list to CSV", "new"),
    ("STORY-4512", "Store card details for one-click reorder", "hold"),  # released in Chapter 3
]


def main():
    gh.ensure_labels()
    print("labels ready")
    existing = {i["title"] for i in gh.list_open_issues()}
    for key, title, state in SEED:
        full_title = f"{key} — {title}"
        if full_title in existing:
            print(f"skip (exists): {full_title}")
            continue
        body = (STORIES / f"{key}.md").read_text()
        issue = gh.create_issue(full_title, body, labels=[f"state:{state}"])
        print(f"created #{issue['number']}: {full_title}  [state:{state}]")


if __name__ == "__main__":
    main()
