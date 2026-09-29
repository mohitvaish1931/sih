import React from 'react';
import { Gauge, ShieldAlert, ArrowRight, Navigation, Globe, Satellite } from 'lucide-react';

export default function GeoVelocityCard({ geoAnalysis, onViewMap }) {
  const available = geoAnalysis?.data_available;
  const hasImpossible = geoAnalysis?.has_impossible_travel;
  const hops = geoAnalysis?.hops || [];
  const flagged = hops.filter((h) => h.is_impossible);
  const coverage = geoAnalysis?.coverage || {};

  return (
    <div className="hud-panel p-5 flex flex-col gap-3">
      <div className="flex items-center justify-between gap-2">
        <h3 className="section-title flex items-center gap-2">
          <Navigation className={`w-4 h-4 ${hasImpossible ? 'text-red-400' : ''}`} /> Geo-Velocity
        </h3>
        {!available ? (
          <span className="px-2 py-0.5 bg-slate-800 text-slate-400 border border-slate-700 rounded-full text-[10px] font-mono">NO TELEMETRY</span>
        ) : hasImpossible ? (
          <span className="px-2 py-0.5 bg-red-500/20 text-red-300 border border-red-500/40 rounded-full text-[10px] font-mono font-bold flex items-center gap-1 animate-pulse">
            <ShieldAlert className="w-3 h-3" /> IMPOSSIBLE TRAVEL
          </span>
        ) : (
          <span className="px-2 py-0.5 bg-emerald-500/10 text-emerald-300 border border-emerald-500/30 rounded-full text-[10px] font-mono">PLAUSIBLE</span>
        )}
      </div>

      {!available ? (
        <div className="flex gap-2 text-xs text-slate-400 font-body leading-relaxed">
          <Satellite className="w-4 h-4 text-cyan-500 shrink-0 mt-0.5" />
          <span>{geoAnalysis?.summary}</span>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-2">
            <div className="bg-slate-900/60 p-3 rounded-lg border border-slate-800">
              <div className="text-[10px] text-slate-400 mb-1 flex items-center gap-1 font-mono"><Gauge className="w-3 h-3 text-cyan-400" />MAX VELOCITY</div>
              <div className={`text-lg font-black font-mono ${hasImpossible ? 'text-red-400' : 'text-slate-100'}`}>
                {Math.round(geoAnalysis.max_velocity_kmh || 0).toLocaleString()} <span className="text-xs">km/h</span>
              </div>
            </div>
            <div className="bg-slate-900/60 p-3 rounded-lg border border-slate-800">
              <div className="text-[10px] text-slate-400 mb-1 font-mono">FLAGGED HOPS</div>
              <div className={`text-lg font-black font-mono ${flagged.length ? 'text-orange-400' : 'text-slate-100'}`}>
                {flagged.length}<span className="text-xs text-slate-400"> / {hops.length}</span>
              </div>
            </div>
          </div>
          <p className={`text-xs font-body leading-relaxed ${hasImpossible ? 'text-red-300' : 'text-slate-400'}`}>{geoAnalysis.summary}</p>
          <div className="space-y-1.5 max-h-40 overflow-y-auto custom-scrollbar pr-1">
            {hops.map((hop, i) => (
              <div key={i} className={`p-2 rounded border text-[11px] font-mono ${hop.is_impossible ? 'bg-red-950/20 border-red-500/40' : 'bg-slate-800/40 border-slate-700/40'}`}>
                <div className="flex items-center justify-between gap-2">
                  <span className="flex items-center gap-1.5 text-slate-200">{hop.from_city}<ArrowRight className="w-3 h-3 text-slate-500" />
                    <span className={hop.is_impossible ? 'text-red-300' : 'text-cyan-300'}>{hop.to_city}</span></span>
                  <span className="text-slate-400">{hop.time_diff_minutes} min</span>
                </div>
                {hop.flag_reason && <div className="text-[10px] text-amber-300/90 mt-0.5 font-body">{hop.flag_reason}</div>}
              </div>
            ))}
          </div>
          <div className="text-[10px] text-slate-500 font-mono">{coverage.observed}/{coverage.total} txs with relay observations
            {coverage.low_confidence ? ` · ${coverage.low_confidence} low-confidence ignored` : ''}</div>
        </>
      )}

      {onViewMap && (
        <button type="button" onClick={onViewMap}
          className="py-1.5 px-3 bg-cyan-500/10 hover:bg-cyan-500/20 text-cyan-300 border border-cyan-500/30 hover:border-cyan-500/60 rounded text-[11px] font-mono flex items-center justify-center gap-2 transition-all cursor-pointer">
          <Globe className="w-3.5 h-3.5" /> Open threat map
        </button>
      )}
    </div>
  );
}
