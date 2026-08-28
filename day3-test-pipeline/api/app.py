"""
===============================================================================
 THE CASE NOTES API  —  the system under test
===============================================================================

This is the service the tests are written against. It is the API behind the
case screen from Day 2: the same notes, the same closed-case rule, the same
orders lookup that somebody wanted rate limited.

WHAT MATTERS ABOUT THIS FILE
    It is built to satisfy contract/openapi.json - and, when we ask it to, it
    deliberately does not.

    That is the whole point. The contract is written by hand and reviewed by
    people. The server is one team's attempt to implement it. Real systems
    drift apart exactly here: the document says one thing, the code does
    another, and nobody notices until a customer does.

    An OpenAPI file generated FROM this code could never disagree with it,
    which is why the contract in this repo is frozen and hand-written. A
    generated spec cannot catch a contract break; it defines one out of
    existence.

ARMING THE BREAKS
    DAY3_BREAKS is a comma-separated list, or "all", or unset for none:

        (unset)   the server matches the contract in every respect
        cap       the note-length limit is enforced at the wrong boundary
        retry     429 responses are returned without the Retry-After header
        pool      one customer's orders return 503 (documented as a defect)
        hang      one customer's orders never answer - the call times out
        all       every break above

    Each one is a real defect of a kind you have shipped. None of them is
    random: the same request produces the same failure every time.
===============================================================================
"""
import os
import time as _time
from datetime import datetime, timezone, timedelta

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="Case Notes API", version="2.4.0", docs_url=None, redoc_url=None)

BREAKS = {b.strip() for b in os.environ.get("DAY3_BREAKS", "").split(",") if b.strip()}
def broken(name: str) -> bool:
    return name in BREAKS or "all" in BREAKS


# =============================================================================
#  THE DATA  -  three cases, held in memory. Restarting the server resets it.
# =============================================================================
CASES = {
    "CASE-1001": {"case_id": "CASE-1001", "customer": "R. Okafor",     "status": "open"},
    "CASE-1002": {"case_id": "CASE-1002", "customer": "M. Lindqvist",  "status": "open"},
    "CASE-1009": {"case_id": "CASE-1009", "customer": "T. Bhatt",      "status": "closed"},
}
NOTES: dict[str, list[dict]] = {c: [] for c in CASES}

ORDERS = {
    "CASE-1001": [
        {"order_id": "ORD-88120", "placed_at": "2026-08-14T09:12:00Z", "total_pence": 4599,  "status": "delivered"},
        {"order_id": "ORD-88455", "placed_at": "2026-08-19T16:40:00Z", "total_pence": 12250, "status": "shipped"},
    ],
    "CASE-1002": [
        {"order_id": "ORD-88907", "placed_at": "2026-08-21T11:05:00Z", "total_pence": 899,   "status": "placed"},
    ],
    "CASE-1009": [],
}

_seq = {"note": 0}
_rate: dict[str, list[datetime]] = {}
_orders_calls = {"n": 0}          # drives the "pool" break, deterministically


ROLES = ("agent", "supervisor", "readonly")
WRITERS = ("agent", "supervisor")


def check_role(role: str | None):
    """Every request carries X-Role. Missing or unknown is refused (R-ROLE-REQ)."""
    if role is None:
        return err(400, "role_required", "The X-Role header is required.")
    if role not in ROLES:
        return err(400, "role_unknown", f"Unknown role {role}.")
    return None


def err(status: int, code: str, message: str, headers: dict | None = None):
    return JSONResponse(status_code=status, content={"error": code, "message": message},
                        headers=headers or {})


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# =============================================================================
#  GET /cases/{case_id}
# =============================================================================
@app.get("/cases/{case_id}")
def get_case(case_id: str, x_role: str | None = Header(default=None)):
    bad = check_role(x_role)
    if bad:
        return bad
    case = CASES.get(case_id)
    if not case:
        return err(404, "case_not_found", f"No case with id {case_id}.")
    return {**case, "note_count": len(NOTES[case_id])}


# =============================================================================
#  POST /cases/{case_id}/notes        STORY-4488 (the cap) + STORY-4520 (closed)
# =============================================================================
NOTE_MAX = 4000          # what the contract says

@app.post("/cases/{case_id}/notes")
async def add_note(case_id: str, request: Request,
                   x_role: str | None = Header(default=None)):
    bad = check_role(x_role)
    if bad:
        return bad
    # R-ROLE-WRITE. Three roles, two operations - six combinations, and a suite
    # written from the happy path covers one of them.
    if x_role not in WRITERS:
        return err(403, "role_forbidden", f"The {x_role} role may not add notes.")
    case = CASES.get(case_id)
    if not case:
        return err(404, "case_not_found", f"No case with id {case_id}.")

    try:
        body = await request.json()
    except Exception:
        return err(422, "invalid_body", "Body must be JSON with a text field.")
    text = body.get("text")

    if not isinstance(text, str) or len(text) == 0:
        return err(422, "text_required", "A note must have text.")

    # ---- BREAK: cap ---------------------------------------------------------
    # The contract says 4000. This enforces 4096 - somebody reached for a round
    # binary number instead of reading the story. Notes of 4001-4096 characters
    # are accepted when they should be refused, and the difference only shows up
    # if your tests probe the exact boundary the contract names.
    limit = 4096 if broken("cap") else NOTE_MAX

    if len(text) > limit:
        return err(422, "text_too_long",
                   f"Note text must be {NOTE_MAX} characters or fewer.")

    # A closed case is read-only (STORY-4520).
    if case["status"] == "closed":
        return err(409, "case_closed", "This case is closed and cannot take new notes.")

    _seq["note"] += 1
    note = {"note_id": f"NOTE-{_seq['note']:05d}", "case_id": case_id,
            "text": text, "created_at": now_iso()}
    NOTES[case_id].insert(0, note)
    return JSONResponse(status_code=201, content=note)


@app.get("/cases/{case_id}/notes")
def list_notes(case_id: str, x_role: str | None = Header(default=None)):
    bad = check_role(x_role)
    if bad:
        return bad
    if case_id not in CASES:
        return err(404, "case_not_found", f"No case with id {case_id}.")
    return NOTES[case_id]


# =============================================================================
#  GET /cases/{case_id}/orders        STORY-4471 (orders) + STORY-4501 (limit)
# =============================================================================
RATE_LIMIT = 100         # requests per minute per client, per the contract

@app.get("/cases/{case_id}/orders")
def list_orders(case_id: str, x_client_id: str | None = Header(default=None),
                x_role: str | None = Header(default=None)):
    bad = check_role(x_role)
    if bad:
        return bad
    if x_client_id is None:
        return err(400, "client_id_required", "The X-Client-Id header is required.")
    if case_id not in CASES:
        return err(404, "case_not_found", f"No case with id {case_id}.")

    # ---- BREAK: pool --------------------------------------------------------
    # This customer's orders live on a shard whose connection pool leaks: a
    # connection is taken on every call and never returned, so the shard is
    # already exhausted and every request to it fails.
    #
    # Scoped to one case on purpose. It has to be independent of the rate-limit
    # counter - otherwise the load test that proves the 429 would trip this
    # instead, and two separate defects would arrive wearing each other's
    # clothes.
    #
    # It reads exactly like a transient upstream blip. It is not. It is
    # deterministic, and it will fail on the first call every single time.
    _orders_calls["n"] += 1
    # ---- BREAK: hang --------------------------------------------------------
    # The request is accepted and then never answered. The client gives up and
    # reports a timeout.
    #
    # This is the interesting one for triage, and the reason is what is ABSENT.
    # There is no status code, no body, no header, and no contract clause that
    # speaks to it - a timeout is not a documented response. So the only thing
    # anybody has to reason from is the SHAPE of the failure, and the shape of
    # a timeout is the shape of a bad afternoon on somebody else's cluster.
    #
    # It is not. It is deterministic. This endpoint will hang on every call,
    # today and next Tuesday. But nothing in the run says so - and an agent
    # asked to classify it will answer anyway, because it was asked to.
    if broken("hang") and case_id == "CASE-1002":
        _time.sleep(6)
        return err(504, "gateway_timeout", "Upstream timed out.")

    if broken("pool") and case_id == "CASE-1002":
        # Note how it presents itself: "temporarily", "please retry", and a
        # Retry-After header. Every signal a tired engineer reads as transient.
        # None of it is true. The pool is leaked and this will fail identically
        # on the tenth attempt and the ten thousandth.
        #
        # Services really do describe permanent faults in transient language,
        # because the code that writes the message does not know which it is.
        return err(503, "service_unavailable",
                   "Orders service temporarily unavailable. Please retry shortly.",
                   headers={"Retry-After": "5"})

    # The rate limit, counted per client over a rolling minute.
    window_start = datetime.now(timezone.utc) - timedelta(seconds=60)
    seen = [t for t in _rate.get(x_client_id, []) if t > window_start]
    seen.append(datetime.now(timezone.utc))
    _rate[x_client_id] = seen

    if len(seen) > RATE_LIMIT:
        # ---- BREAK: retry ---------------------------------------------------
        # The contract says a 429 MUST carry Retry-After. Without it a client
        # cannot know how long to wait, so it retries immediately and makes the
        # overload worse. The status code is right; the header is missing - the
        # kind of gap a status-code-only test will never see.
        headers = {} if broken("retry") else {"Retry-After": "60"}
        return err(429, "rate_limited",
                   f"More than {RATE_LIMIT} requests in one minute from this client.",
                   headers=headers)

    return ORDERS.get(case_id, [])


# =============================================================================
#  Test-support endpoint. Not in the contract, and deliberately so: it exists
#  for the runner to reset counters between suites, never for a real client.
# =============================================================================
@app.post("/_test/reset")
def _reset():
    for v in NOTES.values():
        v.clear()
    _rate.clear()
    _orders_calls["n"] = 0
    _seq["note"] = 0
    return {"reset": True, "breaks_armed": sorted(BREAKS) or ["none"]}


@app.get("/_test/health")
def _health():
    return {"ok": True, "breaks_armed": sorted(BREAKS) or ["none"]}
