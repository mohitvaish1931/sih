import React from 'react';
import { Biohazard, Landmark, Network } from 'lucide-react';
import { formatBTC, shortAddr } from '../services/api';

export default function ExposurePanel({ exposure = {}, cluster = {} }) {
  const direct = exposure.direct || [];
  const indirect = exposure.indirect || [];
  const cashout = exposure.cashout_exchanges || [];
  const funding = exposure.funding_exchanges || [];
  const attributed = cluster.attributed_entity;

  return (
    <div className="hud-panel p-5 flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h3 className="section-title flex items-center gap-2"><Biohazard className="w-4 h-4" /> Illicit Exposure</h3>
        <span className={`text-xs font-mono font-bold ${exposure.score >= 60 ? 'text-red-400' : exposure.score > 0 ? 'text-amber-300' : 'text-emerald-300'}`}>
          {Math.round(exposure.score || 0)}/100
        </span>
      </div>

      {direct.length === 0 && indirect.length === 0 ? (
        <p className="text-xs text-slate-400 font-body">No value exchanged with illicit-attributed counterparties in the analysed window.</p>
      ) : (
        <div className="space-y-1.5">
          {direct.map((d) => (
            <div key={d.address} className="flex items-center gap-2 text-xs bg-red-950/30 border border-red-500/30 rounded px-2 py-1.5">
              <span>{d.icon}</span>
              <div className="flex-1 min-w-0">
                <div className="text-red-200 font-bold truncate">{d.entity_name}</div>
                <div className="text-[10px] text-red-300/70 font-mono">
                  {d.category_label} · hop 1 · {d.received_from_btc > 0 ? `in ${formatBTC(d.received_from_btc)}` : ''}
                  {d.sent_to_btc > 0 ? ` out ${formatBTC(d.sent_to_btc)}` : ''}
                </div>
              </div>
              <span className="text-[10px] font-mono text-red-300">{(d.share * 100).toFixed(1)}%</span>
            </div>
          ))}
          {indirect.slice(0, 4).map((d, i) => (
            <div key={d.entity_address + i} className="flex items-center gap-2 text-xs bg-amber-950/20 border border-amber-500/25 rounded px-2 py-1.5">
              <span>{d.icon}</span>
              <div className="flex-1 min-w-0">
                <div className="text-amber-200 truncate">{d.entity_name}</div>
                <div className="text-[10px] text-amber-300/70 font-mono truncate">hop 2 via {shortAddr(d.via, 10, 4)}</div>
              </div>
            </div>
          ))}
        </div>
      )}

      {(cashout.length > 0 || funding.length > 0) && (
        <div>
          <div className="text-[10px] font-mono tracking-widest text-slate-400 uppercase mb-1.5 flex items-center gap-1.5">
            <Landmark className="w-3.5 h-3.5" /> Regulated touch-points (KYC leads)
          </div>
          <div className="space-y-1">
            {cashout.map((c) => (
              <div key={`o${c.address}`} className="text-[11px] font-mono flex justify-between gap-2 text-emerald-200">
                <span className="truncate">→ {c.exchange}</span><span>{formatBTC(c.btc)}</span>
              </div>
            ))}
            {funding.map((c) => (
              <div key={`i${c.address}`} className="text-[11px] font-mono flex justify-between gap-2 text-sky-200">
                <span className="truncate">← {c.exchange}</span><span>{formatBTC(c.btc)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="border-t border-slate-800 pt-3">
        <div className="text-[10px] font-mono tracking-widest text-slate-400 uppercase mb-1 flex items-center gap-1.5">
          <Network className="w-3.5 h-3.5" /> Ownership cluster
        </div>
        {cluster.size > 1 ? (
          <div className="text-xs text-slate-300 font-body">
            <span className="font-mono text-cyan-300">{cluster.cluster_id}</span> · {cluster.size} addresses via {cluster.co_spend_txs} co-spend tx(s)
            {attributed && <div className="text-emerald-300 mt-0.5">Attributed to {attributed.entity_name} ({attributed.members} member tags)</div>}
            {cluster.coinjoins_excluded > 0 && <div className="text-[10px] text-slate-500 mt-0.5">{cluster.coinjoins_excluded} CoinJoin(s) excluded from clustering</div>}
          </div>
        ) : (
          <div className="text-xs text-slate-500 font-body">
            No co-spent inputs - address not linked to others by common-input-ownership
            {cluster.coinjoins_excluded > 0 ? ` (${cluster.coinjoins_excluded} CoinJoin(s) excluded)` : ''}.
          </div>
        )}
      </div>
    </div>
  );
}
