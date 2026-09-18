import { Navigate, useNavigate } from 'react-router-dom';
import Workspace from '../components/Workspace.jsx';
import { sourceById } from '../sources.js';

// Resolve the remembered pick against what's actually installed + signed in
// right now. If it's usable, show chat. Otherwise, bounce to the picker. The
// grocery source always resolves (it has a default), so it never gates entry —
// it's just passed through so chat can show which source is live.
export default function ChatPage({ agents, savedAgentId, savedProviderId }) {
  const navigate = useNavigate();
  const agent = agents.find((a) => a.id === savedAgentId && a.installed && a.loggedIn);

  if (!agent) return <Navigate to="/select" replace />;

  return (
    <Workspace
      key={agent.id}
      agent={agent}
      provider={sourceById(savedProviderId)}
      onBack={() => navigate('/select')}
    />
  );
}
