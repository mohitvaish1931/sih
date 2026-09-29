import React from 'react';
import { Route, ArrowDown, ArrowUp, X, ExternalLink } from 'lucide-react';
import { formatBTC, shortAddr, txLink, addressLink } from '../services/api';

const MODE_LABEL = {
  outflow: 'funds flowed from the target along this path',
  inflow: 'funds reached the target along this path',
  linked: 'connected, but not by a single direction of flow',
};

export default function FundFlow({ graph, path, mode, onClear }) {
  if (!path || path.length < 2) {
    return (
      <div className="h-full flex flex-col">
        <h3 className="section-title flex items-center gap-2 mb-3"><Route className="w-4 h-4" /> Fund Flow Trace</h3>
        <p className="text-xs text-slate-500 text-center py-8 font-body">
          Click any node in the graph to trace how value moved between it and the target wallet.
        </p>
      </div>
    );
  }

  const nodes = new Map(graph.nodes.map((n) => [n.data.id, n.data]));
  const edgeBetween = (a, b) => graph.edges.find((e) => e.data.source === a && e.data.target === b)
    || graph.edges.find((e) => e.data.source === b && e.data.target === a);

  return (
    <div className="h-full flex flex-col min-h-0">
      <div className="flex justify-between items-center mb-3">
        <h3 className="section-title flex items-center gap-2"><Route className="w-4 h-4" /> Fund Flow Trace</h3>
        <div className="flex items-center gap-2">
          <span className="text-[10px] px-2 py-0.5 bg-yellow-500/15 text-yellow-300 rounded-full font-mono">{path.length - 1} hop(s)</span>
          <button type="button" onClick={onClear} aria-label="Clear trace" className="text-slate-500 hover:text-slate-200 cursor-pointer"><X className="w-4 h-4" /></button>
        </div>
      </div>
      {mode && <p className="text-[10px] font-mono text-slate-500 mb-2">{MODE_LABEL[mode]}</p>}
      <div className="flex-1 overflow-y-auto pr-1 space-y-1 custom-scrollbar min-h-0">
        {path.map((addr, i) => {
          const n = nodes.get(addr) || {};
          const next = path[i + 1];
          const edge = next ? edgeBetween(addr, next) : null;
          const forward = edge && edge.data.source === addr;
          const link = addressLink(addr);
          return (
            <React.Fragment key={addr}>
              <div className={`p-2.5 rounded-md border text-xs ${n.is_root ? 'border-red-500/50 bg-red-950/20' : n.illicit ? 'border-red-400/40 bg-red-950/10' : 'border-slate-700/60 bg-slate-900/70'}`}>
                <div className="flex items-center gap-2">
                  <span>{n.is_root ? '🎯' : n.entity_icon || '❓'}</span>
                  <div className="min-w-0 flex-1">
                    <div className="text-slate-100 font-semibold truncate">{n.entity_name || shortAddr(addr, 12, 6)}</div>
                    <div className="text-[10px] text-slate-500 font-mono truncate">{n.entity_name ? shortAddr(addr, 10, 6) : n.entity_category}</div>
                  </div>
                  {link && <a href={link} target="_blank" rel="noreferrer" aria-label="Open in explorer" className="text-slate-500 hover:text-cyan-300"><ExternalLink className="w-3.5 h-3.5" /></a>}
                </div>
              </div>
              {edge && (
                <div className="flex items-center gap-2 pl-4 py-0.5 text-[10px] font-mono">
                  {forward ? <ArrowDown className="w-3.5 h-3.5 text-yellow-400" /> : <ArrowUp className="w-3.5 h-3.5 text-sky-400" />}
                  <span className="text-slate-300">{formatBTC(edge.data.amount)}</span>
                  <span className="text-slate-500">{edge.data.tx_count} tx · {edge.data.kind}</span>
                  {txLink(edge.data.tx_hash) && (
                    <a href={txLink(edge.data.tx_hash)} target="_blank" rel="noreferrer" className="text-cyan-500 hover:text-cyan-300">{shortAddr(edge.data.tx_hash, 6, 4)}</a>
                  )}
                </div>
              )}
            </React.Fragment>
          );
        })}
      </div>
    </div>
  );
}
