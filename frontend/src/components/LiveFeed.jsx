import React, { useEffect, useRef, useState } from 'react';
import { Activity } from 'lucide-react';
import { getLivePrice, getWatchlist, shortAddr } from '../services/api';

const MIN_BTC = 0.5;      // show mempool transactions at or above this value
const MAX_ITEMS = 24;

export default function LiveFeed({ onSelectAddress }) {
  const [feed, setFeed] = useState([]);
  const [status, setStatus] = useState('Connecting...');
  const [btcPrice, setBtcPrice] = useState(0);
  const priceRef = useRef(0);
  const watchRef = useRef(new Map());

  useEffect(() => {
    let alive = true;
    const loadPrice = () => getLivePrice().then((p) => {
      if (alive && p?.usd) { setBtcPrice(p.usd); priceRef.current = p.usd; }
    });
    loadPrice();
    getWatchlist().then((w) => {
      watchRef.current = new Map((w.entities || []).map((e) => [e.address, e]));
    });
    const id = setInterval(loadPrice, 60000);
    return () => { alive = false; clearInterval(id); };
  }, []);

  useEffect(() => {
    let txWs;
    let blockWs;
    let timers = [];
    let closed = false;
    const push = (item) => setFeed((prev) => [item, ...prev.filter((p) => p.id !== item.id)].slice(0, MAX_ITEMS));

    const connectTx = () => {
      txWs = new WebSocket('wss://ws.blockchain.info/inv');
      txWs.onopen = () => {
        setStatus('Live Mempool Intercept');
        txWs.send(JSON.stringify({ op: 'unconfirmed_sub' }));
      };
      txWs.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          if (msg.op !== 'utx') return;
          const x = msg.x;
          const outs = (x.out || []).filter((o) => o.addr);
          const ins = (x.inputs || []).map((i) => i.prev_out).filter((p) => p && p.addr);
          const total = (x.out || []).reduce((s, o) => s + (o.value || 0), 0) / 1e8;
          const hit = [...ins, ...outs].map((o) => watchRef.current.get(o.addr)).find(Boolean);
          if (total < MIN_BTC && !hit) return;
          const top = [...outs].sort((a, b) => b.value - a.value)[0];
          push({
            id: x.hash,
            address: hit ? hit.address : top?.addr,
            label: hit ? `${hit.icon} ${hit.name}` : shortAddr(top?.addr, 8, 4),
            action: hit ? (hit.illicit ? 'WATCHLIST HIT' : 'KNOWN ENTITY') : total >= 10 ? '🐋 WHALE' : total >= 1 ? 'HIGH VALUE' : 'INTERCEPTED',
            kind: hit ? (hit.illicit ? 'hit' : 'known') : total >= 10 ? 'whale' : total >= 1 ? 'high' : 'tx',
            amount: `${total.toFixed(4)} BTC`,
            usd: priceRef.current ? Math.round(total * priceRef.current) : null,
            time: new Date().toLocaleTimeString(),
          });
        } catch { /* ignore malformed frames */ }
      };
      txWs.onclose = () => {
        if (closed) return;
        setStatus('Reconnecting...');
        timers.push(setTimeout(connectTx, 5000));
      };
      txWs.onerror = () => txWs.close();
    };

    const connectBlocks = () => {
      blockWs = new WebSocket('wss://mempool.space/api/v1/ws');
      blockWs.onopen = () => blockWs.send(JSON.stringify({ action: 'want', data: ['blocks'] }));
      blockWs.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.block) {
            push({
              id: `block-${data.block.height}`, address: null, label: `Block ${data.block.height.toLocaleString()}`,
              action: 'MINED', kind: 'block', amount: `${data.block.tx_count?.toLocaleString() || '?'} txs`, usd: null,
              time: new Date().toLocaleTimeString(),
            });
          }
        } catch { /* ignore */ }
      };
      blockWs.onclose = () => { if (!closed) timers.push(setTimeout(connectBlocks, 8000)); };
      blockWs.onerror = () => blockWs.close();
    };

    connectTx();
    connectBlocks();
    return () => {
      closed = true;
      timers.forEach(clearTimeout);
      timers = [];
      txWs?.close();
      blockWs?.close();
    };
  }, []);

  const badge = {
    hit: 'bg-red-500/25 text-red-300 border-red-500/60 font-black animate-pulse',
    known: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/40',
    whale: 'bg-amber-500/20 text-amber-300 border-amber-500/50 font-black',
    high: 'bg-orange-500/15 text-orange-300 border-orange-500/40',
    block: 'bg-indigo-500/20 text-indigo-300 border-indigo-500/50',
    tx: 'bg-cyan-500/15 text-cyan-300 border-cyan-500/40',
  };
  const live = status.includes('Live');
  const loop = feed.length ? [...feed, ...feed] : [];

  return (
    <div className="bg-[#020617] border-t border-cyan-500/30 flex items-center px-4 py-2 fixed bottom-0 w-full z-50 shadow-[0_-5px_20px_rgba(0,240,255,0.1)] no-print">
      <div className="flex items-center gap-2 mr-4 border-r border-cyan-500/30 pr-4 shrink-0">
        <Activity className={`w-4 h-4 ${live ? 'text-cyan-400 animate-pulse' : 'text-yellow-400'}`} />
        <span className={`text-[11px] font-black uppercase tracking-widest font-display ${live ? 'neon-text-cyan' : 'text-yellow-400'}`}>{status}</span>
      </div>
      {btcPrice > 0 && (
        <div className="flex items-center gap-1.5 mr-4 border-r border-cyan-500/30 pr-4 shrink-0">
          <span className="text-amber-400 text-xs font-bold">₿</span>
          <span className="text-xs font-mono font-bold text-slate-200">${btcPrice.toLocaleString()}</span>
        </div>
      )}
      <div className="overflow-hidden flex-1 relative h-6">
        {feed.length === 0 ? (
          <div className="text-xs text-slate-500 font-mono leading-6">AWAITING MEMPOOL DATA (≥ {MIN_BTC} BTC or watchlist hits)...</div>
        ) : (
          <div className="flex gap-8 absolute whitespace-nowrap font-mono animate-marquee">
            {loop.map((item, i) => (
              <button key={`${item.id}-${i}`} type="button" disabled={!item.address}
                onClick={() => item.address && onSelectAddress && onSelectAddress(item.address)}
                className="flex items-center gap-2.5 text-xs leading-6 enabled:cursor-pointer enabled:hover:opacity-80">
                <span className="text-cyan-700">[{item.time}]</span>
                <span className="font-bold text-slate-300">{item.label}</span>
                <span className={`px-2 rounded-sm uppercase tracking-wider text-[10px] border ${badge[item.kind]}`}>{item.action}</span>
                <span className="text-slate-300 font-bold">{item.amount}</span>
                {item.usd && <span className="text-slate-500 text-[10px]">(${item.usd.toLocaleString()})</span>}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
