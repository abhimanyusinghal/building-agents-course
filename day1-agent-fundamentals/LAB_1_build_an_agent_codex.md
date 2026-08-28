# Lab 1 — Build a Working Agent From Nothing (OpenAI Codex)

This lab builds one small, real agent — **Story Check** — that reads a user story, judges it against
your team's Definition of Ready, and writes the refinement comment back to the repository.

You will build it in the order the pieces actually matter: instructions first, then grounding, then
tools, then the approval gate, then a second surface. Exactly one thing changes per part, so when the
behaviour changes you know precisely what changed it.

**You need no prior experience with Codex.** Part 0 takes you from "no account" to "prompt waiting for
you".

> **Everything in this document is meant to be copy-pasted.** There are no setup scripts. You create
> every file by hand, at the moment the lab needs it — the *order* in which files appear is part of
> the lesson, not an accident of packaging.

---

## Prerequisites

Install these before you start. Each line has the command that proves it worked.

| Requirement | Check it |
|---|---|
| A ChatGPT account with Codex access — or an OpenAI API key | You can sign in at [chatgpt.com](https://chatgpt.com) |
| Node.js 22 or newer | `node --version` |
| A terminal (PowerShell on Windows, Terminal on Mac/Linux) | — |
| Python 3.10 or newer, with pip (needed in Part 5) | `python3 --version && python3 -m pip --version` (macOS/Linux) or `py --version; py -m pip --version` (PowerShell) |
| Git (needed in Part 7) | `git --version` |
| A text editor you are comfortable in — VS Code is assumed for the file-creation steps | `code --version` |
| About 90 minutes | — |

You do **not** need to know Python. You will paste one short Python file and change two strings in it.

---

## Learning Objectives

### Core

- Create an agent in Codex as a file, and explain why the file *is* the agent
- Show the difference between an ungrounded answer and a grounded one, using the same model and the
  same question
- Distinguish **presence** (a file is in the folder) from **wiring** (an instruction points at it)
- Connect an MCP tool server to Codex, and see where that wiring actually lives
- Change which tool an agent picks without touching the model or lengthening the prompt
- Recognise a silent grounding failure — the kind that produces no error at all

### Advanced

- Predict which of the agent's five fields — instructions, grounding, tools, model, approvals — you
  must change to fix a given failure
- Explain why a tool description is a prompt, not documentation
- Explain the difference between a **sandbox** (what is possible) and an **approval policy** (who is
  asked), and why Codex has both
- Design an instruction that survives a missing tool instead of hallucinating around it

---

## Part 0: Get Codex Working

### 0.1 Install

```
npm install -g @openai/codex
```

On macOS you can instead use:

```
brew install --cask codex
```

Confirm:

```
codex --version
```

### 0.2 Sign in

```
codex login
```

A browser opens; sign in with your ChatGPT account. If you are using an API key, the CLI reads it
from standard input.

**macOS / Linux:**

```
printenv OPENAI_API_KEY | codex login --with-api-key
```

**Windows (PowerShell):**

```
$env:OPENAI_API_KEY | codex login --with-api-key
```

On a machine with no browser:

```
codex login --device-auth
```

Device-code login is a beta option and must first be enabled in your ChatGPT security settings, or
by a workspace admin in ChatGPT workspace permissions. See the
[official authentication documentation](https://learn.chatgpt.com/docs/auth).

### 0.3 Know your two dials before you start

Codex gates what an agent can do with **two independent settings**. You will use both by name
throughout this lab, so learn them now.

| Dial | Values | What it controls |
|---|---|---|
| `--sandbox` | `read-only` · `workspace-write` · `danger-full-access` | What is **possible** at all |
| `--ask-for-approval` | `on-request` · `never` | Whether **you** are asked when the agent wants more |

`read-only` means the agent cannot write a file even if it decides to. `workspace-write` means it can
write inside the folder you launched in, but not outside it and not to the network. The approval
setting decides what happens when the agent wants something the sandbox will not give it: ask you, or
just fail.

> Most tools have one dial. Codex has two, and they answer different questions. Keep them apart in
> your head and half the confusion about "why did it do that / why won't it do that" disappears.
> The [official approvals and sandbox documentation](https://learn.chatgpt.com/docs/agent-approvals-security)
> describes how the two settings interact.

### 0.4 The IDE extension (optional)

Codex also ships as an extension for VS Code, Cursor and Windsurf, sharing your CLI login. This lab
uses the terminal throughout, because that is where the file mechanics are visible.

---

## Part 1: Build the Workspace

The agent can read everything in the folder you launch it from. So what is in the folder is a
decision, and we make it deliberately, one file at a time.

### 1.1 Create the folders

Create a folder called `story-check` anywhere convenient (Desktop is fine). Open it in VS Code:
**File → Open Folder…** → select `story-check`.

> **Open `story-check` itself, not its parent.** The folder you launch Codex from is the agent's
> world — and in Codex, more literally than in most tools. Part 6 turns on exactly that.

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

Codex works best in a Git repository. In a non-version-controlled folder, current Codex normally
recommends or starts in `read-only`; Git is not a hard startup requirement. This lab uses Git so every
change is reviewable and Part 7 has a clean commit target. Open a terminal inside VS Code —
**Terminal → New Terminal** — confirm the prompt shows the `story-check` folder, then run:

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

**You should see** — Explorer showing exactly two files under `intake/`, an empty `reviews/`, and a
clean `git status`.

> ⚠️ **Do not create a `standards/` folder yet.** Do not paste the Definition of Ready anywhere. The
> agent searches this folder on its own — if the standard is present in Part 2, the agent finds it
> unprompted and the whole first lesson evaporates.

---

## Part 2: An Agent From Nothing

### 2.1 Create the agent file

In Codex, the agent's instructions are a file called **`AGENTS.md`**, sitting in the root of the
repository. Codex reads it at the start of every session in that folder. That is the entire
mechanism.

Create `AGENTS.md` in the root of `story-check/` and paste exactly this:

```markdown
# Story Check

Check a single user story against the team's Definition of Ready, say whether it is
ready to be picked up, and if it is not, list exactly what is missing.
```

Save it.

That is the whole agent. There is no other screen, no console, no deployment. The file is in the
working tree now; after the checkpoint before Part 7 commits it, it is versioned, reviewable, and
travels with a clone.

### 2.2 Start a session

In the terminal, inside `story-check/`:

```
codex --sandbox workspace-write --ask-for-approval on-request
```

On first use in a new folder, Codex asks whether you trust this directory. Read the question before
answering it — you are being asked to let a program act inside a folder on your behalf. Approve.

**You should see:** the Codex prompt, and — usually near the top — an indication that it picked up
`AGENTS.md`.

### 2.3 Ask it the question

Paste this and send it:

```
Is STORY-4471 ready to pick up?
```

**You should see:** a fluent, confident, entirely generic verdict. It will talk about acceptance
criteria and vagueness. It will sound right.

Now do the thing most people skip. **Look at the commands and file reads Codex printed** above the
answer.

It read `intake/STORY-4471.md`. Nothing else. There was nothing else to read.

### 2.4 The question to sit with

Your team's Definition of Ready has **seven** numbered criteria.

Before reading on: how many of them did that answer check?

None of them. It could not have — the standard is not in this folder. It judged the story against
*a* definition of ready, the general one, learned from everywhere. And nothing in the wording of the
reply tells you that.

> **This is the failure mode you will meet most often in production.** Not a wrong answer. A
> plausible answer to a question you did not ask, delivered in the same tone as a correct one.

Exit the session (`Ctrl+C` twice).

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

**Notice what has not happened.** `AGENTS.md` is untouched. Nothing connects the agent to this file
except the chance that a search stumbles across it. Hope is not wiring.

### 3.2 Then, the line

Open `AGENTS.md` and **append** this single line:

```
Judge only against standards/definition-of-ready.md, and quote the criterion number for every finding.
```

Save. The file now reads:

```markdown
# Story Check

Check a single user story against the team's Definition of Ready, say whether it is
ready to be picked up, and if it is not, list exactly what is missing.

Judge only against standards/definition-of-ready.md, and quote the criterion number for every finding.
```

### 3.3 Ask again — the same question, word for word

Start a **fresh** session so `AGENTS.md` is re-read:

```
codex --sandbox workspace-write --ask-for-approval on-request
```

```
Is STORY-4471 ready to pick up?
```

**You should see:** a read of `standards/definition-of-ready.md` in the printed activity, and a
verdict that cites criterion numbers and quotes the actual offending words from the story —
`reasonable`, `appropriate`, `user-friendly`.

### 3.4 The diagnosis lives in the gap

Scroll back so both answers are on screen. Read the two sets of file reads against each other.

Same model. Same question. Same wording. One file, and one line pointing at it.

> **Grounding is not training.** Nothing about the model changed. The instruction caused a file to be
> retrieved into this run's context — and it will do that again on the next run, and every run. That
> guarantee is what the line buys you. Without it, the file was merely *nearby*.

Exit the session.

---

## Part 4: The Rest of the Instructions

A one-sentence agent proved the point. A working agent needs a response format and guardrails.

Replace the **entire contents** of `AGENTS.md` with this:

```markdown
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

Install the one dependency with the same Python launcher you will use for the server:

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

### 5.2 Wire the server

Get the full path of the server file. In the terminal, inside `story-check/`:

**Windows (PowerShell):**

```
(Resolve-Path tools/workitem_server.py).Path
```

**macOS / Linux:**

```
python3 -c 'from pathlib import Path; print(Path("tools/workitem_server.py").resolve())'
```

Now register the server, substituting that path.

**macOS / Linux:**

```
codex mcp add workitem -- python3 "/FULL/PATH/TO/story-check/tools/workitem_server.py"
```

**Windows (PowerShell):**

```
codex mcp add workitem -- py "C:\FULL\PATH\TO\story-check\tools\workitem_server.py"
```

Confirm it registered:

```
codex mcp list
```

### 5.3 Look at where that wiring actually went

Open `~/.codex/config.toml` (on Windows, `C:\Users\<you>\.codex\config.toml`). You will find
something like:

```toml
[mcp_servers.workitem]
enabled = true
command = "python3"
args = ["/FULL/PATH/TO/story-check/tools/workitem_server.py"]
```

On Windows the corresponding command is `"py"`.

**Stop and notice where that file is.** It is in your home directory. It is **not in the repository**.

Your instructions are in `AGENTS.md` and your grounding is in `standards/`; both are project files you
will commit before Part 7. Your tool wiring is in a file on your laptop that no teammate will ever
receive. Hold that thought — Part 8 is built on it.

> There is no separate "trust this server" dialog here. In Codex the gate is not per-server; it is the
> sandbox and the approval policy you launched with. A server you registered is a server that runs.
> That places the responsibility earlier: on the moment you typed `codex mcp add`.

### 5.4 See what the agent sees

Start a session:

```
codex --sandbox workspace-write --ask-for-approval on-request
```

The `workitem` tools are now available, namespaced by server — you will see them referenced as
something like `workitem:search_backlog`.

For tool selection, the model sees each advertised name, input schema, and description. It cannot
safely try a tool and undo the call; it picks a door by reading the sign.

### 5.5 The question that forces a choice

```
Is STORY-4471 ready to pick up, and which team would own the work?
```

Watch the tool calls, and **read the call and its result**.

The likely outcome: it reaches for `search_backlog` with `case-web` and gets matching story rows —
valid backlog data that does not answer who owns the component. Two tools called "search something",
and it took the wrong one because the descriptions did not make their jobs distinct.

> **If it picks the right tool first time:** that happens, roughly as often as not. Do not re-run
> hoping for failure. Instead ask yourself: *how could I have known in advance that it would?* You
> could not. Same question, two runs, two routes — that is what non-deterministic means, and it is
> why you cannot test one of these by replaying an expected sequence. Then break it deliberately:
> rename `search_owners` to `tool_1`, set its docstring to `"Searches."`, restart the session, and
> ask again. That usually makes the wrong route easier to observe, and it is the truer example —
> that is what tools are called when nobody names them. If it still selects `tool_1`, record that
> result and continue; names and descriptions shift a model's odds, not guarantee a trace. Restore
> the function name to `search_owners` and its docstring to `"Searches items and returns
> information."` before continuing. Part 5.7 will restart the server after you apply the real fix.

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

**String three.** Append this to the **Constraints** section of `AGENTS.md`:

```
- When a story names a component, call get_component_owner with that component name
  before you write the verdict, and name the owning team in the review. Use
  get_component_owner only for components. Use search_backlog only when you are
  looking for other stories that might overlap.
```

Save both files.

### 5.7 Restart and re-ask

Exit the session and start a new one — the server process and `AGENTS.md` are both re-read on launch:

```
codex --sandbox workspace-write --ask-for-approval on-request
```

Ask the **same question, unchanged**:

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

> ⚠️ **You are about to add the conventions for the first time.** If you added them earlier, remove
> them and start this part fresh — the whole point is to see the run *before* and *after*.

Codex has a grounding rule most people learn the hard way, and this part is that rule: **`AGENTS.md`
files apply based on where you launched, not on what you are writing.** Codex collects them from the
repository root down to your current directory, and stops there.

### 6.1 Add house conventions

Append this section to the end of `AGENTS.md`:

```markdown
## Story review conventions

- Refer to criteria as `DoR-1` through `DoR-7`, matching the numbered sections of
  `standards/definition-of-ready.md`.
- Quote the offending words from the story in backticks. Do not paraphrase them — the
  author needs to find the phrase they wrote.
- Name people by their handle (r.iyer, p.nair), never by full name.
- Do not propose the wording of an acceptance criterion the author has not attempted.
  Say what is untestable about theirs and what a testable one would have to state.
- No praise, no filler openings. The first line is the verdict.
```

### 6.2 The full run

Start a fresh session and run:

```
Check STORY-4471 against our Definition of Ready and write the review.
```

Approve the file write when asked.

Open `reviews/STORY-4471.md`. Look for three fingerprints:

1. Criteria written as `DoR-1` … `DoR-7`
2. The offending words from the story in backticks
3. Handles, not full names

Those three habits came from a section nobody mentioned in the prompt.

### 6.3 The experiment — move the file, break it silently

This is where most teams get caught: they file conventions "next to the thing they apply to".

1. **Cut** the whole `## Story review conventions` section out of `AGENTS.md`.
2. Create a new file `reviews/AGENTS.md` and paste the section into it, on its own.
3. Save both. Delete `reviews/STORY-4471.md`.
4. Exit, relaunch Codex **from the repository root** as before, and run the same prompt again,
   unchanged.

**You should see:** a correct review — and the house style gone.

No error. No warning. Nothing changed colour. The file is still there, still valid Markdown, still
reviewed by somebody, and doing nothing at all.

Why: Codex looked for `AGENTS.md` files from the repository root **down to your current directory**,
and your current directory was the root. `reviews/AGENTS.md` sits below it, so it was never read —
even though the agent was, at that very moment, writing a file into `reviews/`.

> **This is the grounding failure you will actually meet.** Not a crash. A file that quietly stopped
> applying, in a system whose output always looks confident. And note the specific trap: the file is
> *closer* to the work, which feels more correct and is in fact worse.

Restore it: move the section back into the root `AGENTS.md`, delete `reviews/AGENTS.md`, delete
`reviews/STORY-4471.md`, then exit and relaunch Codex from the repository root. Run the prompt once
more so the restored root instructions are loaded and you finish this part with a correctly-styled
review on disk.

---

## Part 7: The Two Gates

Your Guidance says **do not commit**. Now you are going to ask anyway and watch which layer actually
stops execution.

### 7.1 Checkpoint the setup

Run these two commands yourself so the later review commit cannot include the setup files:

```
git add AGENTS.md standards/definition-of-ready.md tools/workitem_server.py
git commit -m "build story-check agent"
```

The generated review remains uncommitted. That is all the Git setup this exercise needs.

### 7.2 Ask it to commit — with the sandbox closed

Exit, and relaunch with the tightest sandbox:

```
codex --sandbox read-only --ask-for-approval on-request
```

Then ask:

```
Commit that review with the message "story-check: STORY-4471".
```

The likely outcome is an approval request. **Do not answer yet.**

If the agent instead refuses because its Guidance says not to commit, that is also a win: the
instruction shaped this run. Ask it to `Create an empty file at reviews/approval-check.tmp, then
stop.` That harmless write gives you a gate to inspect; deny it after the inspection and skip the
commit-specific sentence below.

For the commit branch, check one thing before anything runs: the proposed command must stage only
`reviews/STORY-4471.md`. Reject `git add -A`, `git add .`, or any broad path. Then read the approval
scopes. One scope approves once; another typically approves for the rest of the session. Land on the
latter so you can see the standing grant.

> There is the standing grant — one keystroke away, styled like a convenience. Every "why did the
> agent do that?" incident review you will ever read has one of these in it, chosen eight weeks
> earlier by somebody who was in a hurry.

On the commit branch, approve **once**. The agent file said *do not commit*; the request happened
anyway, and the sandbox still blocked execution until you approved it. On the refusal branch, the
instruction was honoured this run — but the harmless write still met the same client gate.

> **Instructions shape behaviour; gates enforce reach.** A sentence in `AGENTS.md` influences what
> the model attempts. The sandbox is the wall, and the approval policy decides who gets asked at the
> wall.

### 7.3 The same request, with the gate removed

Exit and relaunch with approvals switched off:

```
codex --sandbox workspace-write --ask-for-approval never
```

Ask for something harmless that needs a command:

```
Show me the recent commits and tell me which one added the review.
```

No prompt. It just runs, inside the sandbox. That is not a bug — it is the setting you chose, doing
exactly what it says.

> **Two dials, four combinations.** `read-only` + `on-request` is the careful pairing you use when
> exploring somebody else's repository. `workspace-write` + `never` is the CI pairing: nothing outside
> the folder is possible, and nobody is asked. `danger-full-access` removes the first dial entirely —
> and there is a shorthand flag for that, which you should be able to name and should almost never
> type.

---

## Part 8: A Second Surface — What a Teammate Actually Receives

Two things change here at once, and both are honest about how these systems fail in real teams.

### 8.1 Take the tool away — without touching the repository

Open `~/.codex/config.toml` and set the server to disabled:

```toml
[mcp_servers.workitem]
enabled = false
```

Save. **Nothing in the `story-check` repository changed.** No commit. No diff. `git status` is clean.

This is precisely the state a teammate is in five minutes after they clone your repo: they have your
`AGENTS.md`, your `standards/`, your conventions — and they do not have your tool, because your tool
was never in the repository.

### 8.2 Run it with no human attached

`codex exec` is the non-interactive mode: it takes a prompt, runs, prints, and exits. There is nobody
to ask for approval, so the approval policy is effectively `never`.

```
codex exec --sandbox workspace-write "Check STORY-4488 against our Definition of Ready and write the review."
```

Watch what happens when it reaches the ownership step.

`AGENTS.md` tells it to call `get_component_owner`. That tool does not exist in this session. What
does an agent do when the instructions demand a fact it cannot fetch?

Two outcomes, and both are worth having:

- **It follows the Guidance bullet** — writes the review, and says in one line that the owning team
  could not be determined. That is your guardrail from Part 4 working. Go and read that bullet again;
  it is four sentences and it is the difference between a useful review and an invented one.
- **It improvises** — reaches for `tools/workitem_server.py`, because the ownership table is sitting
  in the repository as plain source code, in reach. If the sandbox lets it read that file, it may well
  produce a *correct* answer by an *illegitimate* route. That is the more instructive outcome:
  correct output, untrustworthy process, and nothing in the review says which one you got.

Open `reviews/STORY-4488.md`. Same standard, same conventions, a much stronger story.

**Expect a verdict of `Ready`** — but a strict run may come back **`Not ready`**, usually on DoR-3
(the story names `case-web` but its criteria also cover saving and reloading notes) or DoR-5 (it
states a retention period without listing the personal-data categories). **Both outcomes are
correct.** You are not verifying the verdict here; you are verifying that the *same standard* and the
*same conventions* produced it — `DoR-N` numbering, backticked quotes, handles not names.

### 8.3 What travelled, and what did not

| Field | In the repository? | Travels to a teammate or CI? |
|---|---|---|
| Instructions (`AGENTS.md`) | Yes | Yes |
| Grounding (`standards/`, conventions) | Yes | Yes |
| Tools (`~/.codex/config.toml`) | **No** | **No** — every person and every runner wires them separately |
| Approvals (`--sandbox`, `--ask-for-approval`) | No | No — chosen per invocation |
| Model | No | Whatever that machine defaults to |

> You rebuilt nothing. The agent travelled because the agent **is** the files. Its reach did not,
> because its reach was never in a file you shipped.

Re-enable the server when you are done:

```toml
[mcp_servers.workitem]
enabled = true
```

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

Restart the session and ask:

```
Is anything else in the backlog overlapping with STORY-4471?
```

**Expected finding:** with a description that says "finds other stories", the agent reaches for it
directly and surfaces STORY-4102, STORY-4188 and STORY-4310 — and, because of the `AGENTS.md`
constraint, reports them as *possible* overlaps rather than asserting duplicates.

### Exercise 3 — Break the grounding pointer

In `AGENTS.md`, change the path in the Constraints section from `standards/definition-of-ready.md` to
`standards/dor.md` (a file that does not exist). Save, relaunch, and ask the Part 2 question again.

**Expected finding:** you get an answer. A confident one. The list of file reads is your only evidence
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
| The agent read the tool server's source code to get the answer | |

**Answers:** tools (it needs a tool call, and an instruction to make it); instructions (response
format); instructions first, then a tighter sandbox; tools (descriptions); approvals and sandbox — the
Guidance bullet asks it not to, but `--sandbox read-only` is what makes the shortcut impossible.

### Exercise 5 — Ship the tool wiring with the repository

Part 8 showed that `~/.codex/config.toml` does not travel. Codex also reads a project-level
`.codex/config.toml` from the repository. Move the server definition there:

```toml
[mcp_servers.workitem]
enabled = true
command = "python3"
args = ["tools/workitem_server.py"]
```

Use `command = "py"` on Windows.

Remove it from `~/.codex/config.toml`, commit `.codex/config.toml`, and re-run.

**Expected finding:** the tool now travels with the repository — and you have created exactly the
situation the trust prompt exists for, because anyone who clones this repo now ships you a file that
launches a process on their machine. Write one sentence on which you would choose for your team, and
why.

### Exercise 6 (advanced) — A named agent instead of `AGENTS.md`

Codex also supports named agents defined as TOML in `.codex/agents/`. Create
`.codex/agents/story-check.toml`:

```toml
name = "story_check"
description = "Checks one user story against the team Definition of Ready"
sandbox_mode = "workspace-write"
developer_instructions = """
Paste the body of your AGENTS.md here.
"""
```

Then, in a session, delegate to it explicitly: *"Have story_check review STORY-4471."*

**Expected finding:** the same agent, addressed by name, spawned as its own thread with its own
sandbox setting. Note what this buys you that `AGENTS.md` does not: several differently-scoped agents
in one repository, instead of one set of instructions that applies to everything.

---

## Common Pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| Codex starts in read-only unexpectedly | The folder is not version-controlled or not yet trusted | Run `git init` for this lab, then use `/permissions` if you intentionally want a different mode |
| Edits to `AGENTS.md` have no effect | The file is read at launch | Exit and relaunch. Editing mid-session changes nothing |
| The Part 2 answer already cites DoR numbers | The standard was created too early | Delete `standards/`, relaunch, re-ask. Presence is enough — the agent searches the folder |
| The grounded answer is no better | The pointer line has a typo, or the file is elsewhere | Look at the file reads. If the standard is not among them, compare the path in `AGENTS.md` with the path in Explorer |
| `codex mcp list` does not show `workitem` | The add command failed | Re-run `codex mcp add`, and check `~/.codex/config.toml` by hand |
| The server is listed but no tools appear | Server failed to start | Run `python3 -m pip install "mcp>=2,<3"` (macOS/Linux) or `py -m pip install "mcp>=2,<3"` (Windows), and use that same launcher in the MCP command |
| The server starts but cannot find the script | Relative path resolved from the wrong directory | Use the absolute path in `args`, as Part 5.2 instructs |
| It hallucinates an owner without calling any tool | Instruction not forceful enough | This is why the Part 5 constraint says *call the tool before the verdict*. Re-read it aloud into the prompt once and re-run |
| Renaming the tool did not flip the route | Non-determinism | Strings shift the odds; they do not guarantee. Make sure you relaunched (a stale server process still advertises old names) and run again |
| Conventions ignored after Part 6 | `reviews/AGENTS.md` is below your launch directory | That IS the lesson. Put them in the root `AGENTS.md` |
| No approval prompt in Part 7 | You launched with `--ask-for-approval never`, or the sandbox already permitted the action | Relaunch with `--sandbox read-only --ask-for-approval on-request` |
| Git commit fails with "unknown author" | Git identity not configured | `git config user.email` / `git config user.name` |
| `codex exec` does nothing useful | It cannot ask, so anything the sandbox denies simply fails | Widen `--sandbox` deliberately, and only as far as the task needs |

---

## Key Takeaways

- **The agent is a file.** `AGENTS.md` in the repository *is* the agent. Everything else — grounding,
  tools, approvals — is wiring around that file.
- **Presence is not wiring.** A standard sitting in the repository is *in reach*. Only an instruction
  pointing at it makes it a rule on every run.
- **Grounding is retrieval, not training.** The model did not learn your Definition of Ready. It was
  handed the file, this run, because a line told it to.
- **Read what it read, before you read what it said.** The file reads and tool calls are the
  diagnosis; the prose is the symptom.
- **Tool descriptions are prompts.** The selector sees a name and one line and picks a door by its
  sign. Three strings changed the route; the model never did.
- **`AGENTS.md` scope follows your launch directory, not your work.** A conventions file placed
  "closer to the work" can be read by nobody — silently, with a clean `git status`.
- **The sandbox is the wall; the approval policy is the doorbell.** The agent file shaped the
  attempt; the sandbox and approval policy controlled whether anything could execute.
- **What travels is what you committed.** Instructions and grounding live in the repository. In Codex,
  tool wiring lives in your home directory by default — so the agent travels and its reach does not,
  until you deliberately move that wiring into the repo.

---

## Quick Reference

| Task | Where |
|---|---|
| Agent instructions | `AGENTS.md` at the repository root |
| Directory-specific instructions | `AGENTS.md` in that directory — applies only when you launch in or below it |
| Ground it in a file | A line in `AGENTS.md` naming the path |
| Named agents | `.codex/agents/<name>.toml` (`name`, `description`, `developer_instructions`) |
| Add a tool server | `codex mcp add <name> -- <command> <args>` |
| List / inspect tool servers | `codex mcp list`, or `~/.codex/config.toml` |
| Ship tool wiring with the repo | `.codex/config.toml` → `[mcp_servers.<name>]` |
| Control what is possible | `--sandbox read-only \| workspace-write \| danger-full-access` |
| Control who is asked | `--ask-for-approval on-request \| never` |
| Run with no human | `codex exec "…"` |
| Sign in / switch account | `codex login` |

---

## What's Next

You changed one thing at a time and watched the behaviour move. Everything in a larger agent is more
of the same five fields:

- **Instructions** — `AGENTS.md`
- **Grounding** — files, and the lines that point at them
- **Tools** — MCP servers, and the descriptions that get them chosen
- **Model** — the one thing you never touched in this lab
- **Approvals** — the sandbox, the approval policy, and who holds them

The next lab replaces the single agent with several that hand work to each other, and asks the
question this lab deliberately avoided: when three agents disagree, whose file wins?

---

## Cleanup

1. If `workitem` is still registered in your user config, remove it:

```
codex mcp remove workitem
```

   If you completed Exercise 5 and moved the definition into `.codex/config.toml`, skip this command;
   deleting the project removes that project-scoped registration.
2. Confirm nothing is left in `~/.codex/config.toml` that points at a folder you are about to delete.
3. Delete the `story-check` folder, or keep it — it is self-contained and costs nothing.

Codex stays installed and signed in; nothing else was installed on your machine except the Python
`mcp` package.
