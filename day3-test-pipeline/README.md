# Day 3 — Integrating QA and API Testing Automation

Three agents, and the line between agent and machinery drawn in code rather than
on a slide.

    design the cases     AGENT      deciding what is worth testing is judgement
    run the cases        machinery  issuing a request and comparing a value is not
    triage the failures  AGENT      deciding what a failure MEANS is judgement
    audit the verdicts   machinery  holding a claim to its evidence is a rule

Each runs on its own. All four run together as one LangGraph pipeline.

---

## The pieces

| file | what it is |
|------|-----------|
| `contract/openapi.json` | **the contract** — hand-written, reviewed by people. The source of truth. |
| `api/app.py` | the Case Notes API — the system under test, and where the breaks are armed |
| `agents/generate.py` | agent 1: reads the contract, designs the cases |
| `runner.py` | machinery: issues the requests, checks the answers. **No model in the file.** |
| `agents/triage.py` | agent 3: turns a red run into decisions, and audits its own |
| `pipeline.py` | the three wired together |
| `regression-cases.json` | the suite the team already had — including one that is out of date |
| `ledger.py` | one line per step: seconds, tokens, cost |

The API is the one Day 2's stories were about: the note-length cap from
STORY-4488, the closed-case rule from STORY-4520, the orders rate limit from
STORY-4501. Yesterday the room refined those stories. Today their tests get
written.

---

## Why the contract is frozen and hand-written

FastAPI will generate an OpenAPI document from `api/app.py` on request. **We do
not use it, and the reason is the whole point of the day.**

A generated spec is derived from the implementation, so the two can never
disagree. A "contract break" would be impossible by construction — the document
would simply describe whatever the code does, including the bugs.

`contract/openapi.json` is written by hand and reviewed by people. The server is
one team's attempt to satisfy it. When they disagree, **the server is wrong.**
That is what makes a contract worth having, and it is the only arrangement in
which the phrase "contract testing" means anything.

---

## Running it

```bash
pip install -r requirements.txt
cp .env.example .env            # then fill in the Azure trio
```

**Start the API.** Breaks are armed with an environment variable:

```bash
python -m uvicorn api.app:app --port 8742                      # honest server
DAY3_BREAKS=cap python -m uvicorn api.app:app --port 8742      # one break
DAY3_BREAKS=cap,retry,hang python -m uvicorn api.app:app --port 8742   # the demo set
```

**Then, separately or together:**

```bash
python -m agents.generate            # design cases from the contract
python -m agents.generate --ungrounded   # the same agent, contract taken away
python runner.py                     # run them
python -m agents.triage              # classify the failures
python -m agents.triage --audit      # hold each verdict to its own evidence

python pipeline.py                   # all four steps, one command
python pipeline.py --bill            # what it cost
```

---

## The breaks

| flag | what it does | what should catch it |
|------|--------------|---------------------|
| `cap` | note limit enforced at 4096, not the contract's 4000 | a generated boundary case at 4001 |
| `retry` | 429 returned without the required `Retry-After` header | a case that asserts the header, not just the status |
| `hang` | one customer's orders never answer — the call times out | nothing catches *what it is*. See below. |
| `pool` | one customer's orders return 503 | a happy-path case |

Plus one failure that is nobody's bug: `regression-cases.json` contains a case
expecting `400` where the contract now says `409`. **The test is wrong and the
API is right** — and a triage agent that cannot tell those apart is worth
nothing.

---

## The one it gets wrong

With `hang` armed, one case times out. Run the triage and it will classify it
`environment`, medium confidence, and recommend a rerun. It says this every
time.

It is wrong. The endpoint hangs on every call, today and next Tuesday.

**And the interesting part is that the agent was not being careless.** The
information needed to classify it correctly is not in the run. There is no
status code, no body, no header, and no contract clause that speaks to a
timeout. All it has is the *shape* of the failure — and a permanent hang and a
busy afternoon look identical from outside.

So it answered anyway, because it was asked to.

What should have warned you is in its own output. Its evidence lists three
observations, and not one of them is a second attempt:

```
- Observed status: "null".
- Runner reason: "the request never completed: ReadTimeout".
- Contract clause checked: "/cases/{case_id}/orders" defines 200, 400, 429, 404
```

A timeout is a **symptom**. Transience is a claim about what happens when you
try again — and you cannot make that claim from one attempt.

`--audit` applies exactly that rule, mechanically, to every verdict that assumes
transience. It costs nothing and it flags this one.

---

## What the ledger shows

```
step            runs   seconds   in_tok  out_tok      cost
generate           1      14.4     3597     1079    0.0198
triage             1      10.2     5253      649    0.0196
run_case          16       5.5        0        0    0.0000
audit              1       0.0        0        0    0.0000
```

Two agents, two pieces of machinery, alternating — and the machinery is a column
of zeros. That is the argument for keeping models out of the runner, stated as
arithmetic rather than as an opinion.

It also sets the price of the thing: **about four pence** to design a suite from
a contract, run it, and turn a red board into decisions.
