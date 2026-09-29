import React, { useCallback, useEffect, useState } from 'react';
import { Bell, AlertOctagon, Check } from 'lucide-react';
import { acknowledgeAlert, getAlerts, shortAddr, timeAgo, SEVERITY_STYLES } from '../services/api';

/** Alerts persisted by the backend (investigations + live monitor), newest first. */
export default function AlertPanel({ wallet, refreshKey = 0, onSelectWallet, limit = 8, title = 'Threat Alerts' }) {
  const [alerts, setAlerts] = useState([]);
  const [loaded, setLoaded] = useState(false);

  const load = useCallback(async () => {
    const res = await getAlerts({ limit, ...(wallet ? { wallet } : {}) });
    setAlerts(res.alerts || []);
    setLoaded(true);
  }, [wallet, limit]);

  useEffect(() => {
    let cancelled = false;
    getAlerts({ limit, ...(wallet ? { wallet } : {}) }).then((res) => {
      if (!cancelled) { setAlerts(res.alerts || []); setLoaded(true); }
    });
    const id = setInterval(() => { if (!cancelled) load(); }, 30000);
    return () => { cancelled = true; clearInterval(id); };
  }, [wallet, limit, refreshKey, load]);

  const ack = async (id) => {
    try {
      await acknowledgeAlert(id);
      setAlerts((prev) => prev.map((a) => (a.id === id ? { ...a, acknowledged: true } : a)));
    } catch { /* ignore - list refreshes on its own */ }
  };

  return (
    <div className="hud-panel p-5 flex flex-col relative overflow-hidden">
      <div className="flex items-center justify-between mb-3 border-b border-cyan-500/20 pb-2">
        <h3 className="section-title flex items-center gap-2">
          <span className="relative">
            <Bell className="w-4 h-4" />
            {alerts.some((a) => !a.acknowledged) && <span className="absolute -top-1 -right-1 w-2 h-2 rounded-full bg-red-500 animate-ping" />}
          </span>
          {title}
        </h3>
        <span className="text-[10px] text-slate-500 font-mono">{wallet ? 'THIS WALLET' : 'ALL CASES'}</span>
      </div>

      {loaded && alerts.length === 0 && (
        <p className="text-xs text-slate-500 font-body py-4 text-center">No alerts yet. Alerts are raised by investigations and live monitoring.</p>
      )}

      <div className="space-y-2 overflow-y-auto pr-1 custom-scrollbar max-h-80">
        {alerts.map((a) => {
          const s = SEVERITY_STYLES[a.severity] || SEVERITY_STYLES.LOW;
          return (
            <div key={a.id} className={`flex items-start gap-2.5 p-2.5 bg-slate-900/60 rounded-sm border-l-2 ${s.border} ${a.acknowledged ? 'opacity-50' : ''}`}>
              <AlertOctagon className={`w-4 h-4 shrink-0 mt-0.5 ${s.text}`} />
              <div className="flex-1 min-w-0">
                <div className="flex justify-between items-start gap-2">
                  <div className={`text-xs font-bold font-mono tracking-wide ${s.text}`}>{a.type}</div>
                  <div className="text-[9px] text-slate-500 font-mono shrink-0">{timeAgo(a.created_at)}</div>
                </div>
                <div className="text-[11px] text-slate-400 font-body leading-snug mt-0.5 line-clamp-2">{a.reason}</div>
                <div className="flex items-center justify-between mt-1">
                  {!wallet ? (
                    <button type="button" onClick={() => onSelectWallet && onSelectWallet(a.wallet)}
                      className="text-[10px] font-mono text-cyan-500 hover:text-cyan-300 cursor-pointer truncate">{shortAddr(a.wallet, 10, 6)}</button>
                  ) : <span />}
                  {!a.acknowledged && (
                    <button type="button" onClick={() => ack(a.id)} aria-label="Acknowledge alert"
                      className="text-[10px] font-mono text-slate-500 hover:text-emerald-300 flex items-center gap-0.5 cursor-pointer">
                      <Check className="w-3 h-3" /> ACK
                    </button>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
