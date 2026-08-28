As a support agent I want the case-note field to stop me at 4,000 characters so that my note is not silently truncated on save, which currently loses the last part of the note and has caused two escalations this quarter.

## Acceptance criteria

- Typing beyond 4,000 characters in the case-note field is prevented; the field stops accepting input and a counter shows 4000 / 4000.
- A note of exactly 4,000 characters saves and reloads identically, character for character.
- An existing note longer than 4,000 characters loads without error and is not altered until the agent edits it.
- The counter appears once the note passes 3,500 characters and not before.

## Dependencies

- case-web — the case-note field and counter.

## Non-functional

- The counter updates within 100 ms of a keystroke on the reference laptop spec.

## Data

No new personal data is read, stored or displayed. The note content is already held under the existing case retention period of 24 months.

## Rollback

Behind the caseNoteLimit configuration flag, default off.
