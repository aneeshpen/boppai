import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { newSession, savePreferredAgent, savePreferredProvider } from '../api.js';
import AgentPicker from '../components/AgentPicker.jsx';
import SwitchAgentDialog from '../components/SwitchAgentDialog.jsx';
import { DEFAULT_SOURCE_ID, sourceById } from '../sources.js';

// Pick agent + grocery source, then Continue. If nothing changed we just resume the
// remembered setup; if either pick changed AND there was already a setup, we confirm
// first — changing either one abandons the current conversation and starts fresh
// (same contract as the old agent-only switch).
export default function SelectPage({
  agents,
  savedAgentId,
  savedProviderId,
  onRescan,
  onPicked,
  onProviderPicked,
}) {
  const navigate = useNavigate();

  const readyAgents = agents.filter((agent) => agent.installed && agent.loggedIn);
  const initialAgentId = savedAgentId && readyAgents.some((agent) => agent.id === savedAgentId)
    ? savedAgentId
    : readyAgents[0]?.id || null;

  const [selectedAgentId, setSelectedAgentId] = useState(initialAgentId);
  const [selectedProviderId, setSelectedProviderId] = useState(savedProviderId || DEFAULT_SOURCE_ID);
  const [confirming, setConfirming] = useState(false);
  const [switching, setSwitching] = useState(false);

  // Only warn (and abandon the session) when there's an existing remembered setup
  // AND the user actually changed something. First-time picks commit silently.
  const hasExisting = Boolean(savedAgentId);
  const changed = selectedAgentId !== savedAgentId || selectedProviderId !== savedProviderId;

  async function commit({ freshSession }) {
    await savePreferredAgent(selectedAgentId);
    await savePreferredProvider(selectedProviderId);
    if (freshSession) await newSession();
    onPicked(selectedAgentId);
    onProviderPicked(selectedProviderId);
    navigate('/');
  }

  async function handleContinue() {
    if (!selectedAgentId) return;
    if (hasExisting && changed) {
      setConfirming(true);
      return;
    }
    await commit({ freshSession: false });
  }

  async function confirmSwitch() {
    setSwitching(true);
    try {
      await commit({ freshSession: true });
    } finally {
      setSwitching(false);
      setConfirming(false);
    }
  }

  // Human-readable "what's changing" lines for the confirm dialog.
  const agentName = (id) => agents.find((agent) => agent.id === id)?.name || id;
  const changes = [];
  if (selectedAgentId !== savedAgentId) {
    changes.push(`Agent: ${agentName(savedAgentId)} → ${agentName(selectedAgentId)}`);
  }
  if (selectedProviderId !== savedProviderId) {
    changes.push(`Grocery source: ${sourceById(savedProviderId).name} → ${sourceById(selectedProviderId).name}`);
  }

  return (
    <>
      <AgentPicker
        agents={agents}
        selectedAgentId={selectedAgentId}
        onSelectAgent={(agent) => setSelectedAgentId(agent.id)}
        selectedProviderId={selectedProviderId}
        onSelectProvider={(source) => setSelectedProviderId(source.id)}
        onContinue={handleContinue}
        continueDisabled={!selectedAgentId}
        onRescan={onRescan}
      />
      {confirming && (
        <SwitchAgentDialog
          changes={changes}
          busy={switching}
          onCancel={() => setConfirming(false)}
          onConfirm={confirmSwitch}
        />
      )}
    </>
  );
}
