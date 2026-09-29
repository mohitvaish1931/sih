import React, { useEffect, useRef, useState } from 'react';
import { monitorWallet, formatBTC } from '../services/api';
import { Radio, X, Zap, AlertTriangle } from 'lucide-react';

export default function WalletMonitorAlert({ address, isMonitoring, onNewTransaction }) {
  const [alerts, setAlerts] = useState([]);
  const [connected, setConnected] = useState(false);
  const [showBanner, setShowBanner] = useState(false);
  const callbackRef = useRef(onNewTransaction);
  useEffect(() => { callbackRef.current = onNewTransaction; }, [onNewTransaction]);

  useEffect(() => {
    if (!isMonitoring || !address) return undefined;
    let hideTimer;
    const close = monitorWallet(
      address,
      (data) => {
        if (data.type === 'connected') {
          setConnected(true);
        } else if (data.type === 'new_transactions') {
          const fresh = data.transactions.map((tx) => ({ ...tx, id: tx.txid, time: new Date().toLocaleTimeString() }));
          setAlerts((prev) => [...fresh, ...prev].slice(0, 20));
          setShowBanner(true);
          document.body.classList.add('monitor-flash');
          setTimeout(() => document.body.classList.remove('monitor-flash'), 800);
          data.transactions.forEach((tx) => callbackRef.current && callbackRef.current(tx));
          clearTimeout(hideTimer);
          hideTimer = setTimeout(() => setShowBanner(false), 10000);
        }
      },
      () => setConnected(false),
    );
    return () => {
      clearTimeout(hideTimer);
      close();
      setConnected(false);
    };
  }, [isMonitoring, address]);

  if (!isMonitoring) return null;

  return (
    <>
      <div className={`fixed top-24 right-4 z-50 px-3 py-1.5 rounded-full text-xs font-mono font-semibold flex items-center gap-2 border no-print ${
        connected ? 'bg-emerald-500/10 text-emerald-300 border-emerald-500/40' : 'bg-yellow-500/10 text-yellow-300 border-yellow-500/40 animate-pulse'
      }`} role="status">
        <Radio className="w-3.5 h-3.5" />
        <span>{connected ? 'LIVE MONITORING · 15s POLL' : 'CONNECTING...'}</span>
      </div>

      {showBanner && alerts.length > 0 && (
        <div className="fixed top-36 right-4 z-50 w-96 max-w-[calc(100vw-2rem)] animate-fade-up no-print" role="alert">
          <div className="bg-red-950/95 backdrop-blur-xl border-2 border-red-500/60 rounded-xl p-4 shadow-[0_0_30px_rgba(239,68,68,0.3)]">
            <div className="flex items-start justify-between mb-3">
              <div className="flex items-center gap-2">
                <AlertTriangle className="w-5 h-5 text-red-400 animate-bounce" />
                <span className="text-red-300 font-black font-display text-sm tracking-wider">WATCHED WALLET MOVED</span>
              </div>
              <button type="button" aria-label="Dismiss" onClick={() => setShowBanner(false)} className="p-1 hover:bg-red-500/20 rounded cursor-pointer">
                <X className="w-4 h-4 text-red-300/70" />
              </button>
            </div>
            <div className="space-y-2">
              {alerts.slice(0, 3).map((a) => (
                <div key={a.id} className="bg-black/40 rounded-lg p-2.5 border border-red-500/20">
                  <div className="flex items-center justify-between text-xs font-mono">
                    <span className="flex items-center gap-2 text-slate-300"><Zap className="w-3.5 h-3.5 text-amber-400" />
                      {a.direction === 'received' ? 'INCOMING' : 'OUTGOING'}{a.confirmed ? '' : ' · UNCONFIRMED'}</span>
                    <span className="text-slate-500">{a.time}</span>
                  </div>
                  <div className="flex items-center gap-3 mt-1">
                    <span className="text-lg font-black font-mono text-amber-400">{formatBTC(a.value_btc)}</span>
                    <span className="text-sm font-mono text-slate-400">≈ ${a.value_usd?.toLocaleString()}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
