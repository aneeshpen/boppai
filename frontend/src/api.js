// Thin client for the backend: detect agents, drive the active session, stream chat,
// and read/write the profile + session history.

// The frontend talks to the backend directly (no Vite proxy). Defaults to the local
// backend; set VITE_API_URL at build time to point somewhere else.
const BASE = import.meta.env.VITE_API_URL || 'http://localhost:8787';

export function apiUrl(path) {
  if (!path) return '';
  if (/^https?:\/\//i.test(path)) return path;
  return `${BASE}${path}`;
}

async function readSseStream(res, onEvent) {
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let idx;
    while ((idx = buffer.indexOf('\n\n')) !== -1) {
      const frame = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      const dataLine = frame.split('\n').find((l) => l.startsWith('data:'));
      if (!dataLine) continue;
      try {
        onEvent(JSON.parse(dataLine.slice(5).trim()));
      } catch {
        /* ignore malformed frame */
      }
    }
  }
}

export async function detectAgents() {
  const res = await fetch(`${BASE}/api/detect`);
  if (!res.ok) throw new Error(`detect failed (${res.status})`);
  const data = await res.json();
  return data.agents;
}

/* --- tools (what our bundled MCP exposes) --- */

export async function getTools() {
  const res = await fetch(`${BASE}/api/tools`);
  if (!res.ok) throw new Error(`tools failed (${res.status})`);
  return res.json(); // { servers: [{ name, label, description, tools: [...] }] }
}

// The remote MCP servers (Zepto, Swiggy Instamart, ...) as metadata only — instant.
export async function getRemoteMcpServers() {
  const res = await fetch(`${BASE}/api/mcp/remote`);
  if (!res.ok) throw new Error(`remote MCP list failed (${res.status})`);
  return res.json(); // { servers: [{ name, label, description, login }] }
}

// Live probe of ONE remote MCP: opens a throwaway session, so it takes a few
// seconds and can report `connected: false` when the user hasn't logged in.
export async function getRemoteMcpTools(name, { signal } = {}) {
  const res = await fetch(`${BASE}/api/mcp/remote/${name}/tools`, { signal });
  if (!res.ok) throw new Error(`remote MCP tools failed (${res.status})`);
  return res.json(); // { connected, tools: [...], login, error? }
}

/* --- session --- */

export async function getCurrentSession({ signal } = {}) {
  const res = await fetch(`${BASE}/api/session/current`, { signal });
  if (!res.ok) throw new Error(`session failed (${res.status})`);
  return res.json();
}

export async function newSession() {
  const res = await fetch(`${BASE}/api/session/new`, { method: 'POST' });
  if (!res.ok) throw new Error(`new session failed (${res.status})`);
  return res.json();
}

export async function listSessions() {
  const res = await fetch(`${BASE}/api/sessions`);
  if (!res.ok) throw new Error(`list failed (${res.status})`);
  const data = await res.json();
  return data.sessions;
}

export async function getSessionMessages(id) {
  const res = await fetch(`${BASE}/api/sessions/${id}/messages`);
  if (!res.ok) throw new Error(`transcript failed (${res.status})`);
  const data = await res.json();
  return data.messages;
}

export async function getSessionCalendar({ signal } = {}) {
  const res = await fetch(`${BASE}/api/session/calendar`, { signal });
  if (!res.ok) throw new Error(`calendar failed (${res.status})`);
  const data = await res.json();
  return data.calendar || null;
}

export async function getSessionBasket({ signal } = {}) {
  const res = await fetch(`${BASE}/api/session/basket`, { signal });
  if (!res.ok) throw new Error(`basket failed (${res.status})`);
  const data = await res.json();
  return data.basket || null;
}

export async function clearCalendarDay({ weekId, day }) {
  const res = await fetch(`${BASE}/api/session/calendar`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action: 'clear_day', weekId, day }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `calendar edit failed (${res.status})`);
  return data.calendar || null;
}

// Ask the backend to generate (and cache) ingredients + nutrition for one day's
// meals. Real agent call — can take a few seconds; idempotent on re-open.
export async function generateDayDetails({ weekId, day, force = false }) {
  const res = await fetch(`${BASE}/api/session/calendar/details`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ weekId, day, force }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `details failed (${res.status})`);
  return data.calendar || null;
}

// Consolidate the whole calendar into one grocery list. Real agent call — ensures
// every day's ingredients exist first, so it can take a while. Returns
// { items, calendar, message }; the backend also posts `message` into chat.
export async function buildGroceryList() {
  const res = await fetch(`${BASE}/api/session/calendar/grocery-list`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `grocery list failed (${res.status})`);
  return data;
}

export async function selectCalendarWeek({ weekId }) {
  const res = await fetch(`${BASE}/api/session/calendar`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action: 'select_week', weekId }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `calendar edit failed (${res.status})`);
  return data.calendar || null;
}

// The consolidated shopping list ([{ name, quantity }]) the Basket is filled from.
// The Basket's "still processing" group is derived from what's here but not yet in the
// Basket, so the frontend needs it up front.
export async function getIngredientList({ signal } = {}) {
  const res = await fetch(`${BASE}/api/session/ingredient-list`, { signal });
  if (!res.ok) throw new Error(`ingredient list failed (${res.status})`);
  const data = await res.json();
  return data.items || [];
}

// Direct UI edit — set how many packs of a found Basket item to buy (min 1).
export async function setBasketCount({ ingredient, count }) {
  const res = await fetch(`${BASE}/api/session/basket`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action: 'set_count', ingredient, count }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `basket edit failed (${res.status})`);
  return data.basket || null;
}

// Direct UI edit — drop a Basket line by ingredient name.
export async function removeBasketItem({ ingredient }) {
  const res = await fetch(`${BASE}/api/session/basket`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action: 'remove', ingredient }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `basket edit failed (${res.status})`);
  return data.basket || null;
}

// Run the fill agent (SSE): it sources each ingredient on the connected provider and
// calls show_basket as it goes, so the Basket fills in live. `onEvent` receives the same
// normalized events as chat — we only act on the show_basket tool events.
export async function streamFillBasket({ onEvent, signal }) {
  const res = await fetch(`${BASE}/api/session/basket/fill`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    signal,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || `basket fill failed (${res.status})`);
  }
  await readSseStream(res, onEvent);
}

// Source a single item and upsert it into the Basket — the + on a pantry staple tag
// and the retry on a not-found tag both use this. Streams like the fill: the agent
// searches this one item and show_basket merges it into the Basket.
export async function streamSourceItem({ ingredient, onEvent, signal }) {
  const res = await fetch(`${BASE}/api/session/basket/source-item`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ingredient }),
    signal,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || `source item failed (${res.status})`);
  }
  await readSseStream(res, onEvent);
}

export async function setActiveSurface(activeSurface) {
  const res = await fetch(`${BASE}/api/session/surface`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ activeSurface }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `surface edit failed (${res.status})`);
  return data.activeSurface || activeSurface;
}

/* --- Prava payments --- */

export async function getPravaConfig() {
  const res = await fetch(`${BASE}/api/prava/config`);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `prava config failed (${res.status})`);
  return data;
}

export async function createPravaSession(payload = {}) {
  const res = await fetch(`${BASE}/api/prava/create-session`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `prava session failed (${res.status})`);
  return data;
}

export async function getPravaPaymentResult(sessionId) {
  const res = await fetch(`${BASE}/api/prava/payment-result/${sessionId}?_t=${Date.now()}`);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `prava payment result failed (${res.status})`);
  return data;
}

export async function getSessionPravaCheckout() {
  const res = await fetch(`${BASE}/api/session/prava-checkout?_t=${Date.now()}`);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `prava checkout failed (${res.status})`);
  return data;
}

export async function reportPravaStatus(payload) {
  const res = await fetch(`${BASE}/api/prava/report-status`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `prava report failed (${res.status})`);
  return data;
}

/* --- settings (the remembered agent pick) --- */

export async function getPreferredAgent() {
  const res = await fetch(`${BASE}/api/settings/agent`);
  if (!res.ok) throw new Error(`settings failed (${res.status})`);
  const data = await res.json();
  return data.agent; // 'claude' | 'codex' | null
}

export async function savePreferredAgent(agent) {
  const res = await fetch(`${BASE}/api/settings/agent`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ agent }),
  });
  if (!res.ok) throw new Error(`save agent failed (${res.status})`);
  const data = await res.json();
  return data.agent;
}

/* --- settings (the remembered grocery provider pick) --- */

export async function getPreferredProvider() {
  const res = await fetch(`${BASE}/api/settings/provider`);
  if (!res.ok) throw new Error(`settings failed (${res.status})`);
  const data = await res.json();
  return data.provider; // 'swiggy-instamart' | 'zepto'
}

export async function savePreferredProvider(provider) {
  const res = await fetch(`${BASE}/api/settings/provider`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ provider }),
  });
  if (!res.ok) throw new Error(`save provider failed (${res.status})`);
  const data = await res.json();
  return data.provider;
}

/* --- profile --- */

export async function getProfile() {
  const res = await fetch(`${BASE}/api/profile`);
  if (!res.ok) throw new Error(`profile failed (${res.status})`);
  return res.json();
}

export async function saveProfile(markdown) {
  const res = await fetch(`${BASE}/api/profile`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ markdown }),
  });
  if (!res.ok) throw new Error(`save failed (${res.status})`);
  return res.json();
}

/* --- chat --- */

/**
 * POST /api/chat and read the SSE stream. The backend routes to the active session,
 * so we only send { agent, message }. `onEvent` receives each normalized event
 * ({ type: 'session' | 'status' | 'delta' | 'tool' | 'error' | 'done' | 'end', ... }).
 * We use fetch + ReadableStream (not EventSource) because we need a POST body.
 */
export async function streamChat({ agent, message, images = [], onEvent, signal }) {
  const res = await fetch(`${BASE}/api/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ agent, message, images }),
    signal,
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || `chat failed (${res.status})`);
  }

  await readSseStream(res, onEvent);
}

export async function streamInternalHandoff({ agent, message, transcriptMessage, onEvent, signal }) {
  const res = await fetch(`${BASE}/api/chat/internal-handoff`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ agent, message, transcriptMessage }),
    signal,
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || `internal handoff failed (${res.status})`);
  }

  await readSseStream(res, onEvent);
}

export async function streamOpening({ agent, onEvent, signal }) {
  const res = await fetch(`${BASE}/api/chat/opening`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ agent }),
    signal,
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || `opening failed (${res.status})`);
  }

  await readSseStream(res, onEvent);
}
