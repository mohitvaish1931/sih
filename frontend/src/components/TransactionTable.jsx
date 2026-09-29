import React, { useMemo, useState } from 'react';
import { ArrowDownLeft, ArrowUpRight, Repeat, ExternalLink, Radio } from 'lucide-react';
import { formatBTC, formatUSD, shortAddr, txLink } from '../services/api';

const DIR = {
  received: { icon: ArrowDownLeft, cls: 'text-emerald-300', label: 'IN' },
  sent: { icon: ArrowUpRight, cls: 'text-red-300', label: 'OUT' },
  both: { icon: Repeat, cls: 'text-amber-300', label: 'OUT+CHG' },
};

export default function TransactionTable({ transactions = [] }) {
  const [filter, setFilter] = useState('all');
  const rows = useMemo(() => transactions.filter((t) => filter === 'all'
    || (filter === 'in' ? t.direction === 'received' : t.direction !== 'received')), [transactions, filter]);

  return (
    <div className="h-full flex flex-col min-h-0">
      <div className="flex items-center justify-between gap-2 mb-2">
        <span className="text-[10px] font-mono text-slate-400">{rows.length} of {transactions.length} most recent</span>
        <div className="flex gap-1">
          {['all', 'in', 'out'].map((f) => (
            <button key={f} type="button" onClick={() => setFilter(f)}
              className={`px-2 py-0.5 text-[10px] font-mono rounded border cursor-pointer uppercase ${filter === f ? 'border-cyan-400 text-cyan-200 bg-cyan-500/10' : 'border-slate-700 text-slate-400'}`}>{f}</button>
          ))}
        </div>
      </div>
      <div className="flex-1 overflow-auto custom-scrollbar min-h-0">
        <table className="w-full text-[11px] font-mono">
          <thead className="sticky top-0 bg-slate-950 text-slate-500 text-[10px] tracking-widest">
            <tr>
              <th className="text-left py-1.5 px-2">TIME (UTC)</th>
              <th className="text-left py-1.5 px-2">DIR</th>
              <th className="text-right py-1.5 px-2">VALUE</th>
              <th className="text-left py-1.5 px-2">COUNTERPARTY</th>
              <th className="text-left py-1.5 px-2">TX</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((t) => {
              const d = DIR[t.direction] || DIR.received;
              const Icon = d.icon;
              const href = txLink(t.txid);
              return (
                <tr key={t.txid} className="border-t border-slate-800/80 hover:bg-slate-900/70">
                  <td className="py-1.5 px-2 text-slate-400 whitespace-nowrap">
                    {t.timestamp ? t.timestamp.slice(0, 16).replace('T', ' ') : <span className="text-amber-300">mempool</span>}
                  </td>
                  <td className={`py-1.5 px-2 ${d.cls}`}><span className="flex items-center gap-1"><Icon className="w-3 h-3" />{d.label}</span></td>
                  <td className="py-1.5 px-2 text-right text-slate-200 whitespace-nowrap" title={formatUSD(t.value_usd)}>{formatBTC(t.value_btc)}</td>
                  <td className="py-1.5 px-2 text-slate-400 truncate max-w-[160px]" title={t.counterparties.join('\n')}>
                    {t.counterparties[0] ? shortAddr(t.counterparties[0], 8, 4) : '—'}
                    {t.counterparties.length > 1 && <span className="text-slate-600"> +{t.counterparties.length - 1}</span>}
                  </td>
                  <td className="py-1.5 px-2 whitespace-nowrap">
                    <span className="flex items-center gap-1">
                      {href ? <a href={href} target="_blank" rel="noreferrer" className="text-cyan-400 hover:text-cyan-200 flex items-center gap-0.5">{shortAddr(t.txid, 6, 4)}<ExternalLink className="w-2.5 h-2.5" /></a>
                        : <span className="text-slate-500">{shortAddr(t.txid, 6, 4)}</span>}
                      {t.has_telemetry && <Radio className="w-3 h-3 text-fuchsia-400" aria-label="relay telemetry available" />}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {rows.length === 0 && <div className="text-center text-slate-500 text-xs py-8">No transactions</div>}
      </div>
    </div>
  );
}
