"""
===============================================================================
 THE RUNNER  —  machinery. Read this file for what is NOT in it.
===============================================================================

It issues each request and checks the answer. That is all it does.

WHY THIS FILE HAS NO MODEL IN IT
    Look at the imports. There is no agent here, no model, no prompt, no
    Azure endpoint, nothing that costs a penny to run.

    Issuing an HTTP request is not a judgement call. Comparing 201 to 201 is
    not a judgement call. Validating a response body against a JSON schema is
    not a judgement call. All three have exactly one right answer and a machine
    that gets them wrong is broken, not creative.

    Putting a model here would make the suite slower, more expensive, and -
    the part that matters - NON-DETERMINISTIC. A test that might disagree with
    itself on a re-run is not a test. It is an opinion with a stack trace.

    Deciding WHICH cases are worth writing is judgement, and an agent does it.
    Deciding WHY a run went red is judgement, and an agent does it. This step
    is in between, and it is machinery on purpose.

WHAT IT CHECKS, PER CASE
    1. the status code matches
    2. every header the contract marks required is actually present
    3. the response body validates against the contract's schema

    Two and three are where most of the value is. A status-code-only suite
    passes happily while the body quietly loses a field and a required header
    goes missing - which is exactly one of the defects waiting in this fixture.
===============================================================================
"""
import argparse
import json
import time
from pathlib import Path

import requests
from jsonschema import Draft202012Validator

import ledger

HERE = Path(__file__).parent
CONTRACT = json.loads((HERE / "contract/openapi.json").read_text(encoding="utf-8"))
BASE = CONTRACT["servers"][0]["url"]
OUT = HERE / "out"



def _deref(node, depth=0):
    """Inline the contract's internal references.

    The contract says things like {"$ref": "#/components/schemas/Note"} - a
    pointer to a shape defined once and reused. Before we can check a response
    against it, those pointers have to be followed and replaced by what they
    point at. Every reference in this contract is local to the document, so
    following them is a walk, not a fetch.
    """
    if depth > 20:
        return node
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/"):
            target = CONTRACT
            for part in ref[2:].split("/"):
                target = target[part]
            return _deref(target, depth + 1)
        return {k: _deref(v, depth + 1) for k, v in node.items()}
    if isinstance(node, list):
        return [_deref(v, depth + 1) for v in node]
    return node


# =============================================================================
#  CHECKING A RESPONSE AGAINST THE CONTRACT
# =============================================================================
def _schema_for(method: str, path_template: str, status: int):
    """The response schema the contract promises for this call, if it names one."""
    op = CONTRACT["paths"].get(path_template, {}).get(method.lower())
    if not op:
        return None
    resp = op.get("responses", {}).get(str(status))
    if not resp:
        return None
    return resp.get("content", {}).get("application/json", {}).get("schema")


def _required_headers(method: str, path_template: str, status: int):
    """Headers the contract marks required on this response. Missing one is a break."""
    op = CONTRACT["paths"].get(path_template, {}).get(method.lower())
    if not op:
        return []
    resp = op.get("responses", {}).get(str(status), {})
    return [name for name, spec in (resp.get("headers") or {}).items() if spec.get("required")]


def _short(value, limit=120):
    """Keep evidence readable.

    A boundary case sends 4001 characters and the API echoes them back. Printing
    that to a projector is useless, and feeding it to the triage agent is worse:
    it pays for four thousand x characters and reads nothing it did not already
    know from the length.
    """
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    if len(text) <= limit:
        return value if not isinstance(value, str) else text
    return f"{text[:limit]}… [{len(text)} characters in total]"


def _shorten_body(body):
    """Same idea, applied to every string inside a response body."""
    if isinstance(body, dict):
        return {k: _shorten_body(v) for k, v in body.items()}
    if isinstance(body, list):
        return [_shorten_body(v) for v in body[:5]]
    if isinstance(body, str):
        return _short(body)
    return body


def _validate_body(schema, body):
    """Does the body match the shape the contract promised? Returns a reason, or None."""
    if schema is None or body is None:
        return None
    validator = Draft202012Validator(_deref(schema))
    errors = sorted(validator.iter_errors(body), key=lambda e: list(e.path))
    if not errors:
        return None
    first = errors[0]
    where = "/".join(str(p) for p in first.path) or "(root)"
    return f"body does not match the contract at {where}: {_short(first.message, 100)}"


# =============================================================================
#  RUNNING ONE CASE
# =============================================================================
def run_case(case: dict) -> dict:
    """Issue the request (as many times as the case asks), then check the answer."""
    started = time.time()
    method = case["method"].upper()
    path = case["path"]
    repeat = int(case.get("repeat", 1))

    # A case that needs a 4001-character note does not write 4001 characters into
    # its own definition - it says {"field": "text", "length": 4001} and the
    # runner builds the value. The agent chooses the boundary; machinery makes
    # the data. Keeping it that way round is why the case files stay readable.
    body = case.get("body")
    fill = case.get("fill")
    if fill and isinstance(body, dict) and fill.get("field") and fill.get("length"):
        body = {**body, fill["field"]: (fill.get("char") or "x") * int(fill["length"])}

    response = None
    try:
        for _ in range(repeat):
            response = requests.request(
                method, BASE + path,
                json=body,
                headers={"Content-Type": "application/json", **(case.get("headers") or {})},
                timeout=3,
            )
    except requests.RequestException as error:
        return {**case, "outcome": "error", "seconds": round(time.time() - started, 3),
                "reason": f"the request never completed: {type(error).__name__}",
                "actual_status": None, "actual_body": None, "actual_headers": {}}

    try:
        body = response.json()
    except ValueError:
        body = None

    seconds = round(time.time() - started, 3)
    common = {**case, "seconds": seconds, "actual_status": response.status_code,
              "actual_body": _shorten_body(body),
              "actual_headers": {k: v for k, v in response.headers.items()
                                 if k.lower() in ("retry-after", "content-type")}}

    # 1. the status code
    if response.status_code != case["expect_status"]:
        return {**common, "outcome": "fail",
                "reason": f"expected HTTP {case['expect_status']}, got {response.status_code}"}

    # 2. headers the contract marks required
    template = case.get("path_template", path)
    missing = [h for h in _required_headers(method, template, response.status_code)
               if h.lower() not in {k.lower() for k in response.headers}]
    # a case may also name its own header expectations
    missing += [h for h in (case.get("expect_headers") or [])
                if h.lower() not in {k.lower() for k in response.headers} and h not in missing]
    if missing:
        return {**common, "outcome": "fail",
                "reason": f"the contract requires the header(s) {', '.join(missing)} "
                          f"on a {response.status_code}, and the response did not carry them"}

    # 3. the body's shape
    reason = _validate_body(_schema_for(method, template, response.status_code), body)
    if reason:
        return {**common, "outcome": "fail", "reason": reason}

    # 4. named body fields, when the case asks for them
    for field, want in (case.get("expect_body") or {}).items():
        got = (body or {}).get(field)
        if got != want:
            return {**common, "outcome": "fail",
                    "reason": f"expected {field}={want}, got {field}={got}"}

    return {**common, "outcome": "pass", "reason": ""}


# =============================================================================
#  RUNNING A SUITE
# =============================================================================
def load_cases(include_regression=True) -> list[dict]:
    """The generated cases, plus the suite the team already had.

    Both run. An agent that writes tests does not replace the tests you have -
    the regression file is where a team's hard-won cases live, and some of them
    are older than the contract they were written against.
    """
    cases = []
    # The PINNED suite is what runs - a file that was reviewed and committed.
    # out/cases.json is only ever the output of a generation, waiting to be
    # reviewed. If the thing you run is regenerated on every run, your coverage
    # changes on every run, and a green build stops meaning anything.
    pinned = HERE / "suite.json"
    source = pinned if pinned.exists() else (OUT / "cases.json")
    if source.exists():
        payload = json.loads(source.read_text(encoding="utf-8"))
        tag = "pinned" if source is pinned else "UNPINNED"
        for c in (payload["cases"] if isinstance(payload, dict) else payload):
            cases.append({**c, "source": tag})
    if include_regression:
        legacy = json.loads((HERE / "regression-cases.json").read_text(encoding="utf-8"))
        for c in legacy["cases"]:
            cases.append({**c, "source": "regression"})
    return cases


def main():
    ap = argparse.ArgumentParser(description="Run the suite. No model involved.")
    ap.add_argument("--no-regression", action="store_true",
                    help="generated cases only")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--isolate", action="store_true",
                    help="reset the server between every case. A suite that passes "
                         "isolated and fails in sequence has order dependence, and "
                         "the difference between the two runs is the list of them.")
    args = ap.parse_args()

    try:
        requests.post(f"{BASE}/_test/reset", timeout=5)
    except requests.RequestException:
        print(f"The API is not answering on {BASE}.")
        print("Start it with:  python -m uvicorn api.app:app --port 8742")
        raise SystemExit(1)

    cases = load_cases(include_regression=not args.no_regression)
    if not cases:
        print("No cases to run. Generate some first:  python -m agents.generate")
        raise SystemExit(1)

    print(f"running {len(cases)} cases against {BASE}\n")
    results, started = [], time.time()
    for case in cases:
        if args.isolate:
            requests.post(f"{BASE}/_test/reset", timeout=5)
        r = run_case(case)
        results.append(r)
        mark = {"pass": "  ok  ", "fail": " FAIL ", "error": " ERR  "}[r["outcome"]]
        if not args.quiet or r["outcome"] != "pass":
            print(f"{mark} {r['name'][:58]:<58} {r.get('source','')}")
            if r["outcome"] != "pass":
                print(f"        {r['reason']}")
        # Machinery costs nothing, and the ledger says so out loud.
        ledger.record(r["name"], "run_case", r["seconds"], note=r["outcome"])

    passed = sum(1 for r in results if r["outcome"] == "pass")
    failed = len(results) - passed
    OUT.mkdir(exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(
        {"base_url": BASE, "total": len(results), "passed": passed, "failed": failed,
         "seconds": round(time.time() - started, 2), "results": results},
        indent=2), encoding="utf-8")

    print(f"\n{passed} passed, {failed} failed, in {time.time() - started:.1f}s")
    print(f"written to out/results.json")
    if failed:
        print(f"\n{failed} failures need a decision. That is the next agent's job:")
        print("    python -m agents.triage")


if __name__ == "__main__":
    main()
