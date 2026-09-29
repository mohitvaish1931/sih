import React, { useState } from 'react';
import { ChevronDown, ChevronRight, CheckCircle2, ExternalLink, Microscope } from 'lucide-react';
import { SEVERITY_STYLES, shortAddr, txLink } from '../services/api';

function TxRef({ txid }) {
  const href = txLink(txid);
  return href ? (
    <a href={href} target="_blank" rel="noreferrer" className="text-cyan-400 hover:text-cyan-200 inline-flex items-center gap-0.5">
      {shortAddr(txid, 8, 4)}<ExternalLink className="w-2.5 h-2.5" />
    </a>
  ) : <span className="text-slate-400">{shortAddr(txid, 8, 4)}</span>;
}

function Evidence({ finding }) {
  const ev = finding.evidence || {};
  const txids = [
    ...(ev.pairs || []).flatMap((p) => [p.in_txid, p.out_txid]),
    ...(ev.hops || []).map((h) => h.txid),
    ...(ev.coinjoins || []).map((c) => c.txid),
    ...(ev.widest_tx ? [ev.widest_tx.txid] : []),
    ...(ev.txid ? [ev.txid] : []),
  ].filter(Boolean);
  const unique = [...new Set(txids)].slice(0, 8);
  const metrics = Object.entries(ev).filter(([, v]) => typeof v === 'number' || typeof v === 'string');

  return (
    <div className="mt-2 space-y-2 text-[11px] font-mono">
      <div className="text-slate-500 italic">{finding.typology}</div>
      {metrics.length > 0 && (
        <div className="grid grid-cols-2 gap-x-3 gap-y-0.5">
          {metrics.slice(0, 8).map(([k, v]) => (
            <div key={k} className="flex justify-between gap-2 min-w-0">
              <span className="text-slate-500 truncate">{k.replaceAll('_', ' ')}</span>
              <span className="text-slate-300 truncate">{typeof v === 'number' ? +v.toFixed(4) : String(v).slice(0, 19)}</span>
            </div>
          ))}
        </div>
      )}
      {ev.hops?.length > 0 && (
        <div className="space-y-0.5 max-h-36 overflow-y-auto custom-scrollbar pr-1">
          {ev.hops.slice(0, 12).map((h, i) => (
            <div key={h.txid + i} className="flex items-center gap-1.5 text-slate-400">
              <span className="text-slate-600 w-4">{i + 1}</span>
              <span className="truncate">{shortAddr(h.from, 10, 4)}</span>
              <span className="text-orange-400">−{h.peeled_btc}</span>
              <span className="text-slate-600">→</span>
              <span className="truncate text-slate-300">{shortAddr(h.remainder_to, 10, 4)}</span>
            </div>
          ))}
          {ev.terminal && (
            <div className="text-emerald-300 pt-1">
              ⇢ terminus: {ev.terminal.entity_name || shortAddr(ev.terminal.address)} ({ev.terminal.btc} BTC)
            </div>
          )}
        </div>
      )}
      {unique.length > 0 && (
        <div className="flex flex-wrap gap-x-3 gap-y-1">
          <span className="text-slate-500">evidence txs:</span>
          {unique.map((t) => <TxRef key={t} txid={t} />)}
        </div>
      )}
    </div>
  );
}

export default function FindingsPanel({ findings = [], exposure }) {
  const [open, setOpen] = useState(() => new Set(findings.slice(0, 1).map((f) => f.id)));
  const visible = findings.filter((f) => f.severity !== 'INFO');
  const info = findings.filter((f) => f.severity === 'INFO');
  const toggle = (id) => setOpen((prev) => {
    const next = new Set(prev);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });

  return (
    <div className="hud-panel p-5 flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <h3 className="section-title flex items-center gap-2"><Microscope className="w-4 h-4" /> Typology Findings</h3>
        <span className="text-[10px] font-mono text-slate-500">{visible.length} triggered</span>
      </div>

      {visible.length === 0 && !(exposure?.direct?.length) ? (
        <div className="flex items-center gap-3 text-emerald-300 bg-emerald-400/10 border border-emerald-400/20 p-3 rounded-lg text-sm">
          <CheckCircle2 className="w-5 h-5 shrink-0" />
          No laundering typology triggered (peel chain, pass-through, fan-in/out, CoinJoin, bursts, dormancy).
        </div>
      ) : (
        <div className="space-y-2 max-h-[460px] overflow-y-auto custom-scrollbar pr-1">
          {visible.map((f) => {
            const s = SEVERITY_STYLES[f.severity] || SEVERITY_STYLES.LOW;
            const isOpen = open.has(f.id);
            return (
              <div key={f.id} className={`rounded-md border-l-2 ${s.border} bg-slate-900/60 border border-slate-800`}>
                <button type="button" onClick={() => toggle(f.id)} aria-expanded={isOpen}
                  className="w-full text-left px-3 py-2.5 flex items-start gap-2 cursor-pointer">
                  {isOpen ? <ChevronDown className="w-4 h-4 text-slate-500 mt-0.5 shrink-0" /> : <ChevronRight className="w-4 h-4 text-slate-500 mt-0.5 shrink-0" />}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-sm font-bold text-slate-100">{f.title}</span>
                      <span className={`text-[10px] px-1.5 py-0.5 rounded font-mono ${s.bg} ${s.text} shrink-0`}>
                        {f.severity} · +{Math.round(f.points)}
                      </span>
                    </div>
                    <p className="text-xs text-slate-400 mt-1 leading-relaxed font-body">{f.summary}</p>
                    {isOpen && <Evidence finding={f} />}
                  </div>
                </button>
              </div>
            );
          })}
        </div>
      )}
      {info.map((f) => (
        <div key={f.id} className="text-[11px] text-slate-500 font-mono border border-slate-800 rounded px-2 py-1.5">
          ℹ {f.title}: {f.summary}
        </div>
      ))}
    </div>
  );
}
