# Build 2 fixture - a deliberately badly-described MCP server.
# Two tools over two tables the repository does not contain.
# The fix during the demo is three strings: a tool name, a description,
# and one line in the agent file. Nothing else changes.
#
# Requires:  pip install mcp
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("workitem")

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
def get_component_owner(query: str) -> str:
    """Returns the owning team, tech lead and on-call rota for one named component, such as
    orders-api or case-web. Use this whenever a story names a component and you need to say
    who would do the work. Do not use it to find stories or to search the backlog."""
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
