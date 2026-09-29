import React, { useMemo, useState } from 'react';
import { geoNaturalEarth1, geoPath, geoGraticule10, geoInterpolate } from 'd3-geo';
import { feature } from 'topojson-client';
import world from 'world-atlas/countries-110m.json';
import { Globe, ShieldAlert, MapPin, Satellite } from 'lucide-react';

const WIDTH = 900;
const HEIGHT = 460;
const countries = feature(world, world.objects.countries);

export default function WorldGeoMap({ geoAnalysis, telemetryStats }) {
  const [activeHop, setActiveHop] = useState(null);
  const [selected, setSelected] = useState(null);

  const { path, project } = useMemo(() => {
    const projection = geoNaturalEarth1().fitExtent([[10, 10], [WIDTH - 10, HEIGHT - 10]], { type: 'Sphere' });
    return { path: geoPath(projection), project: (lat, lon) => projection([lon, lat]) };
  }, []);

  const locations = geoAnalysis?.locations || [];
  const hops = geoAnalysis?.hops || [];
  const available = geoAnalysis?.data_available;
  const hasImpossible = geoAnalysis?.has_impossible_travel;
  const coverage = geoAnalysis?.coverage || {};

  const arc = (from, to) => {
    const interp = geoInterpolate([from[1], from[0]], [to[1], to[0]]);
    return path({ type: 'LineString', coordinates: Array.from({ length: 48 }, (_, i) => interp(i / 47)) });
  };

  return (
    <div className="w-full h-full flex flex-col relative bg-[#050b17] rounded-lg overflow-hidden">
      <div className="px-4 py-2.5 bg-slate-900/90 border-b border-slate-800 flex flex-wrap gap-2 items-center justify-between text-xs font-mono">
        <div className="flex items-center gap-2">
          <Globe className="w-4 h-4 text-cyan-400" />
          <span className="text-slate-200 font-semibold tracking-wider uppercase">Broadcast Geo-Velocity</span>
          <span className="text-slate-500 hidden md:inline">| relay telemetry · first-spy estimator</span>
        </div>
        <div className="flex items-center gap-2">
          {!available ? (
            <span className="px-2.5 py-0.5 rounded-full bg-slate-800 text-slate-400 border border-slate-700 text-[11px]">NO TELEMETRY</span>
          ) : hasImpossible ? (
            <span className="flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-red-500/20 text-red-300 border border-red-500/40 text-[11px] font-semibold animate-pulse">
              <ShieldAlert className="w-3.5 h-3.5" /> IMPOSSIBLE TRAVEL
            </span>
          ) : (
            <span className="px-2.5 py-0.5 rounded-full bg-emerald-500/10 text-emerald-300 border border-emerald-500/30 text-[11px]">GEO-CONSISTENT</span>
          )}
          <span className="text-slate-400 bg-slate-800 px-2 py-0.5 rounded border border-slate-700">
            {coverage.observed || 0}/{coverage.total || 0} txs observed
          </span>
        </div>
      </div>

      <div className="flex-1 relative overflow-hidden flex items-center justify-center">
        <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className={`w-full h-full select-none ${available ? '' : 'opacity-40'}`} role="img"
          aria-label="World map of observed broadcast relays">
          <defs>
            <filter id="glow" x="-50%" y="-50%" width="200%" height="200%">
              <feGaussianBlur stdDeviation="2.5" result="b" /><feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
            </filter>
          </defs>
          <path d={path({ type: 'Sphere' })} fill="#030a18" stroke="#12304f" />
          <path d={path(geoGraticule10())} fill="none" stroke="#0e2340" strokeWidth="0.5" />
          <g fill="#0d213d" stroke="#1d3b66" strokeWidth="0.5">
            {countries.features.map((f, i) => <path key={i} d={path(f)} />)}
          </g>

          {hops.map((hop, i) => {
            const d = arc(hop.from_coords, hop.to_coords);
            const hot = activeHop === i;
            const color = hop.is_impossible ? '#ff003c' : hop.flag_reason ? '#f59e0b' : '#22d3ee';
            return (
              <g key={`hop-${i}`} onMouseEnter={() => setActiveHop(i)} onMouseLeave={() => setActiveHop(null)} className="cursor-pointer">
                <path d={d} fill="none" stroke={color} strokeOpacity={0.25} strokeWidth={hot ? 7 : 5} />
                <path d={d} fill="none" stroke={color} strokeWidth={hot ? 2.5 : 1.6} strokeDasharray="6 4"
                  className="arc-flow" filter="url(#glow)" />
              </g>
            );
          })}

          {locations.map((loc) => {
            const p = project(loc.lat, loc.lon);
            if (!p) return null;
            const color = loc.is_vpn_tor ? '#ff003c' : '#22d3ee';
            return (
              <g key={loc.ip} transform={`translate(${p[0]}, ${p[1]})`} onClick={() => setSelected(loc)}
                onMouseEnter={() => setSelected(loc)} className="cursor-pointer">
                <circle r={loc.is_vpn_tor ? 13 : 10} fill="none" stroke={color} strokeOpacity="0.5" className="animate-ping"
                  style={{ transformOrigin: 'center', transformBox: 'fill-box' }} />
                <circle r={selected?.ip === loc.ip ? 6 : 4.5} fill={color} stroke="#fff" strokeWidth="1" filter="url(#glow)" />
                <text y="-10" textAnchor="middle" fill={loc.is_vpn_tor ? '#fca5a5' : '#cbd5e1'} fontSize="10"
                  fontFamily="Share Tech Mono, monospace" className="pointer-events-none">{loc.city}</text>
              </g>
            );
          })}
        </svg>

        {!available && (
          <div className="absolute inset-0 flex items-center justify-center p-6">
            <div className="max-w-md bg-slate-950/90 border border-slate-700 rounded-lg p-5 text-center space-y-2">
              <Satellite className="w-8 h-8 text-cyan-400 mx-auto" />
              <div className="text-sm font-bold text-slate-100 font-mono tracking-wide">NO BROADCAST TELEMETRY FOR THIS WALLET</div>
              <p className="text-xs text-slate-400 font-body leading-relaxed">
                Bitcoin transactions carry no IP address, so SIFRA never guesses a location. Origins come only from the
                SIFRA relay sensor, which records the first peer that announced each new transaction.
              </p>
              <code className="block text-[11px] text-cyan-300 bg-slate-900 border border-slate-800 rounded px-2 py-1.5">
                python sensor/relay_sensor.py --peers 16
              </code>
              {telemetryStats && (
                <div className="text-[11px] text-slate-500 font-mono">
                  Sensor network: {telemetryStats.observations?.toLocaleString()} relay observations stored
                </div>
              )}
            </div>
          </div>
        )}

        {selected && available && (
          <div className="absolute top-3 right-3 bg-slate-900/95 border border-slate-700 p-3 rounded-lg text-xs max-w-[250px] font-mono z-20">
            <div className="flex items-center justify-between border-b border-slate-800 pb-1.5 mb-2 gap-2">
              <span className="text-slate-100 font-bold flex items-center gap-1.5"><MapPin className="w-3.5 h-3.5 text-cyan-400" />{selected.city}, {selected.country}</span>
              {selected.is_vpn_tor && <span className="px-1.5 py-0.5 bg-red-500/20 text-red-300 border border-red-500/40 rounded text-[10px]">TOR/VPN</span>}
            </div>
            <div className="space-y-1 text-[11px]">
              <Row k="Relay IP" v={selected.ip} />
              <Row k="ISP" v={selected.isp} />
              <Row k="Coords" v={`${selected.lat?.toFixed(2)}°, ${selected.lon?.toFixed(2)}°`} />
              <Row k="Txs" v={selected.tx_count} />
              <Row k="Confidence" v={selected.confidence != null ? `${Math.round(selected.confidence * 100)}%` : '—'} />
              <Row k="Source" v={selected.source} />
            </div>
          </div>
        )}

        {activeHop != null && hops[activeHop] && (
          <div className="absolute bottom-3 right-3 bg-slate-900/95 border border-slate-700 p-2.5 rounded text-[11px] font-mono max-w-xs z-20">
            <div className="text-slate-100">{hops[activeHop].from_city} → {hops[activeHop].to_city}</div>
            <div className="text-slate-400">{Math.round(hops[activeHop].distance_km).toLocaleString()} km in {hops[activeHop].time_diff_minutes} min · {Math.round(hops[activeHop].velocity_kmh).toLocaleString()} km/h</div>
            {hops[activeHop].flag_reason && <div className="text-amber-300 mt-0.5">{hops[activeHop].flag_reason}</div>}
          </div>
        )}
      </div>

      <div className="px-4 py-2 bg-slate-900/80 border-t border-slate-800 flex flex-wrap gap-3 items-center justify-between text-[10px] font-mono text-slate-400">
        <div className="flex items-center gap-4">
          <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-cyan-400" />Relay</span>
          <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-red-500" />Tor / VPN</span>
          <span className="flex items-center gap-1.5"><span className="w-4 border-t border-dashed border-red-500" />Impossible (&gt;900 km/h)</span>
        </div>
        <span className="text-slate-500">{geoAnalysis?.summary}</span>
      </div>
    </div>
  );
}

function Row({ k, v }) {
  return (
    <div className="flex justify-between gap-3">
      <span className="text-slate-500">{k}</span><span className="text-slate-300 truncate">{v ?? '—'}</span>
    </div>
  );
}
