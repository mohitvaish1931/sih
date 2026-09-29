import React, { Suspense, lazy, useCallback, useEffect, useRef, useState } from 'react';
import {
  Radio, RadioOff, FileText, RefreshCw, Copy, Check, ArrowLeft, Share2, Globe, Table2, Workflow, ExternalLink,
} from 'lucide-react';
import {
  analyzeWallet, getWalletGraph, getTelemetryStats, errorMessage, addressLink, SEVERITY_STYLES,
} from '../services/api';
import { mergeGraph, tracePath } from '../services/graphUtils';
import WalletSearch from '../components/WalletSearch';
import RiskCard from '../components/RiskCard';
import FindingsPanel from '../components/FindingsPanel';
import CaseNarrative from '../components/CaseNarrative';
import ExposurePanel from '../components/ExposurePanel';
import TransactionTable from '../components/TransactionTable';
import FundFlow from '../components/FundFlow';
import AlertPanel from '../components/AlertPanel';
import GeoVelocityCard from '../components/GeoVelocityCard';
import LiveBlockchainStats from '../components/LiveBlockchainStats';
import WalletMonitorAlert from '../components/WalletMonitorAlert';
import LiveFeed from '../components/LiveFeed';

const TransactionGraph = lazy(() => import('../components/TransactionGraph'));
const WorldGeoMap = lazy(() => import('../components/WorldGeoMap'));
const ReportView = lazy(() => import('../components/ReportView'));
const TransactionChart = lazy(() => import('../components/TransactionChart'));

const PIPELINE = [
  'Sync on-chain history (Esplora / mempool.space)',
  'Typology detectors (peel chain, pass-through, fan-in/out, CoinJoin …)',
  'Entity attribution & illicit exposure',
  'Common-input-ownership clustering',
  'Isolation-Forest anomaly scoring',
  'Risk fusion, narrative & alerts',
];

const readHashAddress = () => {
  const m = window.location.hash.match(/^#\/wallet\/([^/?#]+)/);
  return m ? decodeURIComponent(m[1]) : null;
};

function Spinner() {
  return (
    <div className="flex items-center justify-center h-full text-cyan-400 font-mono text-xs gap-2">
      <span className="w-4 h-4 border-2 border-cyan-400/30 border-t-cyan-400 rounded-full animate-spin" /> LOADING MODULE…
    </div>
  );
}

export default function Dashboard() {
  const [address, setAddress] = useState('');
  const [analysis, setAnalysis] = useState(null);
  const [graph, setGraph] = useState(null);
  const [loading, setLoading] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState(null);
  const [tab, setTab] = useState('graph');
  const [trace, setTrace] = useState({ path: [], mode: null });
  const path = trace.path;
  const [isMonitoring, setIsMonitoring] = useState(false);
  const [showReport, setShowReport] = useState(false);
  const [graphImage, setGraphImage] = useState(null);
  const [alertsKey, setAlertsKey] = useState(0);
  const [copied, setCopied] = useState(false);
  const [telemetry, setTelemetry] = useState(null);
  const cyRef = useRef(null);
  const requestId = useRef(0);

  const runSearch = useCallback(async (target, { refresh = false } = {}) => {
    if (!target) return;
    const id = ++requestId.current;
    setAddress(target);
    setLoading(true);
    setError(null);
    if (!refresh) { setAnalysis(null); setGraph(null); setTrace({ path: [], mode: null }); setIsMonitoring(false); }
    if (readHashAddress() !== target) window.history.pushState(null, '', `#/wallet/${encodeURIComponent(target)}`);
    try {
      const result = await analyzeWallet(target, { refresh });
      if (id !== requestId.current) return;
      setAnalysis(result);
      setTab(result?.geo_analysis?.has_impossible_travel ? 'map' : 'graph');
      const g = await getWalletGraph(target);
      if (id !== requestId.current) return;
      setGraph(g);
      setAlertsKey((k) => k + 1);
    } catch (err) {
      if (id === requestId.current) setError(errorMessage(err));
    } finally {
      if (id === requestId.current) setLoading(false);
    }
  }, []);

  // Deep links: #/wallet/<address>
  useEffect(() => {
    const initial = readHashAddress();
    // Deferred so React StrictMode's mount/unmount/mount doesn't fire the investigation twice
    const boot = initial ? setTimeout(() => runSearch(initial), 0) : null;
    const onPop = () => {
      const a = readHashAddress();
      if (a) runSearch(a);
      else { requestId.current++; setAnalysis(null); setGraph(null); setAddress(''); setLoading(false); }
    };
    window.addEventListener('popstate', onPop);
    return () => { clearTimeout(boot); window.removeEventListener('popstate', onPop); };
  }, [runSearch]);

  useEffect(() => {
    if (!loading) return undefined;
    const start = Date.now();
    const id = setInterval(() => setElapsed(Math.floor((Date.now() - start) / 1000)), 250);
    return () => { clearInterval(id); setElapsed(0); };
  }, [loading]);

  useEffect(() => {
    if (tab === 'map' && !telemetry) getTelemetryStats().then(setTelemetry);
  }, [tab, telemetry]);

  const goHome = () => {
    requestId.current++;
    window.history.pushState(null, '', window.location.pathname);
    setAnalysis(null); setGraph(null); setAddress(''); setError(null); setLoading(false); setIsMonitoring(false);
  };

  const onNodeSelect = (nodeId) => setTrace(tracePath(graph, address, nodeId));
  const onExpand = useCallback((extra) => setGraph((g) => mergeGraph(g, extra)), []);

  const openReport = () => {
    try {
      setGraphImage(cyRef.current ? cyRef.current.png({ full: true, scale: 1.5, bg: '#020617' }) : null);
    } catch {
      setGraphImage(null);
    }
    setShowReport(true);
  };

  const copyAddress = async () => {
    try { await navigator.clipboard.writeText(address); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch { /* clipboard blocked */ }
  };
  const copyLink = async () => {
    try { await navigator.clipboard.writeText(window.location.href); } catch { /* clipboard blocked */ }
  };

  const sev = SEVERITY_STYLES[analysis?.risk_level] || SEVERITY_STYLES.LOW;
  const tabs = [
    { id: 'graph', label: `Network (${graph?.nodes?.length || 0})`, icon: Workflow },
    { id: 'map', label: 'Threat Map', icon: Globe, alert: analysis?.geo_analysis?.has_impossible_travel },
    { id: 'txs', label: `Transactions (${analysis?.transactions?.length || 0})`, icon: Table2 },
  ];

  return (
    <>
      <div className="container mx-auto space-y-5 max-w-[1500px] relative z-10 px-2 md:px-4 pb-20">
        <div className="hud-panel p-5">
          <WalletSearch key={address} initial={address} onSearch={runSearch} loading={loading} compact={Boolean(analysis)} />
          {error && (
            <div role="alert" className="mt-4 p-3 bg-red-950/50 border border-red-500/50 text-red-200 rounded text-sm font-mono">{error}</div>
          )}
        </div>

        {!loading && !analysis && <LiveBlockchainStats onSelectAddress={runSearch} />}

        {loading && (
          <div className="hud-panel p-8 flex flex-col md:flex-row items-center justify-center gap-10">
            <div className="relative">
              <div className="w-24 h-24 border-4 border-cyan-500/20 border-t-cyan-500 rounded-full animate-spin" />
              <div className="w-16 h-16 border-4 border-red-500/20 border-b-red-500 rounded-full animate-[spin_2s_linear_infinite_reverse] absolute top-4 left-4" />
              <div className="absolute inset-0 flex items-center justify-center font-mono text-cyan-300 text-sm">{elapsed}s</div>
            </div>
            <div className="space-y-2">
              <h3 className="text-xl font-black text-cyan-300 tracking-widest font-display uppercase">Investigating</h3>
              <p className="text-xs font-mono text-slate-400 break-all max-w-md">{address}</p>
              <ul className="space-y-1 pt-1">
                {PIPELINE.map((step) => (
                  <li key={step} className="text-[11px] font-mono text-slate-400 flex items-center gap-2">
                    <span className="w-1.5 h-1.5 rounded-full bg-cyan-500/70 animate-pulse" />{step}
                  </li>
                ))}
              </ul>
              <p className="text-[10px] text-slate-500 font-mono">First look-ups query live blockchain APIs (≈5-12 s); repeat views are cached.</p>
            </div>
          </div>
        )}

        {!loading && analysis && (
          <div className="space-y-5 animate-fade-up">
            {/* Case header */}
            <div className={`hud-panel px-5 py-3 flex flex-wrap items-center gap-3 justify-between border-l-4 ${sev.border}`}>
              <div className="flex items-center gap-3 min-w-0">
                <button type="button" onClick={goHome} aria-label="Back to overview" className="p-1.5 text-slate-400 hover:text-cyan-300 cursor-pointer"><ArrowLeft className="w-4 h-4" /></button>
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-sm md:text-base text-slate-100 truncate max-w-[52vw]" title={address}>{address}</span>
                    <button type="button" onClick={copyAddress} aria-label="Copy address" className="text-slate-500 hover:text-cyan-300 cursor-pointer">
                      {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                    </button>
                    {addressLink(address) && (
                      <a href={addressLink(address)} target="_blank" rel="noreferrer" aria-label="Open in explorer" className="text-slate-500 hover:text-cyan-300"><ExternalLink className="w-3.5 h-3.5" /></a>
                    )}
                  </div>
                  <div className="text-[10px] font-mono text-slate-500 flex flex-wrap gap-x-3">
                    {analysis.is_demo && <span className="text-fuchsia-300">DEMO SCENARIO</span>}
                    {analysis.entity?.is_known && <span style={{ color: analysis.entity.color }}>{analysis.entity.icon} {analysis.entity.entity_name}</span>}
                    <span>sync: {analysis.sync?.status}{analysis.sync?.source ? ` · ${analysis.sync.source}` : ''}</span>
                    <span>{analysis.confidence?.note}</span>
                    {analysis.timings && <span>{(analysis.timings.total_ms / 1000).toFixed(1)}s</span>}
                  </div>
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <span className={`px-3 py-1 rounded font-display font-black text-sm tracking-widest border ${sev.border} ${sev.bg} ${sev.text}`}>
                  {Math.round(analysis.risk_score)} · {analysis.risk_level}
                </span>
                <HeaderButton onClick={() => runSearch(address, { refresh: true })} icon={RefreshCw} label="Re-sync" />
                <HeaderButton onClick={() => setIsMonitoring((m) => !m)} icon={isMonitoring ? Radio : RadioOff}
                  label={isMonitoring ? 'Monitoring' : 'Monitor'} active={isMonitoring} disabled={analysis.is_demo}
                  title={analysis.is_demo ? 'Live monitoring works on real mainnet addresses' : 'Alert on every new transaction'} />
                <HeaderButton onClick={copyLink} icon={Share2} label="Link" />
                <button type="button" onClick={openReport}
                  className="glow-btn px-4 py-1.5 bg-cyan-500/15 hover:bg-cyan-500/25 text-cyan-200 text-xs font-mono font-bold tracking-widest uppercase border border-cyan-400/70 flex items-center gap-2 cursor-pointer rounded-sm">
                  <FileText className="w-4 h-4" /> Case report
                </button>
              </div>
            </div>

            <div className="grid grid-cols-1 xl:grid-cols-12 gap-5">
              <div className="xl:col-span-3 space-y-5">
                <RiskCard analysis={analysis} />
                <ExposurePanel exposure={analysis.exposure} cluster={analysis.cluster} />
                <GeoVelocityCard geoAnalysis={analysis.geo_analysis} onViewMap={() => setTab('map')} />
              </div>

              <div className="xl:col-span-6 space-y-5">
                <div className="hud-panel p-3 flex flex-col h-[680px]">
                  <div className="flex flex-wrap items-center justify-between gap-2 mb-3" role="tablist">
                    <div className="flex items-center gap-1 bg-slate-900/90 p-1 rounded-lg border border-slate-800">
                      {tabs.map((t) => (
                        <button key={t.id} type="button" role="tab" aria-selected={tab === t.id} onClick={() => setTab(t.id)}
                          className={`px-3 py-1.5 rounded-md text-xs font-mono transition-all flex items-center gap-1.5 cursor-pointer ${
                            tab === t.id ? 'bg-cyan-500/20 text-cyan-200 border border-cyan-500/40' : 'text-slate-400 hover:text-slate-200 border border-transparent'}`}>
                          <t.icon className="w-3.5 h-3.5" />{t.label}
                          {t.alert && <span className="w-2 h-2 rounded-full bg-red-500 animate-ping" />}
                        </button>
                      ))}
                    </div>
                    {tab === 'graph' && graph && (
                      <span className="text-[10px] text-slate-400 font-mono">{graph.nodes.length} nodes · {graph.edges.length} flows</span>
                    )}
                  </div>
                  <div className="flex-1 rounded-lg overflow-hidden border border-slate-800 bg-[#050b17] relative min-h-0">
                    <Suspense fallback={<Spinner />}>
                      {tab === 'graph' && (graph && graph.nodes.length > 0 ? (
                        <TransactionGraph data={graph} rootAddress={address} onNodeSelect={onNodeSelect} onExpand={onExpand}
                          highlightPath={path} onReady={(cy) => { cyRef.current = cy; }} />
                      ) : (
                        <div className="flex items-center justify-center h-full text-slate-500 font-mono text-sm">
                          {graph ? 'No transaction network found' : 'Building graph…'}
                        </div>
                      ))}
                      {tab === 'map' && <WorldGeoMap geoAnalysis={analysis.geo_analysis} telemetryStats={telemetry} />}
                      {tab === 'txs' && <div className="h-full p-2"><TransactionTable transactions={analysis.transactions} /></div>}
                    </Suspense>
                  </div>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
                  <div className="hud-panel p-4 h-[300px]"><Suspense fallback={<Spinner />}><TransactionChart data={analysis.time_series} /></Suspense></div>
                  <div className="hud-panel p-4 h-[300px]"><FundFlow graph={graph} path={path} mode={trace.mode} onClear={() => setTrace({ path: [], mode: null })} /></div>
                </div>
              </div>

              <div className="xl:col-span-3 space-y-5">
                <CaseNarrative explanation={analysis.ai_explanation} source={analysis.explanation_source}
                  recommendations={analysis.recommendations} />
                <FindingsPanel findings={analysis.findings} exposure={analysis.exposure} />
                <AlertPanel wallet={address} refreshKey={alertsKey} limit={6} />
              </div>
            </div>
          </div>
        )}
      </div>

      <WalletMonitorAlert address={address} isMonitoring={isMonitoring}
        onNewTransaction={() => setAlertsKey((k) => k + 1)} />

      {showReport && analysis && (
        <Suspense fallback={null}>
          <ReportView address={address} graphImage={graphImage} onClose={() => setShowReport(false)} />
        </Suspense>
      )}

      <LiveFeed onSelectAddress={runSearch} />
    </>
  );
}

function HeaderButton({ onClick, icon: Icon, label, active, disabled, title }) {
  return (
    <button type="button" onClick={onClick} disabled={disabled} title={title || label}
      className={`px-3 py-1.5 rounded-sm text-xs font-mono flex items-center gap-1.5 border transition-all cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed ${
        active ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/50' : 'bg-slate-900/80 text-slate-300 border-slate-700 hover:border-cyan-500/50 hover:text-cyan-200'}`}>
      <Icon className={`w-3.5 h-3.5 ${active ? 'animate-pulse' : ''}`} />{label}
    </button>
  );
}
