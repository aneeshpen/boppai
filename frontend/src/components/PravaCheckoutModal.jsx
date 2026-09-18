import { useCallback, useEffect, useRef, useState } from 'react';
import { CheckCircle2, Copy, CreditCard, ExternalLink, ShieldCheck, X } from 'lucide-react';

import {
  createPravaSession,
  getPravaConfig,
  getPravaPaymentResult,
  getSessionPravaCheckout,
  reportPravaStatus,
} from '../api.js';
import PravaCardForm from './PravaCardForm.jsx';

const TEST_PAYMENT = {
  totalAmount: '20.00',
  currency: 'INR',
  description: 'Boppai sandbox grocery test',
  merchantName: 'Swiggy Instamart',
  merchantUrl: 'https://www.swiggy.com/',
  products: [{ description: 'Dairy Milk under Rs 20 test item', unitPrice: '20.00', quantity: 1 }],
};

function firstLineItem(result) {
  return result?.transactions?.[0]?.line_items?.[0] || null;
}

function expiryValue(lineItem) {
  if (!lineItem?.expiry_month || !lineItem?.expiry_year) return '';
  return `${lineItem.expiry_month}/${String(lineItem.expiry_year).slice(-2)}`;
}

function displayAmount(checkout) {
  if (!checkout) return 'Swiggy Instamart';
  return `${checkout.merchantName || 'Swiggy Instamart'} · Rs ${checkout.totalAmount} · ${checkout.currency || 'INR'}`;
}

function CredentialRow({ label, value, secret = false }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    if (!value) return;
    await navigator.clipboard?.writeText(String(value));
    setCopied(true);
    setTimeout(() => setCopied(false), 1200);
  }

  return (
    <div className="grid gap-1 rounded-lg border border-stone-100 bg-white px-3 py-2">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-stone-400">{label}</div>
      <div className="flex items-center gap-2">
        <code className="min-w-0 flex-1 break-all text-sm font-semibold text-stone-800">
          {secret ? String(value || '').replace(/.(?=.{3})/g, '*') : value || 'Not returned'}
        </code>
        {value && (
          <button
            type="button"
            onClick={copy}
            className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-stone-200 text-stone-500 hover:bg-stone-50"
            aria-label={`Copy ${label}`}
            title={`Copy ${label}`}
          >
            {copied ? <CheckCircle2 className="h-4 w-4 text-emerald-600" /> : <Copy className="h-4 w-4" />}
          </button>
        )}
      </div>
    </div>
  );
}

export default function PravaCheckoutModal({ mode = 'sandbox', onClose, onCredentialReady }) {
  const [config, setConfig] = useState(null);
  const [checkout, setCheckout] = useState(null);
  const [session, setSession] = useState(null);
  const [result, setResult] = useState(null);
  const [reported, setReported] = useState(null);
  const [error, setError] = useState('');
  const [phase, setPhase] = useState('loading');
  const attemptsRef = useRef(0);
  const pollingRef = useRef(null);
  const intentRef = useRef(null);
  const handoffRef = useRef('');
  const isAgentMode = mode === 'agent';

  const stopPolling = useCallback(() => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
  }, []);

  const stopIntentPolling = useCallback(() => {
    if (intentRef.current) {
      clearInterval(intentRef.current);
      intentRef.current = null;
    }
  }, []);

  const pollPayment = useCallback(async (sessionId) => {
    attemptsRef.current += 1;
    try {
      const next = await getPravaPaymentResult(sessionId);
      setResult(next);
      const lineItem = firstLineItem(next);

      if (next.status === 'awaiting_result' || lineItem?.token) {
        setPhase('credential_ready');
        stopPolling();
      } else if (next.status === 'completed') {
        setPhase('completed');
        stopPolling();
      } else if (next.status === 'failed') {
        setPhase('failed');
        stopPolling();
      } else if (attemptsRef.current >= 30) {
        setPhase('timed_out');
        stopPolling();
      }
    } catch {
      if (attemptsRef.current >= 30) {
        setPhase('timed_out');
        stopPolling();
      }
    }
  }, [stopPolling]);

  const startPaymentPolling = useCallback((sessionId) => {
    attemptsRef.current = 0;
    setPhase('card_entry');
    pollPayment(sessionId);
    pollingRef.current = setInterval(() => pollPayment(sessionId), 3000);
  }, [pollPayment]);

  const startSandboxPayment = useCallback(async () => {
    setError('');
    setReported(null);
    setResult(null);
    setSession(null);
    setCheckout(TEST_PAYMENT);
    setPhase('creating');
    try {
      const nextSession = await createPravaSession(TEST_PAYMENT);
      setSession(nextSession);
      startPaymentPolling(nextSession.session_id);
    } catch (err) {
      setError(err.message);
      setPhase('error');
    }
  }, [startPaymentPolling]);

  const loadAgentCheckout = useCallback(async () => {
    try {
      const payload = await getSessionPravaCheckout();
      if (!payload.exists) {
        setPhase('waiting_intent');
        return false;
      }

      setCheckout(payload.checkout);
      if (payload.checkout.status === 'error') {
        setError(payload.checkout.error || 'Failed to start Prava checkout');
        setPhase('error');
        return true;
      }

      if (payload.checkout.status === 'ready' && payload.checkout.session?.session_id) {
        setSession(payload.checkout.session);
        startPaymentPolling(payload.checkout.session.session_id);
        return true;
      }

      setPhase('creating');
      return false;
    } catch (err) {
      setError(err.message);
      setPhase('error');
      return true;
    }
  }, [startPaymentPolling]);

  useEffect(() => {
    let alive = true;
    getPravaConfig()
      .then(async (nextConfig) => {
        if (!alive) return;
        setConfig(nextConfig);
        if (!nextConfig.configured) {
          setPhase('missing_config');
          return;
        }
        if (!isAgentMode) {
          setPhase('ready');
          return;
        }

        setPhase('waiting_intent');
        const done = await loadAgentCheckout();
        if (done || !alive) return;
        intentRef.current = setInterval(async () => {
          const resolved = await loadAgentCheckout();
          if (resolved) stopIntentPolling();
        }, 1000);
      })
      .catch((err) => {
        if (!alive) return;
        setError(err.message);
        setPhase('error');
      });

    return () => {
      alive = false;
      stopPolling();
      stopIntentPolling();
    };
  }, [isAgentMode, loadAgentCheckout, stopIntentPolling, stopPolling]);

  useEffect(() => {
    if (!isAgentMode || phase !== 'credential_ready') return undefined;

    let alive = true;
    const syncReportedOutcome = async () => {
      try {
        const payload = await getSessionPravaCheckout();
        if (!alive || !payload.exists) return;
        setCheckout(payload.checkout);
        const outcomeStatus = payload.checkout.reported?.status || payload.checkout.merchantOutcome?.status;
        if (outcomeStatus) {
          setReported({
            status: outcomeStatus,
            response: payload.checkout.reported,
            merchantOutcome: payload.checkout.merchantOutcome,
          });
        }
      } catch {
        // This is a passive UI sync; the agent/reporting path owns the real error.
      }
    };

    syncReportedOutcome();
    const id = setInterval(syncReportedOutcome, 2000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, [isAgentMode, phase]);

  async function report(status) {
    const lineItem = firstLineItem(result);
    if (!session?.session_id || !lineItem?.txn_ref_id) return;
    setError('');
    setReported({ status: 'sending' });
    try {
      const response = await reportPravaStatus({
        sessionId: session.session_id,
        txnRefId: lineItem.txn_ref_id,
        txnStatus: status,
        amountPaid: lineItem.total_amount,
      });
      setReported({ status, response });
    } catch (err) {
      setError(err.message);
      setReported(null);
    }
  }

  const canStart = !isAgentMode && (
    phase === 'ready' || phase === 'completed' || phase === 'failed' || phase === 'timed_out' || phase === 'credential_ready'
  );
  const lineItem = firstLineItem(result);
  const hasCredential = Boolean(lineItem?.token && lineItem?.dynamic_cvv);

  useEffect(() => {
    if (!isAgentMode || phase !== 'credential_ready' || !hasCredential || !session?.session_id || !lineItem?.txn_ref_id) return;
    const handoffKey = `${session.session_id}:${lineItem.txn_ref_id}`;
    if (handoffRef.current === handoffKey) return;
    handoffRef.current = handoffKey;
    onCredentialReady?.({
      checkout,
      sessionId: session.session_id,
      credential: {
        cardNumber: lineItem.token,
        expiry: expiryValue(lineItem),
        cvv: lineItem.dynamic_cvv,
        txnRefId: lineItem.txn_ref_id,
        amountPaid: lineItem.total_amount,
        nameOnCard: 'Prava User',
        cardNickname: 'Prava',
      },
    });
  }, [checkout, hasCredential, isAgentMode, lineItem, onCredentialReady, phase, session?.session_id]);

  // Browser automation is agent-driven through BrowserClaw; this panel stays
  // visible as a debug fallback and passively reflects the reported outcome.

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-stone-950/35 px-4 py-4">
      <div className="flex h-[calc(100vh-2rem)] max-h-[920px] w-full max-w-5xl flex-col overflow-hidden rounded-xl bg-white shadow-2xl shadow-stone-900/20">
        <div className="flex shrink-0 items-center justify-between border-b border-orange-100 px-5 py-3">
          <div className="flex items-center gap-2 font-semibold text-stone-800">
            <CreditCard className="h-4 w-4 text-orange-500" aria-hidden="true" />
            <span>{isAgentMode ? 'Prava payment for Swiggy' : 'Prava sandbox payment'}</span>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg px-2 py-1 text-stone-400 hover:bg-orange-50 hover:text-orange-600"
            aria-label="Close"
          >
            <X className="h-5 w-5" aria-hidden="true" />
          </button>
        </div>

        <div className="flex min-h-0 flex-1 flex-col overflow-hidden p-5">
          {error && (
            <div role="alert" className="mb-4 rounded-lg border border-red-100 bg-red-50 px-3 py-2 text-sm text-red-700">
              {error}
            </div>
          )}

          {phase === 'loading' && <p className="text-sm text-stone-500">Checking Prava setup...</p>}
          {phase === 'waiting_intent' && <p className="text-sm text-stone-500">Waiting for Boppai to create the Prava checkout...</p>}

          {phase === 'missing_config' && (
            <div className="rounded-lg border border-amber-100 bg-amber-50 px-3 py-2 text-sm text-amber-800">
              Add `PRAVA_PUBLISHABLE_KEY` to `backend/.env`, then restart the backend.
            </div>
          )}

          {canStart && (
            <div className="space-y-4">
              <div className="rounded-lg border border-stone-100 bg-stone-50 px-4 py-3 text-sm text-stone-600">
                <div className="font-medium text-stone-800">Swiggy Instamart · Rs 20.00 · INR</div>
                <div>Dairy Milk under Rs 20 test item</div>
              </div>
              <button
                type="button"
                onClick={startSandboxPayment}
                className="inline-flex items-center gap-2 rounded-xl bg-orange-500 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-orange-600"
              >
                <ShieldCheck className="h-4 w-4" aria-hidden="true" />
                Start embedded payment
              </button>
            </div>
          )}

          {phase === 'creating' && (
            <div className="rounded-lg border border-stone-100 bg-stone-50 px-3 py-2 text-sm text-stone-500">
              Creating Prava session for {displayAmount(checkout)}...
            </div>
          )}

          {phase === 'card_entry' && session && config?.publishableKey && (
            <div className="flex min-h-0 flex-1 flex-col gap-3">
              <div className="shrink-0 rounded-lg border border-emerald-100 bg-emerald-50 px-3 py-2 text-xs text-emerald-800">
                Session {session.session_id}. Complete Prava approval here; Boppai will poll for the one-time card credential.
              </div>
              <PravaCardForm
                publishableKey={config.publishableKey}
                session={session}
                onError={(err) => setError(err.message)}
              />
            </div>
          )}

          {phase === 'credential_ready' && (
            <div className="space-y-4 overflow-auto">
              <div className="rounded-lg border border-emerald-100 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
                Prava credential ready. Open Swiggy checkout, choose Add New Card, and enter these values manually.
              </div>

              <div className="rounded-lg border border-stone-100 bg-stone-50 px-4 py-3 text-sm text-stone-600">
                <div className="font-medium text-stone-800">{displayAmount(checkout)}</div>
                <div>{checkout?.description || 'Swiggy Instamart payment'}</div>
              </div>

              <p className="text-sm text-stone-500">Payment set up — you can close this window when the order's done.</p>

              {/*
                Hidden for the demo — we don't want raw card credentials or the
                manual accept/reject controls on screen. Kept commented (not
                deleted) so it's a one-step uncomment when we need it back.

              <div className="grid gap-3 md:grid-cols-2">
                <CredentialRow label="Card Number" value={lineItem?.token} />
                <CredentialRow label="Valid Through" value={expiryValue(lineItem)} />
                <CredentialRow label="CVV" value={lineItem?.dynamic_cvv} secret />
                <CredentialRow label="Name on Card" value="Prava User" />
                <CredentialRow label="Card Nickname" value="Prava" />
                <CredentialRow label="Save/Secure Card" value="Leave unchecked" />
              </div>

              <div className="flex flex-wrap gap-2">
                <a
                  href="https://instamart.in/cart"
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-2 rounded-lg border border-stone-200 px-3 py-2 text-sm font-semibold text-stone-700 hover:bg-stone-50"
                >
                  <ExternalLink className="h-4 w-4" aria-hidden="true" />
                  Open Swiggy cart
                </a>
                <button
                  type="button"
                  onClick={() => report('DECLINED')}
                  disabled={reported?.status === 'sending' || reported?.status === 'DECLINED'}
                  className="rounded-lg border border-red-200 px-3 py-2 text-sm font-semibold text-red-700 hover:bg-red-50 disabled:opacity-50"
                >
                  Report Swiggy declined
                </button>
                <button
                  type="button"
                  onClick={() => report('APPROVED')}
                  disabled={reported?.status === 'sending' || reported?.status === 'APPROVED'}
                  className="rounded-lg border border-emerald-200 px-3 py-2 text-sm font-semibold text-emerald-700 hover:bg-emerald-50 disabled:opacity-50"
                >
                  Report Swiggy accepted
                </button>
              </div>

              {reported?.status && reported.status !== 'sending' && (
                <div className="rounded-lg border border-stone-100 bg-stone-50 px-3 py-2 text-sm text-stone-700">
                  Reported {reported.status} to Prava.
                  {reported.merchantOutcome?.observation && (
                    <div className="mt-1 text-xs text-stone-500">{reported.merchantOutcome.observation}</div>
                  )}
                </div>
              )}
              {reported?.status === 'sending' && <p className="text-sm text-stone-500">Reporting outcome to Prava...</p>}
              */}
            </div>
          )}

          {phase === 'completed' && (
            <div className="rounded-lg border border-emerald-100 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
              Payment completed. {hasCredential ? 'One-time payment credential received.' : ''}
            </div>
          )}

          {phase === 'failed' && (
            <div className="rounded-lg border border-red-100 bg-red-50 px-3 py-2 text-sm text-red-700">
              Payment failed. {result?.transactions?.[0]?.error?.message || ''}
            </div>
          )}

          {phase === 'timed_out' && (
            <div className="rounded-lg border border-amber-100 bg-amber-50 px-3 py-2 text-sm text-amber-800">
              Payment result did not finish within 90 seconds.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
