import { useEffect, useState } from 'react';
import { ArrowLeft, Clock3, TriangleAlert, X } from 'lucide-react';
import { listSessions, getSessionMessages, apiUrl } from '../api.js';
import MarkdownMessage from './MarkdownMessage.jsx';
import { Backdrop } from './ProfileModal.jsx';

function HistoryAttachments({ attachments }) {
  if (!attachments?.length) return null;

  return (
    <div className="mb-2 flex flex-wrap gap-2">
      {attachments.map((attachment) => (
        <img
          key={attachment.id || attachment.url}
          src={apiUrl(attachment.url)}
          alt={attachment.name || 'Attached image'}
          className="h-16 w-16 rounded-lg border border-orange-100 object-cover"
          title={attachment.name}
        />
      ))}
    </div>
  );
}

// Read-only debug view of every past session. Pick one → see its full transcript.
export default function HistoryModal({ onClose }) {
  const [rows, setRows] = useState(null);
  const [err, setErr] = useState('');
  const [open, setOpen] = useState(null); // { session, messages }

  useEffect(() => {
    listSessions().then(setRows).catch((e) => setErr(e.message));
  }, []);

  async function openSession(s) {
    try {
      const messages = await getSessionMessages(s.id);
      setOpen({ session: s, messages });
    } catch (e) {
      setErr(e.message);
    }
  }

  return (
    <Backdrop onClose={onClose}>
      <div className="flex items-center justify-between border-b border-orange-100 px-5 py-3">
        <h2 className="flex items-center gap-2 font-semibold text-stone-800">
          <Clock3 className="h-4 w-4" aria-hidden="true" />
          {open ? 'Session transcript' : 'Past sessions'}
        </h2>
        <div className="flex items-center gap-3">
          {open && (
            <button type="button" onClick={() => setOpen(null)} className="inline-flex items-center gap-1 text-sm text-stone-500 hover:text-orange-600">
              <ArrowLeft className="h-4 w-4" aria-hidden="true" />
              back
            </button>
          )}
          <button type="button" onClick={onClose} className="text-stone-400 hover:text-orange-600" aria-label="Close">
            <X className="h-5 w-5" aria-hidden="true" />
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-5">
        {err && (
          <p className="flex items-center gap-1.5 text-sm text-red-500">
            <TriangleAlert className="h-4 w-4 shrink-0" aria-hidden="true" />
            {err}
          </p>
        )}

        {/* List of sessions */}
        {!open && (
          <>
            {rows === null && <p className="text-sm text-stone-400">Loading…</p>}
            {rows?.length === 0 && <p className="text-sm text-stone-400">No sessions yet.</p>}
            <ul className="space-y-2">
              {rows?.map((s) => (
                <li key={s.id}>
                  <button
                    type="button"
                    onClick={() => openSession(s)}
                    className="flex w-full items-center justify-between rounded-xl border border-stone-200 px-4 py-3 text-left hover:border-orange-300 hover:bg-orange-50"
                  >
                    <div className="min-w-0">
                      <div className="truncate text-sm font-medium text-stone-800">
                        {s.title || <span className="text-stone-400">(no messages)</span>}
                      </div>
                      <div className="mt-0.5 text-xs text-stone-400">
                        {s.name ? `${s.name} · ` : ''}
                        {new Date(s.created_at).toLocaleString()} · {s.message_count} msg
                      </div>
                    </div>
                    <span
                      className={
                        'ml-3 shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium ' +
                        (s.status === 'active'
                          ? 'bg-emerald-100 text-emerald-700'
                          : 'bg-stone-100 text-stone-500')
                      }
                    >
                      {s.status}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </>
        )}

        {/* One session's transcript */}
        {open && (
          <div className="space-y-3">
            {open.messages.length === 0 && <p className="text-sm text-stone-400">Empty session.</p>}
            {open.messages.map((m, i) => (
              <div key={i} className={m.role === 'user' ? 'flex justify-end' : 'flex justify-start'}>
                <div
                  className={
                    'max-w-[85%] rounded-2xl px-3.5 py-2 text-sm ' +
                    (m.role === 'user'
                      ? 'whitespace-pre-wrap bg-orange-500 text-white'
                      : 'border border-orange-100 bg-white text-stone-800')
                  }
                >
                  <HistoryAttachments attachments={m.attachments} />
                  {m.role === 'assistant' ? <MarkdownMessage text={m.content} /> : m.content}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </Backdrop>
  );
}
