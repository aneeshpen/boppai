// The select screen: pick BOTH the driver agent (Claude/Codex) and the grocery
// source (Swiggy/Zepto) on one page, then Continue into chat. Fully controlled —
// selection state + the Continue/Rescan handlers live in SelectPage.
import { Check } from 'lucide-react';
import { GROCERY_SOURCES } from '../sources.js';

function StatusBadge({ agent }) {
  if (!agent.installed) {
    return <span className="rounded-full bg-bp-domino/15 px-3 py-1 text-xs font-semibold text-bp-domino">Not found</span>;
  }
  if (agent.loggedIn) {
    return <span className="rounded-full bg-bp-conifer px-3 py-1 text-xs font-semibold text-bp-jambalaya">Signed in</span>;
  }
  return <span className="rounded-full bg-bp-geraldine/35 px-3 py-1 text-xs font-semibold text-bp-jambalaya">Not signed in</span>;
}

// A shared "you picked this" ring. `selected` wins visually; ready-but-unselected
// tiles stay interactive; not-ready tiles are dimmed and inert.
function tileClass({ ready, selected }) {
  const border = selected
    ? 'border-bp-conifer bg-bp-linen shadow-[0_1.4rem_3rem_rgba(97,55,17,0.22)] ring-2 ring-bp-conifer/55'
    : ready
      ? 'cursor-pointer border-bp-linen/55 bg-bp-linen/92 shadow-[0_1rem_2.5rem_rgba(97,55,17,0.12)] hover:-translate-y-1 hover:border-bp-conifer hover:shadow-[0_1.4rem_3rem_rgba(97,55,17,0.2)]'
      : 'cursor-not-allowed border-bp-domino/20 bg-bp-linen/55 opacity-70';
  return `group flex w-full flex-col gap-4 rounded-[1.75rem] border p-5 text-left transition duration-300 sm:p-6 ${border}`;
}

function SelectedPill() {
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-bp-jambalaya px-3 py-1 text-xs font-semibold text-bp-linen">
      <Check className="h-3.5 w-3.5" aria-hidden="true" />
      Selected
    </span>
  );
}

function AgentTile({ agent, selected, onSelect }) {
  const ready = agent.installed && agent.loggedIn;
  return (
    <button
      type="button"
      disabled={!ready}
      aria-pressed={selected}
      onClick={() => onSelect(agent)}
      className={tileClass({ ready, selected })}
    >
      <div className="flex items-start justify-between gap-4">
        <div>
          <span className="block font-['Nighty'] text-5xl leading-[0.78] text-bp-jambalaya sm:text-6xl">
            {agent.name}
          </span>
          <div className="mt-2 min-h-5 text-xs font-medium text-bp-domino">
            {agent.installed && agent.version && <span>{agent.version}</span>}
            {ready && agent.account && <span className="ml-1 text-bp-jambalaya/80">· {agent.account}</span>}
          </div>
        </div>
        <div className="flex flex-col items-end gap-2">
          <StatusBadge agent={agent} />
          {selected && <SelectedPill />}
        </div>
      </div>
      <p className="max-w-sm text-sm leading-6 text-bp-jambalaya/75">{agent.tagline}</p>

      {!ready && (
        <span className="mt-1 rounded-2xl border border-bp-domino/20 bg-white/50 px-4 py-3 text-xs leading-5 text-bp-domino">
          {agent.installed
            ? `Run \`${agent.bin} login\` in a terminal, then rescan.`
            : `Install the ${agent.name} CLI to use it here.`}
        </span>
      )}
    </button>
  );
}

function SourceTile({ source, selected, onSelect }) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={() => onSelect(source)}
      className={tileClass({ ready: true, selected })}
    >
      <div className="flex items-start justify-between gap-4">
        <span className="block font-['Nighty'] text-5xl leading-[0.78] text-bp-jambalaya sm:text-6xl">
          {source.name}
        </span>
        {selected && <SelectedPill />}
      </div>
      <p className="max-w-sm text-sm leading-6 text-bp-jambalaya/75">{source.tagline}</p>
    </button>
  );
}

export default function AgentPicker({
  agents,
  selectedAgentId,
  onSelectAgent,
  selectedProviderId,
  onSelectProvider,
  onContinue,
  continueDisabled,
  onRescan,
}) {
  return (
    <main className="min-h-screen bg-[radial-gradient(circle_at_50%_20%,#faa486_0%,#ef5927_48%,#613711_145%)] px-5 py-8 text-bp-linen sm:px-8">
      <div className="mx-auto flex min-h-[calc(100vh-4rem)] w-full max-w-4xl flex-col justify-center gap-10">
        <section>
          <h1 className="font-['Nighty'] text-[clamp(2.75rem,7vw,5.75rem)] leading-[0.78] text-bp-linen drop-shadow-[0_0.14rem_0_rgba(97,55,17,0.28)]">
            Pick your sous-chef
          </h1>
          <p className="mt-3 font-['DM_Sans'] text-2xl font-black tracking-tight text-bp-jambalaya sm:text-3xl">
            Driver agent
          </p>
          <p className="mt-5 max-w-xl text-base font-semibold leading-7 text-bp-linen/90 sm:text-lg">
            We found the coding agents on your machine. Choose which one Boppai should plug into for
            this chat.
          </p>

          <div className="mt-6 grid gap-4 md:grid-cols-2">
            {agents.map((agent) => (
              <AgentTile
                key={agent.id}
                agent={agent}
                selected={agent.id === selectedAgentId}
                onSelect={onSelectAgent}
              />
            ))}
          </div>
        </section>

        <section>
          <h2 className="font-['DM_Sans'] text-2xl font-black tracking-tight text-bp-jambalaya sm:text-3xl">
            Pick your grocery source
          </h2>
          <p className="mt-3 max-w-xl text-sm font-semibold leading-6 text-bp-linen/90 sm:text-base">
            Boppai orders through one grocery service per session. You can switch anytime — it just
            starts a fresh chat.
          </p>

          <div className="mt-5 grid gap-4 md:grid-cols-2">
            {GROCERY_SOURCES.map((source) => (
              <SourceTile
                key={source.id}
                source={source}
                selected={source.id === selectedProviderId}
                onSelect={onSelectProvider}
              />
            ))}
          </div>
        </section>

        <div className="flex flex-col items-center gap-3 sm:flex-row sm:justify-center">
          <button
            type="button"
            onClick={onContinue}
            disabled={continueDisabled}
            className="inline-flex min-h-[3.65rem] min-w-[11.5rem] items-center justify-center rounded-full border-2 border-bp-linen bg-bp-linen px-7 pb-2 pt-3 font-['Nighty'] text-4xl leading-[0.72] text-bp-flamingo shadow-[0_0.9rem_1.8rem_rgba(97,55,17,0.2)] transition-colors duration-200 hover:bg-bp-jambalaya hover:text-bp-linen focus:outline-none focus-visible:ring-4 focus-visible:ring-bp-geraldine/45 disabled:cursor-not-allowed disabled:border-bp-linen/40 disabled:bg-bp-linen/45 disabled:text-bp-domino/60 disabled:shadow-none"
          >
            Continue
          </button>
          <button
            type="button"
            onClick={onRescan}
            className="inline-flex min-h-[3.65rem] min-w-[10rem] items-center justify-center rounded-full border-2 border-bp-linen/80 bg-bp-jambalaya/85 px-7 pb-2 pt-3 font-['Nighty'] text-4xl leading-[0.72] text-bp-linen shadow-[0_0.9rem_1.8rem_rgba(97,55,17,0.16)] transition-colors duration-200 hover:bg-bp-linen hover:text-bp-jambalaya focus:outline-none focus-visible:ring-4 focus-visible:ring-bp-geraldine/45"
          >
            Rescan
          </button>
        </div>
      </div>
    </main>
  );
}
