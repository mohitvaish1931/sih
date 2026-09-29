import React, { useEffect, useState } from 'react';
import { getLiveMempool, getLiveBlocks, getLivePrice, getWhaleAlerts, getPlatformStats, getTelemetryStats } from '../services/api';
import { Activity, Box, TrendingUp, TrendingDown, Zap, Clock, Cpu, Flame, AlertTriangle, Satellite, FolderSearch } from 'lucide-react';
import AlertPanel from './AlertPanel';

export default function LiveBlockchainStats({ onSelectAddress }) {
  const [mempool, setMempool] = useState(null);
  const [blocks, setBlocks] = useState([]);
  const [price, setPrice] = useState(null);
  const [whales, setWhales] = useState([]);
  const [platform, setPlatform] = useState(null);
  const [telemetry, setTelemetry] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    const fetchAll = async () => {
      const [m, b, p, w, s, t] = await Promise.all([
        getLiveMempool(), getLiveBlocks(), getLivePrice(), getWhaleAlerts(), getPlatformStats(), getTelemetryStats(),
      ]);
      if (!alive) return;
      if (m) setMempool(m);
      if (b) setBlocks(b);
      if (p) setPrice(p);
      if (w) setWhales(w.whales || []);
      if (s) setPlatform(s);
      if (t) setTelemetry(t);
      setLoading(false);
    };
    fetchAll();
    const interval = setInterval(fetchAll, 30000);
    return () => { alive = false; clearInterval(interval); };
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="w-12 h-12 border-4 border-cyan-500/20 border-t-cyan-500 rounded-full animate-spin" />
      </div>
    );
  }

  const change = price?.usd_24h_change || 0;
  const up = change >= 0;

  return (
    <div className="space-y-6 animate-fade-up">
      <div className="hud-panel p-6">
        <div className="flex flex-col lg:flex-row items-center justify-between gap-6">
          <div className="flex items-center gap-4">
            <div className="p-3 bg-amber-500/10 rounded-xl border border-amber-500/30"><span className="text-3xl">₿</span></div>
            <div>
              <div className="text-xs text-slate-400 font-mono tracking-wider uppercase mb-1">Bitcoin / USD</div>
              <div className="text-4xl font-black font-display text-slate-100">${price?.usd?.toLocaleString() || '---'}</div>
              <div className={`flex items-center gap-1.5 text-sm font-mono font-semibold mt-1 ${up ? 'text-emerald-400' : 'text-red-400'}`}>
                {up ? <TrendingUp className="w-4 h-4" /> : <TrendingDown className="w-4 h-4" />}
                <span>{up ? '+' : ''}{change.toFixed(2)}% (24h)</span>
                {price?.inr ? <span className="text-slate-500 font-normal ml-2">₹{price.inr.toLocaleString('en-IN')}</span> : null}
              </div>
            </div>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <StatBox icon={<Activity className="w-4 h-4 text-cyan-400" />} label="MEMPOOL TXS" value={mempool?.tx_count?.toLocaleString() || '0'} sub="Pending" />
            <StatBox icon={<Box className="w-4 h-4 text-indigo-400" />} label="MEMPOOL SIZE" value={`${mempool?.size_mb || 0} MB`} sub="Virtual size" />
            <StatBox icon={<Flame className="w-4 h-4 text-orange-400" />} label="FASTEST FEE" value={`${mempool?.fee_fastest || 0} sat/vB`} sub="Next block" />
            <StatBox icon={<Cpu className="w-4 h-4 text-purple-400" />} label="LATEST BLOCK" value={blocks[0]?.height?.toLocaleString() || '---'} sub={blocks[0]?.pool_name || 'Unknown'} />
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <MiniStat icon={<FolderSearch className="w-4 h-4 text-cyan-400" />} label="Wallets investigated"
          value={platform?.wallets_investigated ?? 0}
          sub={platform ? `${platform.risk_levels?.CRITICAL || 0} critical · ${platform.risk_levels?.HIGH || 0} high` : ''} />
        <MiniStat icon={<Box className="w-4 h-4 text-indigo-400" />} label="Transactions indexed"
          value={(platform?.transactions_indexed ?? 0).toLocaleString()} sub={`${platform?.alerts ?? 0} alerts raised`} />
        <MiniStat icon={<Satellite className="w-4 h-4 text-fuchsia-400" />} label="Relay observations"
          value={(telemetry?.observations ?? 0).toLocaleString()}
          sub={telemetry?.last_observation ? `last ${new Date(telemetry.last_observation).toLocaleTimeString()} · ${telemetry.sensors?.length || 0} sensor(s)` : 'run sensor/relay_sensor.py'} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="hud-panel p-5">
          <h3 className="section-title mb-4 flex items-center gap-2"><Box className="w-4 h-4 text-indigo-400" /> Latest Blocks
            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" /></h3>
          <div className="space-y-2">
            {blocks.slice(0, 5).map((block) => (
              <div key={block.height} className="flex items-center justify-between p-2.5 bg-slate-900/60 rounded-lg border border-slate-800">
                <div>
                  <div className="text-sm font-bold font-mono text-slate-200">#{block.height?.toLocaleString()}</div>
                  <div className="text-[10px] text-slate-500 font-mono">{block.tx_count?.toLocaleString()} txs · {block.size_mb} MB</div>
                </div>
                <div className="text-right">
                  <div className="text-xs font-mono text-cyan-400">{block.pool_name}</div>
                  <div className="text-[10px] text-slate-500 flex items-center gap-1 justify-end">
                    <Clock className="w-3 h-3" />{block.timestamp ? new Date(block.timestamp * 1000).toLocaleTimeString() : '---'}
                  </div>
                </div>
              </div>
            ))}
            {blocks.length === 0 && <div className="text-xs text-slate-500 text-center py-6">Block data unavailable</div>}
          </div>
        </div>

        <div className="hud-panel p-5">
          <h3 className="section-title mb-4 flex items-center gap-2"><AlertTriangle className="w-4 h-4 text-amber-400" /> Whale Txs · Latest Block
            <span className="text-[10px] text-slate-500 font-normal normal-case tracking-normal">≥10 BTC</span></h3>
          <div className="space-y-2 max-h-[330px] overflow-y-auto pr-1 custom-scrollbar">
            {whales.length === 0 ? (
              <div className="text-xs text-slate-500 text-center py-8 font-mono">No whale transactions in latest block</div>
            ) : whales.map((w) => (
              <button key={w.txid} type="button" onClick={() => w.from_address && onSelectAddress && onSelectAddress(w.from_address)}
                title="Investigate the sending wallet"
                className="w-full text-left p-2.5 bg-slate-900/60 rounded-lg border border-slate-800 hover:border-amber-500/40 transition-colors cursor-pointer">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-sm font-mono font-bold text-amber-400">🐋 {w.value_btc} BTC</span>
                  <span className="text-xs font-mono text-slate-300">${w.value_usd?.toLocaleString()}</span>
                </div>
                <div className="flex items-center gap-2 text-[11px] text-slate-400 font-mono">
                  <span className="truncate">{w.from}</span><Zap className="w-3 h-3 text-cyan-500 shrink-0" /><span className="text-cyan-300 truncate">{w.to}</span>
                </div>
              </button>
            ))}
          </div>
        </div>

        <AlertPanel onSelectWallet={onSelectAddress} title="Recent Alerts" />
      </div>
    </div>
  );
}

function StatBox({ icon, label, value, sub }) {
  return (
    <div className="bg-[#020617] p-3 rounded-lg border border-slate-800 min-w-[120px]">
      <div className="flex items-center gap-1.5 mb-1.5">{icon}<span className="text-[10px] text-slate-500 font-mono tracking-wider">{label}</span></div>
      <div className="text-lg font-black font-mono text-slate-100">{value}</div>
      <div className="text-[10px] text-slate-500">{sub}</div>
    </div>
  );
}

function MiniStat({ icon, label, value, sub }) {
  return (
    <div className="hud-panel px-5 py-4 flex items-center gap-4">
      <div className="p-2.5 rounded-lg bg-slate-900 border border-slate-800">{icon}</div>
      <div className="min-w-0">
        <div className="text-[10px] text-slate-500 font-mono tracking-widest uppercase">{label}</div>
        <div className="text-2xl font-black font-display text-slate-100">{value}</div>
        <div className="text-[10px] text-slate-500 font-mono truncate">{sub}</div>
      </div>
    </div>
  );
}
