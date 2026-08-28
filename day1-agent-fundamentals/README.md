# day1-agent-fundamentals — an agent from its five parts

Day 1 builds an agent *inside a coding assistant* (GitHub Copilot, Claude
Code, or Codex — pick your lab) to make one point: an agent is not magic, it
is five designable parts — a model, a brief, standards to ground it, tools,
and a place to write its output.

The scenario: **story-check** — a user-story review agent. Stories land in
`intake/`; the agent reviews them against the team's Definition of Ready and
writes its reviews to `reviews/`.

## Layout

| Path | What it is |
|------|-----------|
| `story-check/` | the finished workspace — open THIS folder in your editor |
| `story-check/intake/` | two seeded user stories waiting for review |
| `story-check/standards/definition-of-ready.md` | the grounding — the standard the agent applies |
| `story-check/tools/workitem_server.py` | a tiny **MCP server** exposing the work items as tools |
| `story-check/.vscode/mcp.json` | wires the MCP server into the editor |
| `story-check/.github/instructions/` | the agent's standing instructions |
| `story-check/.github/agents/story-check.agent.md` | the agent definition itself |
| `01_graph_execution_model.md` | how an agent's loop actually executes — the day's theory note |
| `LAB_1_build_an_agent_*.md` | the lab, in three flavours: Copilot, Claude Code, Codex |
| `solutions/` | reference solutions — try the lab first |

## Using it

1. Open `story-check/` (that folder, not its parent) in VS Code / your
   assistant of choice.
2. `pip install mcp` if you want the tool-server part live.
3. Follow the LAB file for your assistant. The lab builds the agent up in
   the same order the course did: brief → grounding → tools → instructions.
4. Compare with `solutions/` when done.

The lesson that carries into Days 2–4: every part you just placed by hand —
the brief, the grounding, the tools, the answer shape — reappears as a
`create_agent(...)` argument in code.
