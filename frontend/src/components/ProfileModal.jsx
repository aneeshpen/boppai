import { useEffect, useState } from 'react';
import { Settings, TriangleAlert, X } from 'lucide-react';
import { getProfile, saveProfile } from '../api.js';

// Shows profile.md in an editable textarea. The agent writes this file via its
// save_profile tool; here the user can read it and hand-edit + Save.
export default function ProfileModal({ onClose, onSaved }) {
  const [markdown, setMarkdown] = useState('');
  const [exists, setExists] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');

  useEffect(() => {
    getProfile()
      .then((p) => {
        setMarkdown(p.markdown || '');
        setExists(p.exists);
      })
      .catch((e) => setErr(e.message))
      .finally(() => setLoading(false));
  }, []);

  async function save() {
    setSaving(true);
    setErr('');
    try {
      await saveProfile(markdown);
      onSaved?.();
      onClose();
    } catch (e) {
      setErr(e.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <Backdrop onClose={onClose}>
      <div className="flex items-center justify-between border-b border-orange-100 px-5 py-3">
        <h2 className="flex items-center gap-2 font-semibold text-stone-800">
          <Settings className="h-4 w-4" aria-hidden="true" />
          Your profile
        </h2>
        <button type="button" onClick={onClose} className="text-stone-400 hover:text-orange-600" aria-label="Close">
          <X className="h-5 w-5" aria-hidden="true" />
        </button>
      </div>

      <div className="p-5">
        <p className="mb-2 text-xs text-stone-400">
          This is <code>profile.md</code>. The agent edits it as you chat; you can also edit it
          here and save.
          {!loading && !exists && ' (Nothing saved yet.)'}
        </p>
        <textarea
          value={markdown}
          onChange={(e) => setMarkdown(e.target.value)}
          disabled={loading}
          spellCheck={false}
          placeholder={loading ? 'Loading…' : '# Your name\n- Goal: …\n- Diet: …'}
          className="h-80 w-full resize-none rounded-xl border border-stone-200 p-3 font-mono text-sm outline-none focus:border-orange-400 focus:ring-2 focus:ring-orange-100"
        />
        {err && (
          <p className="mt-2 flex items-center gap-1.5 text-sm text-red-500">
            <TriangleAlert className="h-4 w-4 shrink-0" aria-hidden="true" />
            {err}
          </p>
        )}
      </div>

      <div className="flex justify-end gap-2 border-t border-orange-100 px-5 py-3">
        <button
          type="button"
          onClick={onClose}
          className="rounded-xl px-4 py-2 text-sm text-stone-500 hover:bg-stone-100"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={save}
          disabled={saving || loading}
          className="rounded-xl bg-orange-500 px-4 py-2 text-sm font-semibold text-white hover:bg-orange-600 disabled:opacity-40"
        >
          {saving ? 'Saving…' : 'Save'}
        </button>
      </div>
    </Backdrop>
  );
}

// Shared modal shell (click outside to close).
export function Backdrop({ children, onClose }) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-stone-900/30 p-4"
      onClick={onClose}
    >
      <div
        className="flex max-h-[85vh] w-full max-w-lg flex-col overflow-hidden rounded-2xl bg-white shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        {children}
      </div>
    </div>
  );
}
