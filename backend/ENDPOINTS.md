# Backend Endpoints

All 52 routes the FastAPI backend serves. Paths, methods, bodies and status codes are
unchanged from the Node/Express build — the React frontend talks to this backend without
any modification.

Two families:

- **`/api/*`** — the browser-facing API.
- **`/internal/*`** — called by the bundled MCP tool subprocess over `localhost`. These
  are what give the app a single write path shared by both CLIs and the browser. Not
  meant for the browser.

Errors are always `{"error": "..."}` with the status listed. The Prava routes may also
include `code` and `responseId` passed through from Prava.

## Health & detection

| Method | Endpoint | Body / Params | Description |
| --- | --- | --- | --- |
| GET | `/api/health` | — | Liveness check. Returns `{ ok: true }`. |
| GET | `/api/detect` | — | Probes each agent: `{ agents: [{ id, name, tagline, bin, supportsImages, installed, version, loggedIn, account }] }`. Runs `<bin> --version` then the auth probe. |

## Chat (Server-Sent Events)

All three stream `data: {...}\n\n` frames. Event types: `session`, `status`, `delta`,
`tool`, `error`, `done`, then a final `end`.

| Method | Endpoint | Body | Description |
| --- | --- | --- | --- |
| POST | `/api/chat` | `agent`, `message`, optional `images[]` (data URLs) | Sends a user turn to the active session. Spawns the CLI, streams the reply. 400 on `Empty message`, unknown agent, image errors, or an agent that can't take images. |
| POST | `/api/chat/opening` | `agent` | Lets the CLI write the first assistant message. 409 `Session already has messages`. |
| POST | `/api/chat/internal-handoff` | `agent`, `message`, `transcriptMessage` | Prava credential handoff: the model receives `message` (browser instructions); the transcript shows `transcriptMessage`. 400 on an empty message. |

## Sessions

| Method | Endpoint | Body / Params | Description |
| --- | --- | --- | --- |
| GET | `/api/session/current` | — | The active session: `{ sessionId, agentSessionId, name, agent, activeSurface, profileExists, messages }`. Creates one if none exists. |
| POST | `/api/session/new` | — | Archives the active session and returns a fresh one (same shape). |
| PATCH | `/api/session/surface` | `activeSurface` (`chat`\|`calendar`\|`basket`) | Switches the visible surface. 400 on an unknown surface. |
| GET | `/api/sessions` | — | Every session for the history view: `{ sessions: [{ id, title, name, status, created_at, ended_at, message_count }] }`. |
| GET | `/api/sessions/{id}/messages` | path `id` | One session's transcript. |
| GET | `/api/sessions/{id}/attachments/{file}` | path `id`, `file` | Serves a saved image attachment. 404 for unknown session/file or any path outside the session folder. |
| POST | `/internal/surface` | `activeSurface` | Same switch, for the `show_chat` MCP tool. Returns `{ ok, activeSurface }`. |

## Profile

| Method | Endpoint | Body | Description |
| --- | --- | --- | --- |
| GET | `/api/profile` | — | `{ exists, markdown, name }`. `name` is the first `#` heading. |
| PUT | `/api/profile` | `markdown` | Saves `data/profile.md`, syncs the active session's name. 400 `markdown (string) required`. |
| GET | `/internal/profile` | — | Same read, for `get_profile`. |
| POST | `/internal/profile` | `markdown` | Same write, for `save_profile`. |

## Settings

| Method | Endpoint | Body | Description |
| --- | --- | --- | --- |
| GET | `/api/settings/agent` | — | `{ agent: "claude" \| "codex" \| null }`. |
| PUT | `/api/settings/agent` | `agent` | Saves the pick. 400 `Unknown agent: <x>`. |
| GET | `/api/settings/provider` | — | `{ provider }`, defaulting to `swiggy-instamart`. |
| PUT | `/api/settings/provider` | `provider` | Saves the grocery source. 400 `Unknown provider: <x>`. |
| GET | `/api/settings/payment-provider` | — | `{ provider, configured, providers[] }` — the active payment rail plus whether each has credentials. |
| PUT | `/api/settings/payment-provider` | `provider` (`prava`\|`razorpay`) | Switches the rail. 400 `Unknown payment provider: <x>`. |

## Meal planner calendar

| Method | Endpoint | Body | Description |
| --- | --- | --- | --- |
| GET | `/api/session/calendar` | — | `{ exists, calendar }` for the active session. |
| PATCH | `/api/session/calendar` | `action` = `clear_day` (+`weekId`,`day`) or `select_week` (+`weekId`) | Manual edits. 400 on a bad action or missing week. |
| POST | `/api/session/calendar/details` | `weekId`, `day`, optional `force` | **Real agent call.** Lazily generates and caches ingredients, nutrition and recipe videos for one day. Idempotent — already-generated meals are skipped. |
| POST | `/api/session/calendar/grocery-list` | — | **Real agent calls.** Generates any missing day details (3 at a time), dedups cook-once batches, merges quantities, classifies `basket`/`pantry`, saves `ingredient-list.json`. Returns `{ items, calendar }`. Slow when many days are ungenerated. |
| GET | `/internal/calendar` | — | Same read, for the MCP tool. |
| POST | `/internal/calendar` | `weeks[]`, optional `ui` | `show_calendar`'s write. Replaces the whole planner and switches the surface. Returns `{ ok, calendar }`. |

## Basket

The app-side Basket (`basket.json`) — **not** the user's real Swiggy/Zepto cart.

| Method | Endpoint | Body | Description |
| --- | --- | --- | --- |
| GET | `/api/session/basket` | — | `{ exists, basket }`. |
| PATCH | `/api/session/basket` | `action` = `set_count` (+`ingredient`,`count`) or `remove` (+`ingredient`) | The card stepper and X. 400 on a bad action or unknown ingredient. |
| GET | `/api/session/ingredient-list` | — | `{ items: [{ name, quantity, category }] }` — the consolidated shopping list. |
| POST | `/api/session/basket/fill` | — | **SSE.** Runs an ephemeral sourcing agent over the perishable items; it calls `show_basket` as it goes so cards appear one at a time. Errors arrive as SSE frames, not HTTP errors. |
| POST | `/api/session/basket/source-item` | `ingredient` | **SSE.** Sources one item and upserts it — promotes a pantry staple or retries a miss. |
| GET | `/internal/basket` | — | Same read, for the MCP tool. |
| POST | `/internal/basket` | `items[]` | `show_basket`'s write. Replaces the whole Basket and switches the surface. |

## MCP

| Method | Endpoint | Params | Description |
| --- | --- | --- | --- |
| GET | `/api/tools` | — | The bundled Boppai MCP's 8 tools (static metadata, instant). |
| GET | `/api/mcp/remote` | — | Remote servers as metadata only: `{ servers: [{ name, label, description, login }] }`. |
| GET | `/api/mcp/remote/{name}/tools` | path `name` | **Live probe.** Opens a throwaway MCP session via `npx mcp-remote`, lists tools, closes. Returns `{ connected, tools, login, error? }`. Takes a few seconds; 20s timeout. 404 for an unknown server. |

## Prava payments

The browser only ever receives the publishable key and the session token/iframe URL.
`MERCHANT_SECRET_KEY` stays server-side. The one-time card credential is never returned to
the browser — it goes to the MCP tool and on to BrowserClaw.

| Method | Endpoint | Body / Params | Description |
| --- | --- | --- | --- |
| GET | `/api/prava/config` | — | `{ publishableKey, configured, appUrl }`. |
| GET | `/api/prava/health` | — | `{ healthy }` — upstream reachability. |
| POST | `/api/prava/create-session` | payment fields | Creates a Prava session (sandbox panel). |
| GET | `/api/session/prava-checkout` | — | `{ exists, checkout }` — the session-scoped checkout intent the iframe reads. |
| GET | `/api/prava/payment-result/{sessionId}` | path `sessionId` | Polls the payment result. 500 without a valid `sk_` key. |
| POST | `/api/prava/report-status` | `sessionId`, `txnRefId`, `txnStatus` (+optional) | Reports an outcome. 400 on missing/invalid fields. |
| POST | `/internal/prava/start-checkout` | `totalAmount`, optional `currency`, `description`, `products[]` | `start_prava_checkout`. Creates the Prava session server-side and opens the panel. |
| GET | `/internal/prava/checkout-credential` | — | `get_prava_checkout_credential`. Returns the one-time card credential for the active checkout. 409 while not ready (the tool polls), 404 with no active checkout. |
| POST | `/internal/prava/report-merchant-outcome` | `txnStatus`, optional `observation`, `buttonState`, `pageState` | `report_prava_merchant_outcome`. Reports the observed Swiggy result. The session and txn ref come from the stored checkout, not the caller. |

## Razorpay payments (test mode)

The free payment rail. Boppai never handles card data here — the user pays on Razorpay's
own hosted Payment Link page, and all Boppai stores is the link id and its status. Test
keys (`rzp_test_*`) move no real money.

| Method | Endpoint | Body / Params | Description |
| --- | --- | --- | --- |
| GET | `/api/razorpay/config` | — | `{ configured, testMode, keyId }`. Only the publishable key id is exposed; the secret never leaves the server. |
| GET | `/api/session/razorpay-checkout` | — | `{ exists, checkout }` — the session's active payment link. |
| GET | `/api/razorpay/payment-status/{linkId}` | path `linkId` | Polls one link: `{ id, status, paid, amountPaid, ... }`. |
| POST | `/internal/razorpay/start-checkout` | `totalAmount`, optional `currency`, `description`, `products[]` | `start_razorpay_checkout`. Creates the link and stores it on the session. 500 without `rzp_*` keys. |
| GET | `/internal/razorpay/payment-status` | — | `get_razorpay_payment_status`. Polls this session's link. 404 when no checkout was started. |
