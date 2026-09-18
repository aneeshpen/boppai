# Working rules for Boppai (read every session — non-negotiable)

## RULE 0 — Do NOT modify anything until we plan AND the user says "go"
This is the most important rule and I have broken it before. Follow it exactly:

- **No writing, editing, or creating code/config files. No state-changing commands
  (npm install, starting servers, git, moving/deleting files). NOTHING that changes
  the system** — until BOTH are true:
  1. We have **completely planned** the change together, and
  2. The user gives an **explicit, unambiguous go** ("go", "yes build it", "implement now").
- A mid-conversation "**do it**", "**do category X**", "sure", or any partial/implied
  approval is **NOT** the go signal on its own. When in doubt, ASK: "Ready for me to
  implement this now?" and wait.
- **Default mode is research + explain + plan.** Read-only actions (reading files,
  searching, spawning read-only Explore agents, `--help`/`--version` probes) are fine.
  Anything that writes or changes state is not, until Rule 0 is satisfied.
- If the user asks "how does X work / what should we do", that is a request to
  **explain**, not to build. Explain, then propose a plan, then stop and wait.

## Mermaid diagrams are load-bearing — never remove, always ask
- The `.md` files carry mermaid diagrams that ARE the picture of the architecture:
  `README.md` and `knowledge/02-architecture-and-stack.md`. **Never delete or
  silently break a diagram.**
- Whenever a change touches architecture, data flow, storage, or session/profile/turn
  behavior — anything a diagram depicts — **STOP and ask:** "Do you also want the mermaid
  diagram(s) updated? Affected: &lt;list&gt;." Don't regenerate a diagram without an explicit yes.
- When editing any `.md` that contains a mermaid block, preserve every existing block
  unless explicitly told to change it.

## After implementing — offer to save important decisions to the knowledge base
This runs at the **end of the work, after code is actually written/implemented** (not
before — the "go" rule above still gates all changes). Once a change is done:
- Look back over THIS chat for **decisions worth keeping** — architectural choices,
  important current decisions, or **future notes** ("we'll implement X this way later")
  that other agents/threads would benefit from and that belong in `knowledge/`.
- **Only genuinely important stuff.** No trivia, no restating what the code/diagrams
  already show, no obvious or throwaway details.
- Then **ask, don't write**: "Now that the code's done, here are a few things I found that
  might be worth saving to the knowledge base: &lt;short list&gt;. Want me to write these in?"
  Only touch `knowledge/*.md` after an explicit yes (per the knowledge-base rule below).
- If nothing rises to that bar, say so briefly and don't ask.

## How the user works (honor these)
- **Plan fully before any code.** He wants complete clarity and to decide before we build.
  He reads the code himself and is the sole dev.
- **Dummy-data first**, then swap in real AI/MCP/payment one integration at a time.
- **Conserve AI credits.** Prefer designs with dummy/record/replay; spawning the local
  CLI uses his subscription (fine for dev), API keys cost money (avoid).
- **Readable code, light separation of concerns.** Small focused files, plain-English
  "why" explanations, not over-engineered.
- **Be honest and upfront**, including doubts. Distinguish clearly between current
  behavior, proposed changes, and open questions. Don't race ahead of agreed decisions.
- **Do not edit the `knowledge/*.md` files or memory MD files unless explicitly asked.**
  He will say "write to the MD files" when he wants them synced.

## Project context (source of truth)
- This is **Boppai** — a local, per-user **harness** (downloadable GitHub repo) that
  attaches to the user's own installed `claude`/`codex` CLI. Not a hosted server.
- Detailed, living context lives in **`knowledge/`** (read `knowledge/README.md` first).
- Current app code: `backend/` (Node/Express, spawns the CLI, streams over SSE) and
  `frontend/` (React + Vite + Tailwind). Detect → pick agent → chat.
