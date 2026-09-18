# Backend migration: Node.js/Express → Python/FastAPI

This document records what changed when Boppai's backend was reimplemented in Python,
and — more usefully for whoever maintains it next — *why* certain things were done the way
they were.

The scope was deliberately narrow: replace the backend runtime, keep everything else. The
React/Vite/Tailwind frontend was **not modified** (not one line). The agentic architecture,
the MCP architecture, the Swiggy/Zepto integrations, the Prava flow and the BrowserClaw
handoff are all structurally unchanged.

---

## 1. Architecture

Unchanged in shape; only the middle box is a different runtime.

```
React + Vite + Tailwind  (frontend/ — untouched)
        │  HTTP + SSE
        ▼
Python + FastAPI  (backend/)
        │
        ├── api/routes/     HTTP + SSE surface
        ├── services/       business logic
        ├── persistence/    SQLite + session files
        ├── agents/         CLI runtime: spawn, stream, parse, clean up
        │        ├── Claude CLI
        │        └── Codex CLI
        └── mcp/            Boppai MCP server + remote descriptors
                 ├── Boppai MCP (stdio, 10 tools)
                 └── Remote MCP via `npx mcp-remote`
                          ├── Swiggy Instamart
                          └── Zepto
        │
   SQLite + JSON + Markdown
        │
      Prava ──► BrowserClaw ──► merchant site
```

The load-bearing trick is preserved exactly: **the MCP tools do not write files.** They
call back into this same backend over `localhost`, so there is one normalizing write path
shared by both CLIs and the browser.

## 2. Layout

```
backend/
  app/
    main.py              app assembly + lifespan (a table of contents, nothing else)
    sse.py               SSE frame format
    core/                config (BaseSettings), logging, errors, boot, request helpers
    api/routes/          health detect tools mcp profile settings sessions
                         calendar basket prava chat
    services/            sessions profile settings calendar basket attachments
                         ingredients grocery oneshot prava prava_checkout remote_mcp
    agents/              base claude codex registry detect runner executable
                         streams/{claude,codex}
    mcp/                 servers (descriptors) tools (catalog) server (stdio entrypoint)
    models/              Pydantic wire models + the Session domain object
    persistence/         database (sqlite3) files (JSON/markdown)
  prompts/               boppai.md, basket-fill.md — copied byte-for-byte
  tests/                 112 tests
```

## 3. Technology mapping

| Node | Python | Note |
| --- | --- | --- |
| Express | FastAPI + `APIRouter` | one router per concern, same paths |
| Zod | Pydantic v2 | MCP tool schemas; `.describe()` → `Field(description=...)` verbatim |
| `child_process.spawn` | `asyncio.create_subprocess_exec` | see §6 |
| Node SSE (`res.write`) | `StreamingResponse` + async generator | see §7 |
| `better-sqlite3` | stdlib `sqlite3` | schema and migrations unchanged; no ORM needed |
| `@modelcontextprotocol/sdk` | `mcp` (official Python SDK, 2.x) | server + client |
| `fetch` | `httpx.AsyncClient` | Prava + MCP tool callbacks |
| `dotenv` | `pydantic-settings` | same variable names and defaults |
| Express middleware | FastAPI middleware + `Depends` | CORS, error handlers, body parsing |

Dependencies were chosen for a concrete reason each; nothing was added for fashion. There
is **no ORM, no PostgreSQL, no message broker, no container**.

## 4. API compatibility

All **45 routes** are preserved: same paths, methods, request bodies, response JSON and
status codes. A machine diff of the Express route table against the FastAPI OpenAPI schema
comes back identical — no extras, no omissions. See `backend/ENDPOINTS.md`.

Three contract details that a naive port silently breaks, and how each is handled:

1. **Error shape.** The frontend reads `data.error` everywhere. FastAPI's defaults
   (`{"detail": ...}` for `HTTPException`, 422 for validation) would break it. `core/errors.py`
   defines `BoppaiError` and overrides the validation handler so every failure is
   `{"error": ...}` at the status Express used. Where a Node route hand-checked a field and
   returned a specific message (`"Empty message"`, `"markdown (string) required"`,
   `"action must be clear_day or select_week"`), the Python route hand-checks identically
   rather than leaning on Pydantic.

2. **`req.body || {}`.** Every Express route tolerated a missing or malformed body. Declaring
   required Pydantic body models would turn that into a 422. `core/deps.py::json_body`
   reproduces the old behaviour.

3. **Empty env vars are falsy.** `.env.example` ships keys with empty values, and Node's
   `process.env.X || 'default'` treated `""` as unset. `core/config.py` strips blank values
   before validation so `PRAVA_BACKEND_URL=` still means "use the sandbox default".
   The obvious Python translation would have silently changed behaviour here.

## 5. MCP

Unchanged in architecture; reimplemented on the Python SDK.

**Boppai MCP** (`app/mcp/`) is still an agent-agnostic stdio server, launched by the CLI
as a subprocess. All **8 original tools** keep their names, schemas and semantics:
`get_profile`, `save_profile`, `show_chat`, `show_calendar`, `show_basket`,
`start_prava_checkout`, `get_prava_checkout_credential`, `report_prava_merchant_outcome`.
Two more were added afterwards for the Razorpay rail (§14): `start_razorpay_checkout` and
`get_razorpay_payment_status`.

Every tool `description` and every field description is copied **verbatim** from the Zod
definitions. These strings are not documentation — they are the instructions the agent reads
to decide what to do, so paraphrasing them would change product behaviour.

Two environment details are load-bearing for the spawned server:

- `PYTHONPATH` → `app.mcp.server` resolves whatever the child's cwd is.
- `PYTHONUTF8=1` → Windows would otherwise give the child a cp1252 stdout, and the JSON-RPC
  stream carries product names and prices full of characters like `₹`. Node's stdio was
  UTF-8 by default; Python's is not.

**Remote MCP** (Swiggy Instamart, Zepto) is unchanged: each is reached through
`npx mcp-remote <url>`, which bridges HTTP to stdio and owns the OAuth flow, caching tokens
under `~/.mcp-auth` — one login per server, shared between the probe and the CLI's chat-time
use. `services/remote_mcp.py` opens a short-lived client session to answer the Tools panel's
two questions (connected? which tools?) and reports failures without lying about
connectivity.

## 6. Agent runtime

`agents/runner.py` replaces the `spawn` + `.on('data')` callback style. FastAPI wants to
*pull* from an async iterator while the parsers *push* events, so a queue bridges them:

```
subprocess stdout → incremental UTF-8 decoder → parser → queue → async generator → SSE
```

Four things that are easy to get wrong and are handled explicitly:

- **Concurrency.** stdin writing, stdout reading and stderr reading run together in one task
  group. Sequencing them risks a deadlock: a large prompt can fill the pipe buffer while
  nobody is draining stdout.
- **Chunked decoding.** stdout is read in byte chunks (like Node's `chunk.toString()`), so a
  multi-byte character can straddle a chunk boundary. A plain per-chunk `bytes.decode()`
  would corrupt it; an incremental decoder is used instead.
- **Cleanup.** If the browser disconnects mid-turn the generator is closed, which raises at
  the `yield`. The `finally` terminates the child (escalating to kill after 5s), so a
  cancelled turn never orphans a `claude`/`codex` process. Verified by test.
- **Partial persistence.** Node's `close` handler still saved accumulated assistant text even
  after the SIGTERM it sent on disconnect. The Python generator persists in a `finally` for
  the same reason.

Both adapters keep their own quirks sealed in their own module: Claude's image-paths-in-the-
prompt trick, Codex's TOML escaping for `-c key=value`. One Python-specific trap worth
naming: `bool` is a subclass of `int`, so a naive `str(value)` would emit `True` instead of
TOML's `true` and silently disable a required MCP server. There is a test for it.

`services/oneshot.py` preserves the one-shot path as a genuinely separate mechanism: no
session, no MCP, no transcript — used for lazy day details and grocery-list consolidation.

## 7. SSE

The frontend hand-parses the stream (`frontend/src/api.js::readSseStream`): split on a blank
line, take the first line starting with `data:`. So the format is narrow and preserved
exactly — one JSON object per frame as `data: {...}\n\n`, no `event:`/`id:` fields, no
heartbeat comments, `ensure_ascii=False`.

That is why a plain `StreamingResponse` is used rather than `sse-starlette`, whose default
keep-alive comments would inject frames the Node backend never sent.

Event vocabulary is unchanged: `session`, `status`, `delta`, `tool`, `error`, `done`, `end`.
Claude's `mcp__<server>__<tool>` names are still stripped to the bare tool name so both
brains look identical to the frontend's surface switching.

## 8. Persistence

Nothing moved. SQLite stays SQLite; the files stay files.

- `data/boppai.db` — sessions, messages, settings. Same schema, same three `ALTER TABLE`
  migrations, same `runtime_session_id` backfill for pre-upgrade Claude sessions. An
  existing `boppai.db` is picked up and migrated exactly as before (there is a test that
  builds a legacy database and asserts this).
- `data/profile.md` — still a plain markdown file, because the Profile page lets the human
  edit it and the agent edits the same file through its tools.
- `sessions/<id>/` — `calendar.json`, `basket.json`, `ingredient-list.json`,
  `prava-checkout.json`, `attachments/`. Writers emit the same bytes Node did:
  `json.dumps(indent=2, ensure_ascii=False)` plus a trailing newline.
- Timestamps keep Node's `toISOString()` format (millisecond precision, trailing `Z`).

`better-sqlite3` was synchronous, so Node got serialization for free. Here a single
connection is shared with `check_same_thread=False` behind a lock — every statement is a
microsecond-scale local operation, so holding the lock inline is cheaper than a thread-pool
hop and keeps MCP callbacks, SSE writers and browser requests from interleaving mid-write.

## 9. Prava

The full flow is preserved, including its safeguards:

```
live merchant cart → explicit user confirmation → start_prava_checkout
 → credential polling → BrowserClaw handoff → merchant payment → report outcome
```

- `start_prava_checkout` is only reachable through the MCP tool, which `boppai.md` gates on an
  explicit confirmation after reading the **live** cart. Nothing in the backend
  short-circuits that.
- The one-time credential is never returned to the browser. It is served at
  `/internal/prava/checkout-credential`, which only the MCP subprocess calls.
- A merchant outcome can only be reported against the checkout **this session started** —
  the session id and txn ref are read from stored state, not from the caller.

**One deliberate deviation.** `backend-node-legacy/src/routes/prava.js:128` logged the full
PAN and dynamic CVV in cleartext under `[Prava DEBUG minted credential]`. The brief forbids
logging payment credentials, so the Python version keeps the trace (same trigger, same
dedupe, same `source` tag, same ids for support) but masks the card number to its last four
digits and redacts the CVV. Nothing functional changes — the unmasked credential still
reaches the MCP tool and BrowserClaw. There is a test asserting the raw values never appear
in the log.

## 10. Bug found and fixed during migration

`services/ingredients.py::fan_out` — **pre-existing in the Node build, not introduced here.**

The day-details prompt lists dishes as `- Oats (cook a batch of 1 serving)` and asks the
model to key its JSON by "each dish name EXACTLY as written above". The model reads that two
ways: sometimes the bare dish name, sometimes the whole bullet including the parenthetical.
Node looked up `parsed[dish.name]` strictly, so whenever the model chose the second reading
the lookup missed and the day's card rendered with **no ingredients, no nutrition and no
videos** — silently, with the "already generated" marker set so it never retried.

This was reproduced live during integration testing. The fix makes the lookup tolerant
(exact match first, then match after stripping the batch suffix, case-insensitively) rather
than editing the prompt, so the prompt stays byte-identical to the original. Four regression
tests cover it.

## 11. Known differences

Small, deliberate, and none of them frontend-visible:

| Area | Difference |
| --- | --- |
| Unknown routes | Express returned an HTML 404; FastAPI returns `{"error": "Not Found"}`. The frontend never requests unknown routes. |
| MCP config file | Written with a trailing newline. JSON parsers ignore it. |
| Remote MCP env | Node passed the child the entire `process.env`; the Python SDK passes a curated subset that still includes `PATH` and `USERPROFILE`/`APPDATA` (all `mcp-remote` needs for the token cache). Narrower, same behaviour. |
| Logging | All logs go to stderr (Node used stdout for the Prava trace), and stdio is forced to UTF-8. Both protect the MCP JSON-RPC stream. |
| Prava credential log | Masked — see §9. |

## 12. Environment variables

Unchanged in name, meaning and default. Copy `backend/.env.example` to `backend/.env`.

| Variable | Default | Purpose |
| --- | --- | --- |
| `PORT` | `8787` | The frontend defaults to this; change both if you move it. |
| `PRAVA_BACKEND_URL` | `https://sandbox.api.prava.space` | Prava API base. |
| `PRAVA_PUBLISHABLE_KEY` | *(empty)* | `pk_*` — sent to the browser. |
| `MERCHANT_SECRET_KEY` | *(empty)* | `sk_*` — **server-side only**. |
| `BOPPAI_PUBLIC_APP_URL` | *(empty)* | Prava callback URL. |
| `BOPPAI_USER_ID` | `boppai-local-user` | Payer id. |
| `BOPPAI_USER_EMAIL` | *(empty)* | Payer email; required for checkout. |
| `BROWSERCLAW_MCP_URL` | *(empty)* | When set, browser automation is wired into sessions and declared to the agent. |
| `RAZORPAY_KEY_ID` | *(empty)* | `rzp_test_*` for the free test-mode rail. |
| `RAZORPAY_KEY_SECRET` | *(empty)* | **Server-side only**; never sent to the browser. |
| `CORS_ALLOW_ORIGINS` | `*` | New, optional. Node hardcoded `*`; kept as the default for parity but now overridable instead of baked in. |

## 13. Running and testing

```bash
# first run
cd backend && python -m venv .venv && .venv/Scripts/pip install -r requirements.txt

# every run
cd backend && .venv/Scripts/python -m uvicorn app.main:app --port 8787

# frontend
cd frontend && npm install && npm run dev

# tests
cd backend && .venv/Scripts/python -m pytest
```

On macOS/Linux use `.venv/bin/...`.

## 14. Post-migration changes

Work done after the Node -> Python migration was verified complete. Recorded here because
these are the decisions a future maintainer will most want the reasoning for.

### Rebrand: Tomato Bag -> Boppai

Full rename across backend, frontend and docs: product name, env vars (`TOMATO_*` ->
`BOPPAI_*`), `tomato.db` -> `boppai.db`, the MCP server name `tomato` -> `boppai`, the
frontend design tokens `--color-tb-*` -> `--color-bp-*`, and the assistant persona
`Toto` -> `Boppai`.

The one trap worth knowing about: **"Tomato" is also a grocery ingredient in this
product.** Test fixtures, prompt examples and tool descriptions use `"Tomato"`,
`"Tomatoes"` and `"Fresh Tomatoes 1 kg"` as real shopping data. A blanket
find-and-replace would have silently corrupted the product's own semantics. The rebrand
script therefore swapped vegetable occurrences out for sentinels, ran the brand
replacements, then restored them — verified afterwards by asserting the ingredient
strings survived intact.

### Codex on Windows: a deploy-blocking bug, fixed

`codex` installs via npm as `codex.CMD`, a batch shim. `asyncio.create_subprocess_exec`
cannot execute a `.cmd` at all, and the previous fallback routed it through `cmd.exe /c`
— which re-parses argv quoting. Codex receives its entire MCP configuration as
`-c key="{...}"` TOML values packed with quotes, braces and backslashes, so that path
would have silently corrupted or dropped every MCP server on Windows.

`agents/executable.py` now parses the npm shim (it is a fixed template whose payload is
just `node <pkg>/bin/<name>.js %*`) and execs `node` directly with an argv array. No
shell, nothing to escape. `cmd.exe` remains only as a warned-about last resort for shims
that cannot be parsed.

Verified live: a real Codex turn through `/api/chat` with the full MCP config wired,
which called a Boppai MCP tool and returned the right answer.

### Browser automation is now declared per session

`boppai.md` instructs the agent to use BrowserClaw for the final merchant handoff, but
BrowserClaw is optional and unwired by default. Told to do something it has no tool for,
a model narrates the steps as though it had performed them — in the middle of a payment.

`_build_browser_block()` in `api/routes/chat.py` now states the capability explicitly each
turn, the same way the grocery provider is declared. When no browser tool is wired the
agent is told to hand the payment steps to the user and wait for them to report back,
which is something it can actually do.

### Second payment rail: Razorpay test mode

Prava stays as the hackathon integration. Razorpay test mode was added as the free path so
the payment flow remains demoable by anyone who clones the repo.

Design choices worth keeping:

- **Payment Links, not embedded checkout.** Boppai never sees a card; the user pays on
  Razorpay's hosted page. That keeps the rail free, needs no frontend SDK (the agent hands
  over a Markdown link in chat), and means there is no PAN or CVV anywhere to leak.
- **Amounts convert to integer paise in one tested function.** Razorpay works in the
  smallest currency unit, and being wrong by 100x is the classic bug on this API.
- **The rail is declared in the system prompt**, like the grocery provider. `boppai.md`
  used to say "Prava is the ONLY payment method", which stops being true with a second
  rail — so that section now defers to the per-session note, and the note also warns when
  the active rail has no credentials, so the agent says so instead of walking the user to
  a checkout that cannot complete.

## 15. Unresolved / not verified

Honest list. Nothing below was faked or asserted without evidence.

- ~~Codex end-to-end~~ **now verified.** Codex was installed and a real turn was run
  through `/api/chat` with MCP wired; see §14.
- **Prava credentialed flow.** The hackathon credentials no longer exist, so session
  creation, credential polling and outcome reporting have never been exercised against the
  real sandbox. Everything up to the network call is tested. Razorpay test mode exists as
  the working alternative.
- **Razorpay live call.** The client, amount conversion and payload shape are tested
  against a stubbed transport; no `rzp_test_*` keys were available, so no real Payment
  Link has been created.
- **Swiggy/Zepto tool execution.** Both remotes require an OAuth login that has not been
  performed here. The transport is proven working (the probe reaches Zepto's auth server and
  is refused with HTTP 403 on dynamic client registration), but no grocery search, cart
  operation or order has been run.
- **BrowserClaw handoff.** `BROWSERCLAW_MCP_URL` is unset, so the final-mile browser
  automation was never exercised.
- **Node A/B comparison.** The original backend cannot run on this machine:
  `better-sqlite3@11.10.0` has no prebuilt binary for Node v24 and requires MSVC build
  tools, so `npm install` fails. Contract equivalence was therefore established by reading
  the Express source and encoding it as tests, not by diffing two live servers. (A side
  benefit of the migration: the Python backend has no native build step.)
- **`backend-node-legacy/`** is retained as reference. It can be deleted once you are
  satisfied; it is kept because this working copy has no git history to recover it from.
