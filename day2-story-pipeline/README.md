# day2-story-pipeline — one judgement island inside a designed spine

A user story lands in the tracker; this pipeline checks it against the team's
Definition of Ready, drafts the refinement comment, and **waits for a named
person's approval before anything is posted**. One judgement island (the Story
Check agent) inside a designed spine (a LangGraph state graph), driving real
systems: GitHub Issues as the work tracker, mail for the human path, an Azure
OpenAI deployment behind the judge.

This folder is the **finished** pipeline — the state the session built up to:

```
fetch -> guard -> rules_gate -> judge -> gate_ask -> gate_wait(interrupt)
                      |                                   |
                      +-> post (rules failed: free reject)+-> post_review / hold
```

- **guard** (chapter 2): the idempotency check — a story already handled is
  never judged or posted twice.
- **gate** (chapter 3): the human approval — the graph *interrupts*, mails the
  reviewer, and resumes only on their answer. The checkpointer makes the wait
  survive restarts.

## Layout

| File | What it is |
|------|-----------|
| `graph.py` | the spine — nodes, edges, caps; the process, planned in the design |
| `judge.py` | the judgement step — a tool-calling agent that plans its own route inside its box |
| `gh.py` | tracker adapter — real GitHub Issues REST calls |
| `mailer.py` / `mailer_gmail.py` | people adapter — Microsoft Graph, with a Gmail fallback |
| `ledger.py` | the proof — one line per step, cost per accepted outcome |
| `pipeline.py` | the runner — run / sweep / watch / answer / resume / stall-sweep / bill |
| `seed.py`, `reset.py` | provision your demo repo; restore a clean state |
| `stories/` | the story bodies `seed.py` files as issues |
| `definition-of-ready.md` | the standard the judge applies |

## Setup

```bash
pip install -r ../requirements.txt
cp .env.example .env        # then fill it in — table below
python seed.py              # once, against your fresh repo
python pipeline.py bill     # sanity: "No ledger yet."
```

What goes in `.env`:

| key | where it comes from |
|-----|--------------------|
| `AZURE_OPENAI_API_KEY` / `_ENDPOINT` / `_DEPLOYMENT` | your Azure OpenAI resource |
| `GH_REPO` | `<your-user>/<a-repo-you-create>` — the pipeline's work tracker |
| `GH_TOKEN` | fine-grained PAT for that repo — Issues **Read and write**, Metadata Read |
| `GH_TOKEN_READONLY` | same repo, Issues **Read only** — used to demonstrate least-privilege failure |
| `MAIL_*` / `REVIEWER_EMAIL` | only for the mail leg — see below, **optional** |

> **Note the identity lesson:** the PAT is scoped to ONE repo and expires.
> That credential belongs to the pipeline, not to you — revoking it stops the
> agent without touching your own access. Day 4 builds on exactly this.

### Mail is optional

Everything except the approval e-mail runs without mail. When you want the
full human-gate experience:

- **Easiest:** set `MAIL_BACKEND=gmail` plus a Gmail address and a
  16-character app password.
- **Microsoft Graph:** register an Entra app (delegated `Mail.Send` +
  `Mail.Read`, public client), put its client id + tenant in `.env`, and run
  `python pipeline.py mail-test` — the first run signs you in with a device
  code. If the admin-consent CLI hangs, tick *"Consent on behalf of your
  organization"* on the device-code screen instead.

## The verbs

```bash
python pipeline.py run --story 4471    # one story, now
python pipeline.py sweep               # every open story — the schedule's arrival
python pipeline.py watch               # new issues + approval replies, until Ctrl+C
python pipeline.py answer --story 4512 --approve   # resume a waiting run by hand
python pipeline.py resume --story 4495 # resume after a crash or a fixed failure
python pipeline.py stall-sweep         # alert on runs waiting past the clock
python pipeline.py bill                # the ledger, totalled
python reset.py                        # put the tracker + local state back to clean
```

State lives on the work item as a `state:*` label:
`new → needs-human/waiting → posted` or `held`; `state:hold` marks stories the
pipeline must leave alone until released.

## What to study

1. `graph.py` `build_graph()` — the whole process in a screenful of edges;
   find the conditional edge and the interrupt.
2. `judge.py` — how little a "judgement island" needs: model, tools, brief,
   answer shape.
3. Run `sweep` twice — the guard makes the second pass free. Then read
   `ledger.csv`: cost per *accepted outcome* is the number that matters.
