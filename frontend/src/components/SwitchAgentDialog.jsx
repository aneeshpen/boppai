import { RefreshCw, X } from 'lucide-react';
import { Backdrop } from './ProfileModal.jsx';

// Shown when the user changes their driver agent and/or grocery source on the select
// screen while a conversation already exists. Applying the change ends that session
// (it moves to History) and starts a fresh one. `changes` is a list of short
// "What: old → new" lines describing exactly what's about to change.
export default function SwitchAgentDialog({ changes = [], busy, onCancel, onConfirm }) {
  return (
    <Backdrop onClose={busy ? () => {} : onCancel}>
      <div className="flex items-center justify-between border-b border-orange-100 px-5 py-3">
        <h2 className="flex items-center gap-2 font-semibold text-stone-800">
          <RefreshCw className="h-4 w-4" aria-hidden="true" />
          Start a fresh session?
        </h2>
        <button
          type="button"
          onClick={onCancel}
          disabled={busy}
          className="text-stone-400 hover:text-orange-600 disabled:opacity-40"
          aria-label="Close"
        >
          <X className="h-5 w-5" aria-hidden="true" />
        </button>
      </div>

      <div className="p-5 text-sm text-stone-600">
        <p>
          Applying this change will <span className="font-semibold">end your current conversation</span>{' '}
          and start a brand-new session.
        </p>
        {changes.length > 0 && (
          <ul className="mt-3 space-y-1 rounded-lg bg-stone-50 px-4 py-3 text-stone-700">
            {changes.map((line) => (
              <li key={line} className="font-medium">{line}</li>
            ))}
          </ul>
        )}
        <p className="mt-3 text-stone-400">
          Your current chat moves to History. If you'd rather keep going, cancel and head back to it.
        </p>
      </div>

      <div className="flex justify-end gap-2 border-t border-orange-100 px-5 py-3">
        <button
          type="button"
          onClick={onCancel}
          disabled={busy}
          className="rounded-xl px-4 py-2 text-sm text-stone-500 hover:bg-stone-100 disabled:opacity-40"
        >
          Keep chatting
        </button>
        <button
          type="button"
          onClick={onConfirm}
          disabled={busy}
          className="rounded-xl bg-orange-500 px-4 py-2 text-sm font-semibold text-white hover:bg-orange-600 disabled:opacity-40"
        >
          {busy ? 'Starting…' : 'Yes, start fresh'}
        </button>
      </div>
    </Backdrop>
  );
}
