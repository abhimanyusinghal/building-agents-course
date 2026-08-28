# Lab 1 — Build a Working Agent From Nothing (GitHub Copilot in VS Code)

This lab builds one small, real agent — **Story Check** — that reads a user story, judges it against
your team's Definition of Ready, and writes the refinement comment back to the repository.

You will build it in the order the pieces actually matter: instructions first, then grounding, then
tools, then the approval gate, then a second surface. Exactly one thing changes per part, so when the
behaviour changes you know precisely what changed it.

**You need no prior experience with GitHub Copilot.** Part 0 takes you from "no account" to "chat
window open".

> **Everything in this document is meant to be copy-pasted.** There are no setup scripts. You create
> every file by hand, at the moment the lab needs it — the *order* in which files appear is part of
> the lesson, not an accident of packaging.

---

## Prerequisites

Install these before you start. Each line has the command that proves it worked.

| Requirement | Check it |
|---|---|
| A GitHub account (free is fine) | You can sign in at [github.com](https://github.com) |
| Visual Studio Code, current version | `code --version` |
| Node.js 22 or newer (needed in Part 8) | `node --version` |
| Python 3.10 or newer, with pip (needed in Part 5) | `python3 --version && python3 -m pip --version` (macOS/Linux) or `py --version; py -m pip --version` (PowerShell) |
| Git (needed in Part 7) | `git --version` |
| About 90 minutes, and no auto-approve settings left on from a previous session | — |

You do **not** need to know Python. You will paste one short Python file and change two strings in it.

---

## Learning Objectives

### Core

- Create a custom agent in VS Code as a file, and explain why the file *is* the agent
- Show the difference between an ungrounded answer and a grounded one, using the same model and the
  same question
- Distinguish **presence** (a file is in the folder) from **wiring** (an instruction points at it)
- Connect an MCP tool server to the agent, and read the trust dialog for what it is
- Change which tool an agent picks without touching the model or lengthening the prompt
- Recognise a silent grounding failure — the kind that produces no error at all

### Advanced

- Predict which of the agent's five fields — instructions, grounding, tools, model, approvals — you
  must change to fix a given failure
- Explain why a tool description is a prompt, not documentation
- Explain why an agent travels between surfaces but its reach does not
- Design an instruction that survives a missing tool instead of hallucinating around it

---

## Part 0: Get GitHub Copilot Working

### 0.1 Sign up

1. Create a GitHub account at [github.com/signup](https://github.com/signup) if you do not have one.
2. Open VS Code.
3. Click the **account icon** at the bottom of the Activity Bar (left edge) → **Sign in with GitHub**.
   A browser window opens; approve the request and return to VS Code.
4. Look at the Status Bar (bottom right) for the **Copilot icon**. Hover it and choose
   **Use AI Features** if prompted. If you have no paid plan, this enrols you in **Copilot Free** —
   no credit card, no trial expiry.

> **A word on plans.** Copilot Free includes a limited monthly allowance of chat requests. This lab
> makes roughly fifteen chat requests. If you are doing the lab alongside other work that day, or if
> your first run tells you that you are out of requests, start a **Copilot Pro** free trial at
> [github.com/features/copilot/plans](https://github.com/features/copilot/plans) — it is the
> comfortable path for a workshop.

### 0.2 Open the chat view

Press `Ctrl+Alt+I` (Windows/Linux) or `Cmd+Ctrl+I` (Mac), or click the Copilot icon in the title bar.

**You should see:** a chat panel, with a **mode/agent dropdown** at the top or bottom of the input
box showing something like *Ask*, *Edit*, *Agent*.

### 0.3 Verify the two features this lab depends on

Open the Command Palette — `Ctrl+Shift+P` (`Cmd+Shift+P` on Mac) — and type each of these. You are
only checking that the command exists.

```
Chat: New Custom Agent
```

```
MCP: List Servers
```

If either command is missing, your Copilot plan or your organisation's policy has that feature
switched off. Find that out now, not in Part 5 — ask whoever administers your GitHub organisation, or
use a personal GitHub account for the lab.

### 0.4 Prepare deterministic approval prompts

Part 7 depends on seeing the actual command before it runs. Note your current values for the two
settings below so you can restore them after the lab, then:

1. In the chat input's permission picker, choose **Default Approvals**.
2. Open Settings (`Ctrl+,`), search for `chat.tools.global.autoApprove`, and set it to **false**.
3. Search for `chat.tools.terminal.enableAutoApprove`, and set it to **false**. VS Code normally
   auto-approves some safe terminal commands, so this temporary setting makes every terminal command
   ask during the exercise.
4. Open the Command Palette and run `Chat: Reset Tool Confirmations` to clear saved approvals from
   earlier sessions.

These are the current controls documented in
[VS Code approvals and permissions](https://code.visualstudio.com/docs/agents/run/approvals).

### 0.5 Install the Copilot CLI (used in Part 8 only)

In any terminal:

```
npm install -g @github/copilot
```

Then run it once from an empty folder you trust — not from your home directory — and sign in:

```
copilot
```

When it asks about folder trust, choose trust for **this session only**.

At its prompt, type:

```
/login
```

Follow the browser flow, then type `/exit`. You can do this later, but doing it now means Part 8 does
not stall.

---

## Part 1: Build the Workspace

The agent can read everything in the folder you open. So what is in the folder is a decision, and we
make it deliberately, one file at a time.

### 1.1 Create the folders

Create a folder called `story-check` anywhere convenient (Desktop is fine). Open it in VS Code:
**File → Open Folder…** → select `story-check`.

> **Open `story-check` itself, not its parent.** The folder you open is the agent's world.

In the Explorer pane, use the **New Folder** button to create exactly two folders inside it:

```
intake
reviews
```

Your workspace is now:

```
story-check/
  intake/
  reviews/
```

Nothing else. No standards folder. That is deliberate, and you will see why in Part 2.

### 1.2 Add the two stories

Create `intake/STORY-4471.md` (Explorer → **New File**) and paste this:

```markdown
# STORY-4471 — Show recent orders on the case screen

**Status:** Refinement
**Raised by:** customer support intake
**Sprint:** unassigned

## Story

As a support agent I want to see a customer's recent orders on the case screen so that
I do not have to switch systems while the customer is on the phone.

## Notes

Agents currently open the orders system in a second tab and search by email address.
It takes a while and they lose the case context. We would pull from the orders service.

## Acceptance criteria

- Recent orders are shown on the case screen.
- Performance should be reasonable.
- Only appropriate customer data is displayed.
- The panel is user-friendly.

## Dependencies

- `case-web` — the case-screen panel.
- The orders system.
```

Create `intake/STORY-4488.md` and paste this:

```markdown
# STORY-4488 — Cap case-note length at 4,000 characters

**Status:** Refinement
**Raised by:** support operations
**Sprint:** unassigned
**Estimate:** 3 points (r.iyer, d.oyelaran)

## Story

As a support agent I want the case-note field to stop me at 4,000 characters so that my
note is not silently truncated on save, which currently loses the last part of the note
and has caused two escalations this quarter.

## Acceptance criteria

- Typing beyond 4,000 characters in the case-note field is prevented; the field stops
  accepting input and a counter shows `4000 / 4000`.
- A note of exactly 4,000 characters saves and reloads identically, character for
  character.
- An existing note longer than 4,000 characters loads without error and is not altered
  until the agent edits it.
- The counter appears once the note passes 3,500 characters and not before.

## Dependencies

- `case-web` — the case-note field and counter.

## Non-functional

- The counter updates within 100 ms of a keystroke on the reference laptop spec.

## Data

No new personal data is read, stored or displayed. The note content is already held
under the existing case retention period of 24 months.

## Rollback

Behind the `caseNoteLimit` configuration flag, default off.
```

### 1.3 Put the folder under Git

Open a terminal inside VS Code — **Terminal → New Terminal** — and confirm the prompt shows the
`story-check` folder. Then run:

```
git init
```

```
git add -A
```

```
git commit -m "stage 0: two stories"
```

If the commit fails because Git does not know who you are, set the identity once:

```
git config user.email "you@example.com"
```

```
git config user.name "Your Name"
```

Then explicitly rerun the commit that failed:

```
git commit -m "stage 0: two stories"
```

Part 7 needs a repository to commit into. This is that repository.

**You should see** — Explorer showing exactly two files under `intake/`, an empty `reviews/`, and a
clean `git status`.

> ⚠️ **Do not create a `standards/` folder yet.** Do not paste the Definition of Ready anywhere. The
> agent searches this folder on its own — if the standard is present in Part 2, the agent finds it
> unprompted and the whole first lesson evaporates.

---

## Part 2: An Agent From Nothing

### 2.1 Create the agent file

A custom agent in VS Code is one Markdown file with YAML frontmatter, living at
`.github/agents/<name>.agent.md`. That is the entire mechanism.

In the Explorer, create the folders `.github` and then `agents` inside it, then the file
`.github/agents/story-check.agent.md`, and paste exactly this:

```markdown
---
name: Story Check
description: Checks a user story against the team Definition of Ready
---

Check a single user story against the team's Definition of Ready, say whether it is
ready to be picked up, and if it is not, list exactly what is missing.
```

Save it.

That is the whole agent. Frontmatter names it; the body is its instructions. There is no other
screen, no console, no deployment.

> **Aside — the Command Palette route.** `Chat: New Custom Agent` creates this same file for you,
> with a template body. It is worth knowing, but different Copilot builds behave differently there,
> and one of them writes the body for you by reading your folder. Pasting the file gives everyone in
> the room the identical starting point, which is what this lab needs.

### 2.2 Select the agent

In the chat input, open the **agent dropdown** and choose **Story Check**.

**Not in the list?** Check the path is exactly `.github/agents/story-check.agent.md` and the extension
is `.agent.md`, not `.md`. Then run `Developer: Reload Window` from the Command Palette.

### 2.3 Ask it the question

Paste this into chat and send it:

```
Is STORY-4471 ready to pick up?
```

**You should see:** a fluent, confident, entirely generic verdict. It will talk about acceptance
criteria and vagueness. It will sound right.

Now do the thing most people skip. **Open the reference list on the reply** — the collapsed
"Used N references" / file list at the top or bottom of the answer.

It read `intake/STORY-4471.md`. Nothing else. There was nothing else to read.

### 2.4 The question to sit with

Your team's Definition of Ready has **seven** numbered criteria.

Before reading on: how many of them did that answer check?

None of them. It could not have — the standard is not in this folder. It judged the story against
*a* definition of ready, the general one, learned from everywhere. And nothing in the wording of the
reply tells you that.

> **This is the failure mode you will meet most often in production.** Not a wrong answer. A
> plausible answer to a question you did not ask, delivered in the same tone as a correct one.

---

## Part 3: Grounding — the File, Then the Line

Two moves, in this order. The order is the lesson.

### 3.1 First, the file

Create the folder `standards/`, then the file `standards/definition-of-ready.md`, and paste this:

```markdown
# Definition of Ready

A story is Ready when a team member who was not in refinement could pick it up and
start work without asking a question. Refinement checks all seven. A story that fails
any one of them is not Ready, and the missing item is named in the refinement comment.

## 1. Problem statement

States who has the problem, what they cannot do today, and why it matters now.
"As a … I want … so that …" is acceptable but the *so that* has to name a real
consequence, not restate the want.

## 2. Acceptance criteria

Every behaviour described in the story has at least one acceptance criterion that can
be observed and tested by somebody other than the author.

A criterion is **not** testable if it relies on any of: *appropriate, reasonable,
sensible, user-friendly, performant, as needed, where relevant, properly, correctly
handled*. These words move the judgement to whoever tests it, which is exactly the
argument the criterion was supposed to settle.

## 3. Dependencies

Every system the story reads from or writes to is named, using the component name from
the service catalogue. "The orders system" is not a component name; `orders-api` is.

## 4. Non-functional expectations

Where the story touches a user-facing screen or a shared service, at least one number:
a response-time target, an expected volume, or a retention period. A number that turns
out to be wrong is still better than no number, because it can be argued with.

## 5. Data

If the story causes personal data to be read, stored, or displayed, the categories of
data are listed and a retention period is stated. Order history, contact details and
payment metadata all count as personal data here.

## 6. Sizing

Estimated by at least two people, and no larger than one sprint. A story nobody will
size is a story nobody understands.

## 7. Rollback

If the change is visible to a user, the story says how it is turned off — a flag, a
configuration value, or a documented revert. "Redeploy the previous version" is only
acceptable where there is no data migration.
```

Save it.

**Notice what has not happened.** The agent file is untouched. Nothing connects the agent to this
file except the chance that a search stumbles across it. Hope is not wiring.

### 3.2 Then, the line

Open `.github/agents/story-check.agent.md` and **append** this single line to the body:

```
Judge only against standards/definition-of-ready.md, and quote the criterion number for every finding.
```

Save. The file now reads:

```markdown
---
name: Story Check
description: Checks a user story against the team Definition of Ready
---

Check a single user story against the team's Definition of Ready, say whether it is
ready to be picked up, and if it is not, list exactly what is missing.

Judge only against standards/definition-of-ready.md, and quote the criterion number for every finding.
```

### 3.3 Ask again — the same question, word for word

Start a new chat and select **Story Check** again so this run loads the updated agent file. Then ask:

```
Is STORY-4471 ready to pick up?
```

**You should see:** a verdict that cites criterion numbers, and quotes the actual offending words from
the story — `reasonable`, `appropriate`, `user-friendly`. Open the reference list: it now shows the
story **and** the standard.

### 3.4 The diagnosis lives in the gap

Scroll back so both answers are on screen. Read the two reference lists against each other.

Same model. Same question. Same wording. One file, and one line pointing at it.

> **Grounding is not training.** Nothing about the model changed. The instruction caused a file to be
> retrieved into this run's context — and it will do that again on the next run, and every run. That
> guarantee is what the line buys you. Without it, the file was merely *nearby*.

---

## Part 4: The Rest of the Instructions

A one-sentence agent proved the point. A working agent needs a response format and guardrails.

Replace the **entire contents** of `.github/agents/story-check.agent.md` with this:

```markdown
---
name: Story Check
description: Checks one user story against the team Definition of Ready and drafts the refinement comment
---

# Story Check

You check a single user story against the team's Definition of Ready and draft the
comment that goes back to the author. You do not edit the story, and you do not decide
whether it is picked up.

## Constraints

- Judge the story only against `standards/definition-of-ready.md`. If a rule is not in
  that file, it is not a rule. Read that file before you form a verdict — do not answer
  from memory of what a definition of ready usually contains.
- Quote the criterion number for every finding. A finding with no number is not a
  finding.
- Report a possible overlap with another story as a possibility; do not assert a
  duplicate.
- Never call a story ready if any acceptance criterion cannot be observed and tested by
  somebody other than the author.

## Response format

Three sections, in this order, and nothing else:

1. **Verdict** — `Ready` or `Not ready`, then one sentence.
2. **What is missing** — one bullet per failed criterion, each starting with the
   criterion number, then what is missing, then the exact words in the story that
   caused it to fail.
3. **Suggested comment** — the text to paste into the story, addressed to the author,
   under 120 words, specific enough to act on without a meeting.

## Guidance

- When asked to write the review, write it to `reviews/<STORY-ID>.md`. Do not modify
  anything under `intake/`.
- If a tool named in these instructions is not available where you are running, say so
  in one line of the review and continue without that information. Do not reconstruct
  what the tool would have returned by reading files under `tools/` or by running
  scripts.
- Stop after writing the file. Do not commit, do not push, and do not move the story.
```

Save.

Read the **Guidance** section again. The second bullet is the interesting one: it tells the agent what
to do when a tool it was promised is *not there*. Most agents, in that situation, improvise. You will
watch this one try, in Part 8.

---

## Part 5: Tools — The Wrong One, Then the Right One

Everything so far was files the agent could read. Tools are different: they are functions the agent
can *call*, presenting data through an advertised interface instead of an ordinary grounding file.

### 5.1 Create the tool server

Create the folder `tools/`, then the file `tools/workitem_server.py`, and paste this:

```python
# A deliberately badly-described MCP server.
# Two tools over embedded demo tables. In production, these would usually be external.
#
# Requires:  python3 -m pip install "mcp>=2,<3" (macOS/Linux)
#            py -m pip install "mcp>=2,<3" (Windows)
from mcp.server import MCPServer

mcp = MCPServer("workitem")

OWNERS = """orders-api,Commerce Platform,p.nair,commerce-oncall
case-web,Service Experience,r.iyer,svc-oncall
identity-gateway,Platform Security,a.singh,sec-oncall
fx-rates,Commerce Platform,l.mendes,commerce-oncall
notifications,Service Experience,d.oyelaran,svc-oncall
billing-core,Revenue Systems,m.haddad,revenue-oncall"""

BACKLOG = """STORY-4102 | Show the last five orders in the case sidebar | Open, unrefined | case-web
STORY-4188 | Add an order-lookup link to the case header | Open, in sprint 34 | case-web
STORY-4310 | Retire the standalone order-search tab | Blocked on STORY-4102 | case-web
STORY-4471 | Show recent orders on the case screen | Refinement | case-web
STORY-4488 | Cap case-note length at 4,000 characters | Refinement | case-web
STORY-4501 | Rate-limit the orders lookup endpoint | Open, unrefined | orders-api
STORY-4522 | Move FX rate refresh off the nightly job | Open, unrefined | fx-rates"""


@mcp.tool()
def search_backlog(query: str) -> str:
    """Searches items."""
    q = query.lower()
    hits = [r for r in BACKLOG.splitlines() if q in r.lower()]
    return "\n".join(hits) if hits else "NO MATCH"


@mcp.tool()
def search_owners(query: str) -> str:
    """Searches items and returns information."""
    q = query.lower()
    hits = [r for r in OWNERS.splitlines() if q in r.lower()]
    if not hits:
        return "NOT IN CATALOGUE"
    out = []
    for r in hits:
        c, team, lead, rota = r.split(",")
        out.append(f"component={c} owning_team={team} tech_lead={lead} on_call={rota}")
    return "\n".join(out)


if __name__ == "__main__":
    mcp.run()
```

Install the one dependency in the VS Code terminal, using the same Python launcher you will configure
for the server:

**macOS / Linux:**

```
python3 -m pip install "mcp>=2,<3"
```

**Windows (PowerShell):**

```
py -m pip install "mcp>=2,<3"
```

The version range keeps this lab on the MCP Python SDK 2.x API used by the file above. Plain `mcp`
is enough; the optional CLI extra is not needed. The server shape follows the
[official SDK run guide](https://py.sdk.modelcontextprotocol.io/run/).

Read the two docstrings out loud: *"Searches items."* and *"Searches items and returns information."*

Those are not jokes. That is what tool descriptions look like in the wild, because the author knows
what the tool does and cannot imagine not knowing.

### 5.2 Wire the server to the editor

Create the folder `.vscode/`, then the file `.vscode/mcp.json`, and paste this:

```json
{
  "servers": {
    "workitem": {
      "type": "stdio",
      "command": "python3",
      "args": ["${workspaceFolder}/tools/workitem_server.py"]
    }
  }
}
```

> **Windows:** use `"command": "py"` so the server runs with the interpreter where you installed
> `mcp`.

`.vscode/mcp.json` is a VS Code workspace setting. VS Code can forward compatible servers to its
Agent Host, but another program such as Copilot CLI does not read this editor file directly. For MCP
wiring intended to be portable across those surfaces, use repository-root `.mcp.json`; Exercise 5
does that deliberately. See the
[current MCP configuration reference](https://code.visualstudio.com/docs/agents/reference/mcp-configuration).

### 5.3 Start it, and read the gate

Command Palette → `MCP: List Servers` → **workitem** → **Start**.

A **trust dialog** appears. Do not click through it silently. Read it.

> The editor will not run code you just added to the folder without a person saying yes, once, by
> name. That is a gate. Remember it exists — one day a colleague will tell you their MCP server
> "does not work", and it will be sitting behind this dialog.

Approve it.

**If `workitem` is not listed:** open `.vscode/mcp.json` and save it once — the editor re-reads it.
**If it fails to start:** open the MCP output channel from `MCP: List Servers`. Nearly always
the matching install command was missed, or the configured launcher does not match the one used for
installation.

### 5.4 See what the agent sees

Start a new chat and select **Story Check** again so this run loads the complete Part 4 agent file.
In the chat input, click **Configure Tools** (the tools/wrench control). Find the two `workitem` tools
and read what is written next to them.

For tool selection, the model sees each advertised name, input schema, and description. It cannot
safely try a tool and undo the call; it picks a door by reading the sign.

### 5.5 The question that forces a choice

With **Story Check** still selected, paste:

```
Is STORY-4471 ready to pick up, and which team would own the work?
```

Watch the tool calls appear in the log, and **expand them**. Read the call and the result.

The likely outcome: it reaches for `search_backlog` with `case-web` and gets matching story rows —
valid backlog data that does not answer who owns the component. Two tools called "search something",
and it took the wrong one because the descriptions did not make their jobs distinct.

> **If it picks the right tool first time:** that happens, roughly as often as not. Do not re-run
> hoping for failure. Instead ask yourself: *how could I have known in advance that it would?* You
> could not. Same question, two runs, two routes — that is what non-deterministic means, and it is
> why you cannot test one of these by replaying an expected sequence. Then break it deliberately:
> rename `search_owners` to `tool_1`, set its docstring to `"Searches."`, restart the server, and ask
> again. That usually makes the wrong route easier to observe, and it is the truer example — that is
> what tools are called when nobody names them. If it still selects `tool_1`, record that result and
> continue; names and descriptions shift a model's odds, not guarantee a trace. Restore the function
> name to `search_owners` and its docstring to `"Searches items and returns information."` before
> continuing. Part 5.7 will restart the server after you apply the real fix.

### 5.6 The fix — three strings

Before you touch anything, say the promise out loud: **you will not change the model, and you will
not lengthen the prompt.**

**String one.** In `tools/workitem_server.py`, rename the function `search_owners` to:

```
get_component_owner
```

**String two.** Replace that function's docstring with:

```
Returns the owning team, tech lead and on-call rota for one named component, such as
orders-api or case-web. Use this whenever a story names a component and you need to say
who would do the work. Do not use it to find stories or to search the backlog.
```

The function should now begin:

```python
@mcp.tool()
def get_component_owner(query: str) -> str:
    """Returns the owning team, tech lead and on-call rota for one named
    component, such as orders-api or case-web. Use this whenever a story
    names a component and you need to say who would do the work. Do not
    use it to find stories or to search the backlog."""
```

**String three.** Append this to the **Constraints** section of
`.github/agents/story-check.agent.md`:

```
- When a story names a component, call get_component_owner with that component name
  before you write the verdict, and name the owning team in the review. Use
  get_component_owner only for components. Use search_backlog only when you are
  looking for other stories that might overlap.
```

Save both files.

### 5.7 Restart and re-ask

Command Palette → `MCP: List Servers` → **workitem** → **Restart**.

Start a new chat, select **Story Check** again, then open **Configure Tools** and confirm the new name
and description are showing. The new chat reloads the edited agent profile; restarting the server
reloads the edited tool metadata.

Now ask the **same question, unchanged**:

```
Is STORY-4471 ready to pick up, and which team would own the work?
```

**You should see:** `get_component_owner` called with `case-web`, and the answer naming **Service
Experience** and **r.iyer** — values returned through the ownership tool.

Three strings. A tool's name, its description, and one instruction naming it. Nothing about the
model. Nothing added to your prompt.

> `search_backlog` still has its terrible description. Leave it. Fixing the second tool is Exercise 2.

---

## Part 6: Grounding That Fails Silently

> ⚠️ **You are about to create the conventions file for the first time.** If you created it earlier,
> delete it and start this part fresh — the whole point is to see the run *before* and *after*.

### 6.1 Add house conventions

Create `.github/instructions/story-review.instructions.md` and paste this:

```markdown
---
name: Story review conventions
description: House conventions for anything written under reviews/
applyTo: 'reviews/**/*.md,intake/**/*.md'
---

# Story review conventions

- Refer to criteria as `DoR-1` through `DoR-7`, matching the numbered sections of
  `standards/definition-of-ready.md`.
- Quote the offending words from the story in backticks. Do not paraphrase them — the
  author needs to find the phrase they wrote.
- Name people by their handle (r.iyer, p.nair), never by full name.
- Do not propose the wording of an acceptance criterion the author has not attempted.
  Say what is untestable about theirs and what a testable one would have to state.
- No praise, no filler openings. The first line is the verdict.
```

Look at the `applyTo:` line. That glob is the deterministic attachment mechanism. Current VS Code
can also select an instructions file when its `description` semantically matches the task, so Part
6.3 disables both routes. This file is not mentioned in your agent file or prompt. See the
[current custom-instructions documentation](https://code.visualstudio.com/docs/agent-customization/custom-instructions).

### 6.2 The full run

Start a new chat and select **Story Check** so this run discovers the new conventions file. Then ask:

```
Check STORY-4471 against our Definition of Ready and write the review.
```

Approve the file write when asked.

Open `reviews/STORY-4471.md`. Look for three fingerprints:

1. Criteria written as `DoR-1` … `DoR-7`
2. The offending words from the story in backticks
3. Handles, not full names

Those three habits came from a file nobody mentioned, deterministically matched to the reviews
folder by one glob.

### 6.3 The experiment — break it silently

1. Open `.github/instructions/story-review.instructions.md`.
2. Delete the `description:` line so semantic matching cannot select the file.
3. Change `applyTo:` to `applyTo: 'docs/**/*.md'`, a glob that matches nothing in this task. Save.
4. Delete `reviews/STORY-4471.md`.
5. Start a new chat, select **Story Check**, and run the same prompt again, unchanged.

**You should see:** a correct review — and the house style gone.

No error. No warning. Nothing changed colour. The file is still there, still valid Markdown, still
reviewed by somebody, and doing nothing at all.

> **This is the grounding failure you will actually meet.** Not a crash. A file that quietly stopped
> applying, in a system whose output always looks confident.

Put both attachment fields back, exactly:

```
description: House conventions for anything written under reviews/
applyTo: 'reviews/**/*.md,intake/**/*.md'
```

Delete `reviews/STORY-4471.md`, start another new chat, select **Story Check**, and run the prompt
once more so you finish this part with a correctly-styled review on disk. Starting new chats keeps
the before/after runs from inheriting style cues or cached customization state from one another.

---

## Part 7: The Approval Gate

Your Guidance says **do not commit**. Now you are going to ask anyway and watch which layer actually
stops execution.

### 7.1 Checkpoint the setup

Run these two commands yourself so the later review commit cannot include the setup files:

```
git add .github/agents/story-check.agent.md .github/instructions/story-review.instructions.md .vscode/mcp.json standards/definition-of-ready.md tools/workitem_server.py
git commit -m "build story-check agent"
```

The generated review remains uncommitted. That is all the Git setup this exercise needs.

### 7.2 Ask for the review commit

Ask it to commit:

```
Commit that review with the message "story-check: STORY-4471".
```

A dialog will usually appear. **Do not click yet.**

If the agent instead refuses because its Guidance says not to commit, that is also a win: the
instruction shaped this run. Ask it to `Create an empty file at reviews/approval-check.tmp, then
stop.` That harmless write gives you a gate to inspect; deny it after the inspection and skip the
commit-specific sentence below.

For the commit branch, check one thing before anything runs: the proposed command must stage only
`reviews/STORY-4471.md`. Reject `git add -A`, `git add .`, or any broad path. Then read the scopes
slowly. There is usually something like: allow once · allow for this session · allow for this
workspace · always allow. Land on the last one so you can see the standing grant.

> There is the standing grant — one click away, styled like a convenience. Every "why did the agent
> do that?" incident review you will ever read has one of these in it, clicked eight weeks earlier by
> somebody who was in a hurry.

On the commit branch, click **Allow once**. The agent file said *do not commit*; the request happened
anyway, and the dialog still controlled whether the command could execute. On the refusal branch,
the instruction was honoured this run — but the harmless write still met the same client gate.

> **Instructions shape behaviour; gates enforce reach.** A sentence in the agent file influences
> what the model attempts. The approval dialog is the repeatable control over what actually runs.

---

## Part 8: A Second Surface — the Terminal

You are going to run **the same agent profile** from a completely different program, having rebuilt
nothing. Both surfaces read the same `.github/agents/story-check.agent.md` file.

In the VS Code terminal (confirm you are inside `story-check/`):

```
copilot
```

Copilot CLI asks whether you trust this folder. Read the scope, then choose trust for **this session
only**. Folder trust is separate from the editor's trust and from later per-tool approvals.

At its prompt, enter `/agent`, select **Story Check**, and then paste:

```
Check STORY-4488 against our Definition of Ready and write the review.
```

This is the documented interactive custom-agent flow; `--agent` is the programmatic form when it is
paired with `--prompt`. See GitHub's
[Copilot CLI custom-agent documentation](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/create-custom-agents-for-cli).

The review write should request approval. One additional request may appear, and the two get
**opposite answers**:

- **A request to write `reviews/STORY-4488.md`** — approve it. Same idea as the VS Code dialog, in
  different clothes.
- **If it requests a shell command that reads `tools/workitem_server.py`** — **deny it**, and
  understand why it asked. A compliant run can instead follow the Guidance immediately, report that
  the tool is unavailable, and never make this request; that is also correct.

The instructions name `get_component_owner`. On this surface that tool does not exist — the MCP
server was wired to the *editor*, not to the CLI. If the agent tries to improvise, the ownership table
is sitting in the repository as readable source code and it may ask to inspect it with a shell
command. The advertised MCP tool schema is absent even though a separate filesystem route to its
implementation remains in reach.

Deny that workaround if it appears. Facts come from the tool, or they are not in the review. The
Guidance states that policy; the approval prompt can enforce it when the agent proposes a command
anyway.

Open `reviews/STORY-4488.md`. Same standard, same conventions, a much stronger story.

**Expect a verdict of `Ready`** — but a strict run may come back **`Not ready`**, usually on DoR-3
(the story names `case-web` but its criteria also cover saving and reloading notes) or DoR-5 (it
states a retention period without listing the personal-data categories). **Both outcomes are
correct.** You are not verifying the verdict here; you are verifying that the *same standard* and the
*same conventions* produced it — `DoR-N` numbering, backticked quotes, handles not names.

If the review contains a line saying the owning team could not be determined, that is the Guidance
bullet from Part 4 doing its job — the agent said what it did not know instead of inventing it.

Type `/exit` to leave.

### What just travelled, and what did not

| Field | Travelled to the terminal? | Why |
|---|---|---|
| Instructions | Yes | `.github/agents/story-check.agent.md` is in the repo |
| Grounding (standard, conventions) | Yes | Files in the repo |
| Tools | **No** | The MCP server was wired in `.vscode/mcp.json`, an editor-specific file that Copilot CLI does not read directly |
| Approvals | Different | The CLI has its own prompts, its own scopes, its own memory of them |
| Model | Different defaults | Each surface picks its own |

> You rebuilt nothing. The terminal read the same files, because the agent **is** the files. The
> agent travelled; its reach did not.

---

## Exercises

### Exercise 1 — Count the criteria

Take the Part 2 answer (ungrounded) and the Part 3 answer (grounded). For each, count how many of the
seven DoR criteria were actually evaluated.

**Expected finding:** the ungrounded answer evaluates a general notion of readiness and cites nothing
numbered. The grounded answer reports findings against most or all seven — commonly six failures on
STORY-4471: untestable words (DoR-2), a vague dependency (DoR-3), no number (DoR-4), unstated personal
data (DoR-5), no sizing (DoR-6), no rollback (DoR-7). That is the standard doing work, not the agent
getting cleverer.

### Exercise 2 — Fix the second tool by eye

`search_backlog` is already a useful name, but its docstring still says *"Searches items."* Keep the
name and replace only its docstring with:

```
Returns backlog stories matching a component or phrase. Use this to find other stories
that might overlap. Do not use it to identify a component owner.
```

Restart the server, start a new chat, reselect **Story Check**, and ask:

```
Is anything else in the backlog overlapping with STORY-4471?
```

**Expected finding:** with a description that says "finds other stories", the agent reaches for it
directly and surfaces STORY-4102, STORY-4188 and STORY-4310 — and, because of the agent file's
constraint, reports them as *possible* overlaps rather than asserting duplicates.

### Exercise 3 — Break the grounding pointer

In your agent file, change the path in the Constraints section from
`standards/definition-of-ready.md` to `standards/dor.md` (a file that does not exist). Save. Ask the
Part 2 question again.

**Expected finding:** you get an answer. A confident one. The reference list is your only evidence
that it never read the standard. Write down, in one sentence, what monitoring would have caught this
in production. Restore the path to `standards/definition-of-ready.md` before the next exercise.

### Exercise 4 — Which field would you change?

For each symptom, name which of the five fields you would change: **instructions, grounding, tools,
model, approvals**.

| Symptom | Field? |
|---|---|
| The review names a team that does not exist in any table | |
| The review is correct but written as an essay, not three sections | |
| The agent edited `intake/STORY-4471.md` | |
| The agent calls two tools for a one-tool question | |
| The agent pushed to a remote branch | |

**Answers:** tools (it needs a tool call, and an instruction to make it); instructions (response
format); instructions first, then a narrower tool list; tools (descriptions); approvals — an
instruction is not enough, as Part 7 showed.

### Exercise 5 — Make MCP wiring portable to the CLI

The Part 8 run could not name the owning team because `.vscode/mcp.json` is editor-specific. Move the
server definition to `.mcp.json` at the repository root:

```json
{
  "mcpServers": {
    "workitem": {
      "type": "stdio",
      "command": "python3",
      "args": ["tools/workitem_server.py"]
    }
  }
}
```

Use `"command": "py"` on Windows. Remove `.vscode/mcp.json` to avoid registering the same server
twice, then commit both sides of the migration:

```
git add .mcp.json .vscode/mcp.json
```

```
git commit -m "share workitem MCP wiring"
```

Restart the editor and CLI. Confirm folder trust when the CLI asks; VS Code may show its MCP trust
dialog when it discovers the new root configuration. Then repeat the ownership question.

**Expected finding:** repository-root `.mcp.json` is portable to Copilot CLI and compatible Agent Host
sessions. The root file uses Copilot CLI's `mcpServers` schema; the editor-only `.vscode/mcp.json`
uses VS Code's `servers` schema. The agent did not change; only its tool wiring travelled to the
second surface. See GitHub's
[current Copilot CLI MCP documentation](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-mcp-servers).

---

## Common Pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| Story Check is missing from the agent dropdown | Wrong path or extension | Must be `.github/agents/story-check.agent.md`, ending `.agent.md`. Then `Developer: Reload Window` |
| The Part 2 answer already cites DoR numbers | The standard was created too early | Delete `standards/`, start a new chat, re-ask. Presence is enough — the agent searches the folder |
| The grounded answer is no better | The pointer line has a typo, or the file is elsewhere | Read the reference list. If the standard is not on it, compare the path in the agent file with the path in Explorer |
| `workitem` not listed under MCP: List Servers | The editor has not re-read the config | Open `.vscode/mcp.json` and save it once |
| The MCP server fails to start | `mcp` not installed, incompatible SDK major version, or wrong interpreter | Run `python3 -m pip install "mcp>=2,<3"` (macOS/Linux) or `py -m pip install "mcp>=2,<3"` (Windows), and use that same launcher in the MCP config |
| Tools missing from Configure Tools | Trust dialog unanswered, or server stopped | `MCP: List Servers` shows the state in five seconds |
| The trust dialog never appeared | The editor remembers a previous answer | Trust lives in the editor, not the repo — which is itself the lesson. Gates have state, and somebody already opened this one |
| It hallucinates an owner without calling any tool | Instruction not forceful enough | This is why the Part 5 constraint says *call the tool before the verdict*. Re-read it aloud into the prompt once and re-run |
| Renaming the tool did not flip the route | Non-determinism | Strings shift the odds; they do not guarantee. Restart the server (a stale process still advertises old names) and run again |
| Conventions ignored even with `applyTo` present | Glob does not match the file being written | The pattern must cover `reviews/**`. If it still misses occasionally, say so honestly — attachment is best-effort, not a contract |
| No approval dialog on the commit request | Wrong permission level, auto-approve, terminal defaults, or a saved grant | Choose Default Approvals; set `chat.tools.global.autoApprove` and `chat.tools.terminal.enableAutoApprove` to false; run `Chat: Reset Tool Confirmations` |
| `copilot` not found | CLI not installed or Node too old | `node --version` must be 22+, then `npm install -g @github/copilot` |
| CLI cannot find the agent | Wrong working directory | It reads `.github/agents/` relative to where you launched it. `cd` into `story-check/` |
| Every CLI tool request is denied automatically | You used the `-p` flag | `-p` is non-interactive: no human, so no approvals, by design. Run it interactively |

---

## Key Takeaways

- **The agent is a file.** Frontmatter names it, the body instructs it. Everything else — grounding,
  tools, approvals — is wiring around that file.
- **Presence is not wiring.** A standard sitting in the repository is *in reach*. Only an instruction
  pointing at it makes it a rule on every run.
- **Grounding is retrieval, not training.** The model did not learn your Definition of Ready. It was
  handed the file, this run, because a line told it to.
- **The reference list is the diagnosis.** Read what it *read* before you read what it *said*.
- **Tool descriptions are prompts.** The selector sees a name and one line and picks a door by its
  sign. Three strings changed the route; the model never did.
- **Grounding fails silently.** Disable both automatic attachment signals — the `applyTo:` glob and
  a task-matching `description` — and the conventions stop applying with no error anywhere. Nothing
  in the output looks different in kind — only in quality.
- **Instructions shape behaviour; gates enforce reach.** The agent might obey the hard sentence,
  but if it tries the commit anyway, the dialog controls whether the command runs.
- **The agent travels; its reach does not.** Instructions and grounding live in the repository. Tools
  and approvals are wired per surface.

---

## Quick Reference

| Task | Where |
|---|---|
| Create a custom agent | `.github/agents/<name>.agent.md` |
| Select the agent | Agent dropdown in the chat input |
| Ground it in a file | A line in the agent body naming the path |
| Path-scoped conventions | `.github/instructions/<name>.instructions.md` with `applyTo:` |
| Add an editor-specific tool server | `.vscode/mcp.json` → `servers` → stdio command |
| Share tool wiring with Copilot CLI | Repository-root `.mcp.json` |
| Start / restart / stop a server | Command Palette → `MCP: List Servers` |
| See what the agent can call | **Configure Tools** in the chat input |
| See what it actually read | The reference list on the reply |
| Prepare the approval exercise | Default Approvals; global and terminal auto-approve false; reset tool confirmations |
| Run the same agent profile in a terminal | Run `copilot`, then `/agent`, then select **Story Check** |
| Reload after editing an agent file | Start a new chat and reselect the agent; use `Developer: Reload Window` if the list itself is stale |

---

## What's Next

You changed one thing at a time and watched the behaviour move. Everything in a larger agent is more
of the same five fields:

- **Instructions** — the agent file body
- **Grounding** — files, and the lines that point at them
- **Tools** — MCP servers, and the descriptions that get them chosen
- **Model** — the one thing you never touched in this lab
- **Approvals** — the gates, and who holds them

The next lab replaces the single agent with several that hand work to each other, and asks the
question this lab deliberately avoided: when three agents disagree, whose file wins?

---

## Cleanup

1. Command Palette → `MCP: List Servers` → **workitem** → **Stop**.
2. Run `Chat: Reset Tool Confirmations`, then restore
   `chat.tools.global.autoApprove` and `chat.tools.terminal.enableAutoApprove` to the values you noted
   in Part 0.4.
3. Delete the `story-check` folder, or keep it — it is self-contained and costs nothing.

The Copilot CLI stays installed and signed in; nothing else was installed on your machine except the
Python `mcp` package.
