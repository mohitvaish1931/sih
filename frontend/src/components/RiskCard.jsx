import React, { useEffect, useState } from 'react';
import { AlertTriangle, ShieldCheck, Activity, Wallet, Clock, Tag, Gauge, Info } from 'lucide-react';
import { formatUSD, formatBTC, SEVERITY_STYLES } from '../services/api';

const LEVEL_ICON = { CRITICAL: AlertTriangle, HIGH: AlertTriangle, MEDIUM: Activity, LOW: ShieldCheck };
const COMPONENT_COLORS = { behaviour: '#f97316', exposure: '#ff003c', anomaly: '#a855f7', geo: '#22d3ee' };

function useAnimatedNumber(target, duration = 1200) {
  const [value, setValue] = useState(0);
  useEffect(() => {
    let raf;
    const start = performance.now();
    const tick = (now) => {
      const t = Math.min(1, (now - start) / duration);
      setValue(target * (1 - Math.pow(1 - t, 3)));
      if (t < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, duration]);
  return value;
}

export default function RiskCard({ analysis }) {
  const score = analysis?.risk_score || 0;
  const level = analysis?.risk_level || 'LOW';
  const stats = analysis?.statistics || {};
  const entity = analysis?.entity || {};
  const balance = analysis?.balance || {};
  const confidence = analysis?.confidence || {};
  const sev = SEVERITY_STYLES[level] || SEVERITY_STYLES.LOW;
  const Icon = LEVEL_ICON[level] || ShieldCheck;
  const animated = useAnimatedNumber(score);

  const radius = 60;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (animated / 100) * circumference;

  const age = (() => {
    if (!stats.first_seen) return null;
    const days = Math.floor((new Date(stats.last_seen || stats.first_seen) - new Date(stats.first_seen)) / 86400000);
    if (days > 365) return `${Math.floor(days / 365)}y ${days % 365}d`;
    if (days > 30) return `${Math.floor(days / 30)}m ${days % 30}d`;
    return `${days}d`;
  })();

  return (
    <div className="hud-panel p-5 flex flex-col gap-4 relative overflow-hidden">
      <div className="absolute top-0 left-1/2 -translate-x-1/2 w-40 h-40 blur-3xl opacity-20 rounded-full pointer-events-none"
        style={{ background: sev.hex }} />

      {entity.is_known && (
        <div className="flex items-center gap-2 bg-slate-900/80 px-3 py-2 rounded-lg border relative z-10"
          style={{ borderColor: `${entity.color}66` }}>
          <span className="text-lg">{entity.icon || '❓'}</span>
          <div className="flex-1 min-w-0">
            <div className="text-sm font-bold text-slate-100 truncate">{entity.entity_name}</div>
            <div className="text-[10px] uppercase tracking-wider font-mono" style={{ color: entity.color }}>
              {entity.category_label} · {entity.confidence || 'medium'} confidence · {entity.source}
            </div>
          </div>
          <Tag className="w-3.5 h-3.5 text-slate-500 shrink-0" />
        </div>
      )}

      <div className="text-center relative z-10 flex flex-col items-center">
        <h2 className="section-title mb-3">Fused Risk Score</h2>
        <div className="relative w-40 h-40 flex items-center justify-center mb-2" role="img"
          aria-label={`Risk score ${Math.round(score)} of 100, ${level}`}>
          <svg className="absolute inset-0 w-full h-full -rotate-90" viewBox="0 0 160 160">
            <circle cx="80" cy="80" r={radius} stroke="#0b1224" strokeWidth="12" fill="transparent" />
            <circle cx="80" cy="80" r={radius} stroke={sev.hex} strokeWidth="12" fill="transparent"
              strokeDasharray={circumference} strokeDashoffset={offset} strokeLinecap="round"
              style={{ filter: `drop-shadow(0 0 8px ${sev.hex})` }} />
          </svg>
          <div className="absolute inset-0 flex flex-col items-center justify-center">
            <Icon className={`w-6 h-6 mb-1 ${sev.text} opacity-90`} />
            <div className={`text-4xl font-black font-display ${sev.text}`}>{Math.round(animated)}</div>
            <div className="text-[10px] text-slate-500 font-mono">/ 100</div>
          </div>
        </div>
        <div className={`text-xl font-black tracking-widest font-display ${sev.text}`}>{level} RISK</div>
        <div className="mt-1 flex items-center gap-1.5 text-[10px] font-mono text-slate-400" title={confidence.note}>
          <Gauge className="w-3 h-3" /> CONFIDENCE {confidence.level || '—'} · {confidence.note}
        </div>
      </div>

      {/* Explainable breakdown */}
      <div className="space-y-2 relative z-10">
        <div className="text-[10px] font-mono text-slate-400 tracking-widest uppercase">Why this score</div>
        {(analysis?.score_breakdown || []).map((b) => (
          <div key={b.component} title={b.summary}>
            <div className="flex justify-between text-[11px] font-mono">
              <span className={b.available ? 'text-slate-300' : 'text-slate-600'}>{b.label}</span>
              <span className="text-slate-400">
                {b.available ? `${Math.round(b.score)} → +${Math.round(b.contribution)}` : 'n/a'}
              </span>
            </div>
            <div className="h-1.5 bg-slate-800 rounded-full overflow-hidden mt-0.5">
              <div className="h-full rounded-full transition-all duration-700"
                style={{ width: `${b.available ? b.score : 0}%`, background: COMPONENT_COLORS[b.component] }} />
            </div>
          </div>
        ))}
        {(analysis?.adjustments || []).map((a) => (
          <div key={a.type} className="flex gap-1.5 text-[10px] text-slate-400 font-mono bg-slate-900/60 border border-slate-800 rounded px-2 py-1.5">
            <Info className="w-3 h-3 shrink-0 mt-0.5 text-cyan-500" /> <span>{a.detail}</span>
          </div>
        ))}
      </div>

      <div className="h-px w-full bg-slate-700/50" />

      {balance.available !== false && (
        <div className="bg-[#020617] p-3 rounded-md border border-amber-500/20">
          <div className="flex items-center gap-1.5 mb-1">
            <Wallet className="w-3.5 h-3.5 text-amber-400" />
            <span className="text-[10px] text-amber-500/80 font-mono tracking-widest">CURRENT BALANCE</span>
          </div>
          <div className="text-lg font-bold text-amber-400">{formatBTC(balance.confirmed_btc)}</div>
          <div className="text-xs font-mono text-slate-400">{formatUSD(balance.confirmed_usd)}
            {balance.unconfirmed_btc ? <span className="text-amber-300/70"> · {formatBTC(balance.unconfirmed_btc)} pending</span> : null}
          </div>
        </div>
      )}

      {stats.first_seen && (
        <div className="flex flex-wrap items-center gap-2 text-[11px] text-slate-400 font-mono bg-slate-900/40 px-3 py-2 rounded-md border border-slate-800">
          <Clock className="w-3.5 h-3.5 text-slate-500" />
          <span>Active span: <span className="text-slate-200 font-semibold">{age}</span></span>
          <span className="text-slate-600">|</span>
          <span>Last: {new Date(stats.last_seen).toLocaleDateString()}</span>
        </div>
      )}

      <div className="grid grid-cols-2 gap-2.5 font-mono">
        <StatCard label="TXS ANALYSED" value={stats.transactions_count || 0}
          subValue={stats.onchain_tx_count > stats.transactions_count ? `of ${Number(stats.onchain_tx_count).toLocaleString()} on-chain` : 'full history'} />
        <StatCard label="COUNTERPARTIES" value={stats.connected_wallets || 0} />
        <StatCard label="INFLOW" value={formatBTC(stats.total_received_btc)} subValue={formatUSD(stats.total_received_usd)} />
        <StatCard label="OUTFLOW" value={formatBTC(stats.total_sent_btc)} subValue={formatUSD(stats.total_sent_usd)} />
      </div>
    </div>
  );
}

function StatCard({ label, value, subValue }) {
  return (
    <div className="bg-[#020617] p-2.5 rounded-md border border-cyan-500/15 min-w-0">
      <div className="text-[10px] text-cyan-500/70 mb-0.5 tracking-widest">{label}</div>
      <div className="text-sm font-bold text-cyan-300 truncate" title={String(value)}>{value}</div>
      {subValue && <div className="text-[10px] text-slate-500 truncate">{subValue}</div>}
    </div>
  );
}
