import { useCallback, useEffect, useState } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { CircleAlert } from 'lucide-react';
import { detectAgents, getPreferredAgent, getPreferredProvider } from './api.js';
import { DEFAULT_SOURCE_ID } from './sources.js';
import ChatPage from './pages/ChatPage.jsx';
import LandingPage from './pages/LandingPage.jsx';
import SelectPage from './pages/SelectPage.jsx';
import thinkingImage from './assets/thinking.png';

export default function App() {
  const [phase, setPhase] = useState('detecting'); // 'detecting' | 'error' | 'ready'
  const [agents, setAgents] = useState([]);
  const [savedAgentId, setSavedAgentId] = useState(null);
  const [savedProviderId, setSavedProviderId] = useState(DEFAULT_SOURCE_ID);
  const [error, setError] = useState('');

  // Boot gate: detect installed agents AND read the remembered picks (agent +
  // grocery provider) together, then hand off to routing. Also reused by
  // Rescan / Try again.
  const boot = useCallback(async () => {
    setPhase('detecting');
    setError('');
    try {
      const [detected, savedAgent, savedProvider] = await Promise.all([
        detectAgents(),
        getPreferredAgent(),
        getPreferredProvider(),
      ]);
      setAgents(detected);
      setSavedAgentId(savedAgent);
      setSavedProviderId(savedProvider || DEFAULT_SOURCE_ID);
      setPhase('ready');
    } catch (err) {
      setError(err.message);
      setPhase('error');
    }
  }, []);

  useEffect(() => {
    boot();
  }, [boot]);

  if (phase === 'detecting') {
    return (
      <div className="min-h-screen overflow-hidden bg-[radial-gradient(circle_at_50%_45%,#faa486_0%,#ef5927_52%,#c8420f_135%)]">
        <div className="flex min-h-screen flex-col items-center justify-center gap-6 px-6 text-center text-bp-linen">
          <img
            src={thinkingImage}
            alt=""
            className="w-[min(60vw,40rem)] max-w-full animate-boppai-wobble object-contain drop-shadow-[0_1.2rem_2rem_rgba(97,55,17,0.4)]"
          />
          <p className="font-['Nighty'] text-[clamp(1.8rem,4vw,3.2rem)] leading-tight">
            Looking for coding agents on your machine…
          </p>
        </div>
      </div>
    );
  }

  if (phase === 'error') {
    return (
      <div className="min-h-screen bg-orange-50/40">
        <div className="flex min-h-screen flex-col items-center justify-center gap-4 px-6 text-center">
          <CircleAlert className="h-10 w-10 text-orange-500" aria-hidden="true" />
          <p className="text-stone-600">Couldn't reach the backend.</p>
          <p className="max-w-md text-sm text-stone-400">{error}</p>
          <button
            type="button"
            onClick={boot}
            className="rounded-xl bg-orange-500 px-4 py-2 text-sm font-semibold text-white hover:bg-orange-600"
          >
            Try again
          </button>
        </div>
      </div>
    );
  }

  // phase === 'ready' → routing takes over. Linen is the app-wide canvas; the
  // Landing/Select pages paint their own full-bleed background over it, so this
  // linen only shows through on the chat page (behind the centered column).
  return (
    <div className="min-h-screen bg-bp-linen">
      <Routes>
        <Route path="/landing" element={<LandingPage agents={agents} savedAgentId={savedAgentId} />} />
        <Route
          path="/"
          element={<ChatPage agents={agents} savedAgentId={savedAgentId} savedProviderId={savedProviderId} />}
        />
        <Route
          path="/select"
          element={
            <SelectPage
              agents={agents}
              savedAgentId={savedAgentId}
              savedProviderId={savedProviderId}
              onRescan={boot}
              onPicked={setSavedAgentId}
              onProviderPicked={setSavedProviderId}
            />
          }
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </div>
  );
}
