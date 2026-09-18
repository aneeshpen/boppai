import { useEffect, useState } from 'react';
import { ChevronDown, ChevronRight, RefreshCw, TriangleAlert, X } from 'lucide-react';
import { getTools, getRemoteMcpServers, getRemoteMcpTools } from '../api.js';
import { Backdrop } from './ProfileModal.jsx';

// The Tools modal has two kinds of sections:
//   - Local Boppai MCP: static metadata from /api/tools, renders instantly.
//   - Remote MCPs (Zepto, Swiggy Instamart, ...): discovered LIVE, one section each,
//     probed independently so a slow/offline one never blocks the others. Each shows
//     a status pill and a brief "Checking..." while the backend opens a real session.
// Opening the modal probes every remote once; each Recheck button re-probes its own.

const PILL = {
  checking: ['Checking…', 'bg-stone-100 text-stone-500'],
  connected: ['Connected', 'bg-emerald-100 text-emerald-700'],
  offline: ['Not connected', 'bg-red-100 text-red-600'],
};

function StatusPill({ state }) {
  const [text, cls] = PILL[state] || PILL.offline;
  return <span className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium ${cls}`}>{text}</span>;
}

function ToolItem({ tool }) {
  const [open, setOpen] = useState(false);
  const hasDescription = Boolean(tool.description);
  const Chevron = open ? ChevronDown : ChevronRight;

  return (
    <li className="rounded-lg border border-stone-200 px-4 py-3">
      <button
        type="button"
        onClick={() => hasDescription && setOpen((value) => !value)}
        disabled={!hasDescription}
        aria-expanded={hasDescription ? open : undefined}
        className="flex w-full items-baseline gap-2 text-left disabled:cursor-default"
      >
        {hasDescription ? (
          <Chevron className="mt-0.5 h-4 w-4 shrink-0 text-stone-400" aria-hidden="true" />
        ) : (
          <span className="h-4 w-4 shrink-0" aria-hidden="true" />
        )}
        <span className="flex min-w-0 flex-wrap items-baseline gap-2">
          <code className="rounded bg-orange-50 px-1.5 py-0.5 text-sm font-semibold text-orange-700">
            {tool.name}
          </code>
          {tool.title && <span className="text-sm text-stone-500">{tool.title}</span>}
        </span>
      </button>
      {hasDescription && open && (
        <p className="ml-6 mt-1.5 text-sm leading-relaxed text-stone-700">{tool.description}</p>
      )}
    </li>
  );
}

// A local Boppai MCP section: header + static tool list.
function LocalServerSection({ server }) {
  return (
    <section>
      <div className="mb-2 flex items-baseline justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-stone-800">{server.label || server.name}</h3>
          {server.description && (
            <p className="mt-0.5 text-xs leading-relaxed text-stone-400">{server.description}</p>
          )}
        </div>
        <span className="shrink-0 text-xs text-stone-400">{server.tools?.length || 0} tools</span>
      </div>
      <ul className="space-y-2">
        {server.tools?.map((t) => <ToolItem key={`${server.name}:${t.name}`} tool={t} />)}
      </ul>
    </section>
  );
}

// A remote MCP section: probes /api/mcp/remote/:name/tools on mount + on Recheck,
// showing a live status pill, the discovered tools, or a login hint when offline.
function RemoteServerSection({ server }) {
  const [state, setState] = useState(null); // { connected, tools, login, error }
  const [loading, setLoading] = useState(true);

  function load() {
    setLoading(true);
    getRemoteMcpTools(server.name)
      .then(setState)
      .catch((e) => setState({ connected: false, tools: [], error: e.message }))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    load();
  }, [server.name]);

  const status = loading ? 'checking' : state?.connected ? 'connected' : 'offline';
  const tools = state?.tools || [];
  const loginCmd = state?.login || server.login;

  return (
    <section>
      <div className="mb-2 flex items-baseline justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-semibold text-stone-800">{server.label || server.name}</h3>
            <StatusPill state={status} />
          </div>
          {server.description && (
            <p className="mt-0.5 text-xs leading-relaxed text-stone-400">{server.description}</p>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <span className="text-xs text-stone-400">{tools.length} tools</span>
          <button
            type="button"
            onClick={load}
            disabled={loading}
            className="inline-flex items-center gap-1 rounded-md border border-stone-200 px-2 py-0.5 text-xs text-stone-500 hover:border-orange-300 hover:text-orange-600 disabled:opacity-40"
          >
            <RefreshCw className={`h-3 w-3 ${loading ? 'animate-spin' : ''}`} aria-hidden="true" />
            {loading ? 'Checking…' : 'Recheck'}
          </button>
        </div>
      </div>

      {loading && <p className="text-sm text-stone-400">Connecting…</p>}

      {!loading && !state?.connected && (
        <div className="rounded-lg border border-dashed border-stone-200 bg-stone-50 px-4 py-3 text-sm">
          <p className="text-stone-600">Not connected. Log in once in a terminal, then Recheck:</p>
          <code className="mt-2 block overflow-x-auto whitespace-nowrap rounded bg-white px-3 py-2 text-xs text-stone-700">
            {loginCmd}
          </code>
          <p className="mt-2 text-xs text-stone-400">
            A browser opens for the mobile-number + OTP login. The token is cached and reused after that.
          </p>
        </div>
      )}

      {!loading && state?.connected && tools.length > 0 && (
        <ul className="space-y-2">
          {tools.map((t) => <ToolItem key={`${server.name}:${t.name}`} tool={t} />)}
        </ul>
      )}

      {/* Connected, but the catalog lives behind the agent CLI's OAuth token rather than
          ours — say so instead of showing a bare empty list. */}
      {!loading && state?.connected && tools.length === 0 && state?.note && (
        <p className="rounded-lg border border-dashed border-stone-200 bg-stone-50 px-4 py-3 text-sm text-stone-600">
          {state.note}
        </p>
      )}
    </section>
  );
}

export default function ToolsModal({ onClose }) {
  const [local, setLocal] = useState(null); // { servers: [{ name, label, tools }] }
  const [localErr, setLocalErr] = useState('');
  const [remotes, setRemotes] = useState(null); // [{ name, label, description, login }]
  const [remotesErr, setRemotesErr] = useState('');

  useEffect(() => {
    getTools().then(setLocal).catch((e) => setLocalErr(e.message));
    getRemoteMcpServers().then((d) => setRemotes(d.servers || [])).catch((e) => setRemotesErr(e.message));
  }, []);

  const localServers = local?.servers || [];

  return (
    <Backdrop onClose={onClose}>
      <div className="flex items-center justify-between border-b border-orange-100 px-5 py-3">
        <h2 className="font-semibold text-stone-800">Tools</h2>
        <button type="button" onClick={onClose} className="text-stone-400 hover:text-orange-600" aria-label="Close">
          <X className="h-5 w-5" aria-hidden="true" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-5">
        <p className="mb-4 text-xs text-stone-400">
          The MCP tools Boppai gives the selected agent. Remote servers are discovered live and authenticate lazily on first use.
        </p>

        <div className="space-y-6">
          {localErr && (
            <p className="flex items-center gap-1.5 text-sm text-red-500">
              <TriangleAlert className="h-4 w-4 shrink-0" aria-hidden="true" />
              {localErr}
            </p>
          )}
          {!localErr && local === null && <p className="text-sm text-stone-400">Loading…</p>}
          {localServers.map((server) => <LocalServerSection key={server.name} server={server} />)}

          {remotesErr && (
            <p className="flex items-center gap-1.5 text-sm text-red-500">
              <TriangleAlert className="h-4 w-4 shrink-0" aria-hidden="true" />
              {remotesErr}
            </p>
          )}
          {(remotes || []).map((server) => <RemoteServerSection key={server.name} server={server} />)}
        </div>
      </div>
    </Backdrop>
  );
}
