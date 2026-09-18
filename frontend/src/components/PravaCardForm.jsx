import { useCallback, useEffect, useRef, useState } from 'react';
import { PravaSDK } from '@prava-sdk/core';

export default function PravaCardForm({ publishableKey, session, onError }) {
  const containerRef = useRef(null);
  const sdkRef = useRef(null);
  const hasStarted = useRef(false);
  const [loading, setLoading] = useState(true);
  const [sdkReady, setSdkReady] = useState(false);
  const [error, setError] = useState('');
  const [validationState, setValidationState] = useState(null);

  const mountSdk = useCallback(async () => {
    setLoading(true);
    setSdkReady(false);
    setError('');

    if (sdkRef.current) {
      sdkRef.current.destroy();
      sdkRef.current = null;
    }

    try {
      const sdk = new PravaSDK({ publishableKey });
      sdkRef.current = sdk;

      if (containerRef.current) {
        await sdk.collectPAN({
          sessionToken: session.session_token,
          iframeUrl: session.iframe_url,
          container: containerRef.current,
          onReady: () => {
            setSdkReady(true);
            setLoading(false);
          },
          onChange: (state) => setValidationState(state),
          onSuccess: () => {},
          onError: (err) => {
            setError(err.message);
            onError?.(err);
          },
        });
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown Prava SDK error';
      setError(message);
      onError?.(err instanceof Error ? err : new Error(message));
      setLoading(false);
    }
  }, [onError, publishableKey, session]);

  useEffect(() => {
    if (!hasStarted.current) {
      hasStarted.current = true;
      mountSdk();
    }

    return () => {
      sdkRef.current?.destroy();
      sdkRef.current = null;
      hasStarted.current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || sdkReady) return undefined;

    const hideLoading = () => {
      setSdkReady(true);
      setLoading(false);
    };

    const observer = new MutationObserver(() => {
      if (container.querySelector('iframe')) hideLoading();
    });
    observer.observe(container, { childList: true, subtree: true });

    const timeout = setTimeout(() => setLoading(false), 5000);

    return () => {
      observer.disconnect();
      clearTimeout(timeout);
    };
  }, [sdkReady]);

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      {error && (
        <div role="alert" className="rounded-lg border border-red-100 bg-red-50 px-3 py-2 text-sm text-red-700">
          <div>{error}</div>
          <button
            type="button"
            onClick={mountSdk}
            className="mt-2 rounded-md border border-red-200 bg-white px-3 py-1 text-xs font-semibold text-red-700 hover:bg-red-50"
          >
            Try again
          </button>
        </div>
      )}

      {loading && !sdkReady && !error && (
        <div className="rounded-lg border border-stone-100 bg-stone-50 px-3 py-2 text-sm text-stone-500">
          Loading secure payment form...
        </div>
      )}

      {validationState && sdkReady && (
        <div className="flex flex-wrap gap-2 text-xs text-stone-500">
          <span className={validationState.cardNumber?.isValid ? 'text-emerald-700' : ''}>Card</span>
          <span className={validationState.expiry?.isValid ? 'text-emerald-700' : ''}>Expiry</span>
          <span className={validationState.cvv?.isValid ? 'text-emerald-700' : ''}>CVV</span>
        </div>
      )}

      <div
        ref={containerRef}
        id="prava-card-form"
        className="min-h-[560px] flex-1 overflow-hidden rounded-lg border border-stone-100 [&>iframe]:h-full [&>iframe]:min-h-[560px] [&>iframe]:w-full"
      />
    </div>
  );
}
