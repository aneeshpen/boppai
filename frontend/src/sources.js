// The grocery sources Boppai can plug into. IDs must match the backend remote MCP
// names (see backend/src/mcp/servers.js) — they're what /api/settings/provider
// stores. One source is active per session; the select screen picks it and it's
// remembered like the agent. Zepto is intentionally selectable even though it's
// rate-limited: choosing it works, and the error only shows when its tools run.
export const GROCERY_SOURCES = [
  {
    id: 'swiggy-instamart',
    name: 'Swiggy Instamart',
    tagline: "Swiggy's instant-grocery arm — snacks, essentials, and fresh produce at your door in minutes.",
  },
  {
    id: 'zepto',
    name: 'Zepto',
    tagline: "India's 10-minute grocery app — a full quick-commerce catalog delivered from nearby dark stores.",
  },
];

export const DEFAULT_SOURCE_ID = 'swiggy-instamart';

export function sourceById(id) {
  return GROCERY_SOURCES.find((source) => source.id === id) || GROCERY_SOURCES[0];
}
