import React, { useEffect, useState } from 'react';
import { Shield } from 'lucide-react';
import Dashboard from './pages/Dashboard';
import { getHealth, getTelemetryStats } from './services/api';

function StatusChip({ ok, label, title }) {
  const color = ok === null ? 'bg-slate-500' : ok ? 'bg-emerald-400' : 'bg-red-500';
  return (
    <span title={title} className="flex items-center gap-1.5 text-[10px] font-mono text-slate-300 bg-slate-900/70 px-2.5 py-1 rounded-sm border border-slate-700/80 tracking-widest">
      <span className={`w-1.5 h-1.5 rounded-full ${color} ${ok ? 'animate-pulse' : ''}`} />{label}
    </span>
  );
}

export default function App() {
  const [health, setHealth] = useState(null);
  const [sensor, setSensor] = useState(null);
  const [sensorFresh, setSensorFresh] = useState(false);
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      const [h, t] = await Promise.all([getHealth(), getTelemetryStats()]);
      if (!alive) return;
      setHealth(h);
      setSensor(t);
      setSensorFresh(Boolean(t?.last_observation) && Date.now() - new Date(t.last_observation).getTime() < 10 * 60 * 1000);
      setChecked(true);
    };
    load();
    const id = setInterval(load, 60000);
    return () => { alive = false; clearInterval(id); };
  }, []);

  const apiDown = checked && !health;

  return (
    <div className="min-h-screen bg-grid-cyber flex flex-col relative overflow-x-hidden">
      <div className="scanline-overlay no-print" />

      <header className="bg-slate-950/80 backdrop-blur-md border-b border-cyan-500/20 px-4 py-3 sticky top-0 z-50 shadow-[0_0_20px_rgba(0,240,255,0.08)] no-print">
        <div className="container mx-auto max-w-[1500px] flex flex-wrap gap-3 items-center justify-between">
          <a href="#" className="flex items-center gap-3.5 group" onClick={(e) => { e.preventDefault(); window.location.hash = ''; window.dispatchEvent(new PopStateEvent('popstate')); }}>
            <div className="p-2.5 bg-cyan-500/10 rounded-xl border border-cyan-500/40 relative shadow-[0_0_15px_rgba(0,240,255,0.2)] group-hover:border-cyan-400 transition-all">
              <Shield className="w-6 h-6 text-cyan-400" />
              <span className={`absolute top-0 right-0 w-2.5 h-2.5 rounded-full ${apiDown ? 'bg-red-500 animate-ping' : 'bg-emerald-400'}`} />
            </div>
            <div>
              <h1 className="text-2xl md:text-3xl font-black tracking-[0.2em] glitch-text font-display leading-none">SIFRA</h1>
              <p className="text-[10px] text-cyan-500/70 font-mono tracking-[0.2em] mt-1 uppercase">Bitcoin forensics &amp; threat intelligence</p>
            </div>
          </a>

          <div className="flex flex-wrap items-center gap-2">
            {apiDown ? (
              <StatusChip ok={false} label="API OFFLINE" title="Start the backend: uvicorn main:app --reload" />
            ) : (
              <>
                <StatusChip ok={health ? health.database?.ok : null} label={`DB ${health?.database?.backend?.toUpperCase() || ''}`} />
                <StatusChip ok={health ? health.blockchain?.ok : null}
                  label={health?.blockchain?.tip_height ? `CHAIN #${health.blockchain.tip_height.toLocaleString()}` : 'CHAIN'} />
                <StatusChip ok={health ? health.llm?.available : null} label={health?.llm?.available ? 'LLM ONLINE' : 'LLM: TEMPLATE'}
                  title={health?.llm?.available ? `Local model ${health.llm.model}` : 'Narratives use the deterministic evidence template (start Ollama to enable)'} />
                <StatusChip ok={sensor ? Boolean(sensorFresh) : null} label={sensorFresh ? 'RELAY SENSOR LIVE' : 'SENSOR IDLE'}
                  title={`${sensor?.observations?.toLocaleString() || 0} relay observations stored`} />
              </>
            )}
          </div>
        </div>
      </header>

      <main className="flex-1 py-5 relative z-10">
        <Dashboard />
      </main>
    </div>
  );
}
