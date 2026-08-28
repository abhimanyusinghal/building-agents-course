"""
===============================================================================
 INVENTORY  —  the fleet register, ENFORCED rather than decorative
===============================================================================

    python fleet/inventory.py

Prints every agent in the fleet and lints the three mandatory fields:
owner, identity, cost cap. A register nobody checks rots into a wiki page;
this one fails loudly the moment a row is incomplete — so "every agent has
an owner and its own identity" is a build check, not a policy hope.

The identity column is the day's quiet headline: credentials that belong to
THE AGENT. Revoke that row and the agent stops — and no person loses access.
===============================================================================
"""
import sys
from pathlib import Path

HERE = Path(__file__).parent

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def parse(path):
    """A deliberately tiny YAML reader for exactly this file's shape —
    the inventory format is simple enough that no library is needed."""
    agents, current = [], None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("- agent:"):
            current = {"agent": line.split(":", 1)[1].strip()}
            agents.append(current)
        elif current is not None and ":" in line and not line.startswith("#"):
            k, _, v = line.partition(":")
            current[k.strip()] = v.strip().strip('"')
    return agents


REQUIRED = ["owner", "identity", "cost_cap_usd_per_day"]


def main():
    agents = parse(HERE / "inventory.yaml")
    print(f"the fleet — {len(agents)} agents registered\n")
    print(f"{'agent':<18} {'day':>3} {'model':<13} {'ver':<4} {'cap/day':>8}  owner · identity")
    print("-" * 100)
    problems = 0
    for a in agents:
        missing = [k for k in REQUIRED if not a.get(k)]
        mark = "  " if not missing else "!!"
        ident = a.get("identity", "-")
        print(f"{mark}{a['agent']:<16} {a.get('day','-'):>3} {a.get('model','-'):<13} "
              f"{a.get('prompt_version','-'):<4} {'$' + a.get('cost_cap_usd_per_day','?'):>8}  "
              f"{a.get('owner','-')} · {ident[:52]}")
        if missing:
            problems += 1
            print(f"   ^ MISSING: {', '.join(missing)}")
    print("-" * 100)
    if problems:
        print(f"\n{problems} agent(s) incomplete. An agent without an owner and its own "
              f"identity does not go past this line.")
        raise SystemExit(1)
    print("\nEvery agent has an owner, an identity of its own, and a cost cap. "
          "The fleet may run.")


if __name__ == "__main__":
    main()
