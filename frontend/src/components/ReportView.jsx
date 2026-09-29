import React, { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { Printer, Download, X, ShieldCheck, Loader2, BadgeCheck } from 'lucide-react';
import { getCaseReport, verifyReport, errorMessage, formatBTC, formatUSD, shortAddr } from '../services/api';

const LEVEL_COLOR = { CRITICAL: '#b91c1c', HIGH: '#c2410c', MEDIUM: '#a16207', LOW: '#0e7490' };

export default function ReportView({ address, graphImage, onClose }) {
  const [report, setReport] = useState(null);
  const [error, setError] = useState(null);
  const [analyst, setAnalyst] = useState('SIFRA Analyst');
  const [caseRef, setCaseRef] = useState('');
  const [verified, setVerified] = useState(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let alive = true;
    getCaseReport(address, { analyst, caseRef })
      .then((r) => { if (alive) { setReport(r); setError(null); setVerified(null); } })
      .catch((e) => alive && setError(errorMessage(e)));
    return () => { alive = false; };
    // analyst / caseRef are applied explicitly via "Apply" (reloadKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [address, reloadKey]);

  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const downloadJson = () => {
    const blob = new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `${report.case.case_id}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  const verify = async () => {
    try {
      const res = await verifyReport(report.integrity.payload, report.integrity.digest);
      setVerified(res.matches);
    } catch {
      setVerified(false);
    }
  };

  const inv = report?.investigation;

  // Portal to <body> so the report escapes the dashboard's stacking context (and prints cleanly)
  return createPortal((
    <div className="report-overlay fixed inset-0 z-[10000] bg-slate-950/95 overflow-y-auto" role="dialog" aria-modal="true" aria-label="Case report">
      <div className="no-print sticky top-0 z-10 bg-slate-900/95 border-b border-slate-700 px-4 py-2.5 flex flex-wrap items-center gap-2 justify-between">
        <div className="flex flex-wrap items-center gap-2 text-xs font-mono">
          <span className="text-cyan-300 font-bold tracking-widest">CASE REPORT</span>
          <input value={analyst} onChange={(e) => setAnalyst(e.target.value)} aria-label="Analyst name"
            className="bg-slate-950 border border-slate-700 rounded px-2 py-1 text-slate-200 w-40" placeholder="Analyst" />
          <input value={caseRef} onChange={(e) => setCaseRef(e.target.value)} aria-label="Case reference"
            className="bg-slate-950 border border-slate-700 rounded px-2 py-1 text-slate-200 w-44" placeholder="FIR / case ref (optional)" />
          <button type="button" onClick={() => setReloadKey((k) => k + 1)}
            className="px-2.5 py-1 border border-slate-600 rounded text-slate-300 hover:border-cyan-400 cursor-pointer">Apply</button>
        </div>
        <div className="flex items-center gap-2">
          <button type="button" disabled={!report} onClick={verify}
            className="px-3 py-1.5 text-xs font-mono rounded border border-emerald-500/50 text-emerald-300 hover:bg-emerald-500/10 flex items-center gap-1.5 cursor-pointer disabled:opacity-40">
            <BadgeCheck className="w-4 h-4" /> Verify integrity
          </button>
          <button type="button" disabled={!report} onClick={downloadJson}
            className="px-3 py-1.5 text-xs font-mono rounded border border-slate-600 text-slate-200 hover:border-cyan-400 flex items-center gap-1.5 cursor-pointer disabled:opacity-40">
            <Download className="w-4 h-4" /> Evidence JSON
          </button>
          <button type="button" disabled={!report} onClick={() => window.print()}
            className="px-3 py-1.5 text-xs font-mono rounded bg-cyan-500/20 border border-cyan-400 text-cyan-100 hover:bg-cyan-500/30 flex items-center gap-1.5 cursor-pointer disabled:opacity-40">
            <Printer className="w-4 h-4" /> Print / Save PDF
          </button>
          <button type="button" onClick={onClose} aria-label="Close report" className="p-1.5 text-slate-400 hover:text-white cursor-pointer"><X className="w-5 h-5" /></button>
        </div>
      </div>

      {verified !== null && (
        <div className={`no-print mx-auto max-w-[900px] mt-3 px-4 py-2 rounded text-sm font-mono ${verified ? 'bg-emerald-500/15 text-emerald-300 border border-emerald-500/40' : 'bg-red-500/15 text-red-300 border border-red-500/40'}`}>
          {verified ? '✔ Evidence fingerprint verified by the SIFRA API - payload is unaltered.' : '✘ Fingerprint mismatch - the evidence payload has been altered.'}
        </div>
      )}

      {error && <div className="no-print max-w-[900px] mx-auto mt-6 p-4 bg-red-950/60 border border-red-500/50 text-red-200 rounded">{error}</div>}
      {!report && !error && (
        <div className="flex items-center justify-center py-32 text-slate-300 gap-3"><Loader2 className="w-6 h-6 animate-spin" /> Compiling case file…</div>
      )}

      {report && inv && (
        <div className="report-print-root py-6 px-4">
          <article className="report-sheet max-w-[900px] mx-auto p-10 shadow-2xl rounded-sm space-y-6">
            <header className="flex items-start justify-between border-b-2 border-slate-900 pb-4">
              <div>
                <div className="text-[11px] tracking-[0.3em] text-slate-500 font-semibold">SIFRA · BITCOIN FORENSICS</div>
                <h1 className="text-2xl font-bold mt-1">Wallet Investigation Report</h1>
                <div className="mono mt-1 text-slate-600">{report.case.subject}</div>
              </div>
              <table className="w-auto text-[11px]" style={{ width: 'auto' }}>
                <tbody>
                  <tr><th>Case ID</th><td className="mono">{report.case.case_id}</td></tr>
                  <tr><th>Generated</th><td>{new Date(report.case.generated_at).toLocaleString()}</td></tr>
                  <tr><th>Analyst</th><td>{report.case.analyst}</td></tr>
                  <tr><th>Engine</th><td>{report.case.engine_version}</td></tr>
                </tbody>
              </table>
            </header>

            <section className="grid grid-cols-3 gap-4">
              <div className="col-span-1 rounded border-2 p-4 text-center" style={{ borderColor: LEVEL_COLOR[inv.risk_level] }}>
                <div className="text-[11px] tracking-widest text-slate-500">RISK VERDICT</div>
                <div className="text-4xl font-bold" style={{ color: LEVEL_COLOR[inv.risk_level] }}>{Math.round(inv.risk_score)}</div>
                <div className="font-bold tracking-widest" style={{ color: LEVEL_COLOR[inv.risk_level] }}>{inv.risk_level}</div>
                <div className="text-[11px] text-slate-500 mt-1">Confidence {inv.confidence?.level}</div>
              </div>
              <div className="col-span-2">
                <h2 className="text-sm font-bold uppercase tracking-wider mb-1">Executive summary</h2>
                <p>{inv.ai_explanation}</p>
                {inv.entity?.is_known && (
                  <p className="mt-2 text-[12px]"><b>Attribution:</b> {inv.entity.entity_name} ({inv.entity.category_label}, {inv.entity.confidence} confidence, source {inv.entity.source}).</p>
                )}
              </div>
            </section>

            <section>
              <h2 className="text-sm font-bold uppercase tracking-wider mb-2">Score composition</h2>
              <table>
                <thead><tr><th>Component</th><th>Score</th><th>Weight</th><th>Contribution</th><th>Basis</th></tr></thead>
                <tbody>
                  {inv.score_breakdown.map((b) => (
                    <tr key={b.component}>
                      <td>{b.label}</td><td>{b.available ? Math.round(b.score) : 'n/a'}</td><td>{b.weight}</td>
                      <td>{Math.round(b.contribution)}</td><td className="text-[11px]">{b.summary}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {inv.adjustments?.map((a) => <p key={a.type} className="text-[11px] text-slate-600 mt-1">Adjustment: {a.detail}</p>)}
            </section>

            <section>
              <h2 className="text-sm font-bold uppercase tracking-wider mb-2">Findings</h2>
              {inv.findings.filter((f) => f.severity !== 'INFO').length === 0 ? <p>No laundering typology triggered.</p> : (
                <table>
                  <thead><tr><th>Typology</th><th>Severity</th><th>Evidence</th></tr></thead>
                  <tbody>
                    {inv.findings.filter((f) => f.severity !== 'INFO').map((f) => (
                      <tr key={f.id}>
                        <td><b>{f.title}</b><div className="text-[11px] text-slate-500">{f.typology}</div></td>
                        <td>{f.severity} (+{Math.round(f.points)})</td>
                        <td className="text-[12px]">{f.summary}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </section>

            <section className="grid grid-cols-2 gap-6">
              <div>
                <h2 className="text-sm font-bold uppercase tracking-wider mb-2">Illicit exposure</h2>
                {inv.exposure.direct.length === 0 && inv.exposure.indirect.length === 0 ? <p>None detected.</p> : (
                  <ul className="list-disc pl-5 text-[12px] space-y-0.5">
                    {inv.exposure.direct.map((d) => <li key={d.address}>{d.entity_name} - {d.category_label}, hop 1, {(d.share * 100).toFixed(1)}% of value</li>)}
                    {inv.exposure.indirect.slice(0, 5).map((d, i) => <li key={i}>{d.entity_name} - {d.category_label}, hop 2 via <span className="mono">{shortAddr(d.via)}</span></li>)}
                  </ul>
                )}
              </div>
              <div>
                <h2 className="text-sm font-bold uppercase tracking-wider mb-2">Regulated touch-points</h2>
                {inv.exposure.cashout_exchanges.length + inv.exposure.funding_exchanges.length === 0 ? <p>None identified.</p> : (
                  <ul className="list-disc pl-5 text-[12px] space-y-0.5">
                    {inv.exposure.cashout_exchanges.map((c) => <li key={`o${c.address}`}>Sent {formatBTC(c.btc)} to {c.exchange}</li>)}
                    {inv.exposure.funding_exchanges.map((c) => <li key={`i${c.address}`}>Received {formatBTC(c.btc)} from {c.exchange}</li>)}
                  </ul>
                )}
                <p className="text-[12px] mt-2"><b>Cluster:</b> {inv.cluster.size > 1 ? `${inv.cluster.cluster_id}, ${inv.cluster.size} addresses (${inv.cluster.method})` : 'no co-spend links'}</p>
                <p className="text-[12px]"><b>Broadcast telemetry:</b> {inv.geo_analysis.summary}</p>
              </div>
            </section>

            <section>
              <h2 className="text-sm font-bold uppercase tracking-wider mb-2">Recommended actions</h2>
              <ol className="list-decimal pl-5 text-[12px] space-y-1">
                {inv.recommendations.map((r, i) => <li key={i}><b>[{r.priority}] {r.action}:</b> {r.detail}</li>)}
              </ol>
            </section>

            {graphImage && (
              <section>
                <h2 className="text-sm font-bold uppercase tracking-wider mb-2">Transaction graph (snapshot)</h2>
                <img src={graphImage} alt="Investigation graph snapshot" className="w-full rounded border border-slate-300" />
              </section>
            )}

            <section>
              <h2 className="text-sm font-bold uppercase tracking-wider mb-2">Transaction evidence (most recent 25)</h2>
              <table>
                <thead><tr><th>Time (UTC)</th><th>Dir</th><th>Value</th><th>Txid</th></tr></thead>
                <tbody>
                  {inv.transactions.slice(0, 25).map((t) => (
                    <tr key={t.txid}>
                      <td className="whitespace-nowrap">{t.timestamp ? t.timestamp.slice(0, 16).replace('T', ' ') : 'unconfirmed'}</td>
                      <td>{t.direction}</td>
                      <td className="whitespace-nowrap">{formatBTC(t.value_btc)} <span className="text-slate-500">({formatUSD(t.value_usd)})</span></td>
                      <td className="mono">{t.txid}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>

            <section>
              <h2 className="text-sm font-bold uppercase tracking-wider mb-2">Methodology &amp; limitations</h2>
              <ul className="list-disc pl-5 text-[11px] space-y-0.5 text-slate-700">
                {report.methodology.data_sources.map((s) => <li key={s}>{s}</li>)}
                <li>{report.methodology.risk_fusion}</li>
                <li>{report.methodology.clustering}</li>
                <li>{report.methodology.ml}</li>
                {report.methodology.limitations.map((s) => <li key={s}><i>{s}</i></li>)}
              </ul>
            </section>

            <section className="border-t-2 border-slate-900 pt-3">
              <h2 className="text-sm font-bold uppercase tracking-wider mb-1 flex items-center gap-1.5"><ShieldCheck className="w-4 h-4" /> Evidence integrity</h2>
              <p className="text-[11px]">SHA-256 over the canonical evidence payload ({report.integrity.covers}):</p>
              <p className="mono text-[12px] font-bold mt-1">{report.integrity.digest}</p>
              <p className="text-[10px] text-slate-500 mt-1">{report.integrity.verify}</p>
              <div className="grid grid-cols-2 gap-10 mt-10 text-[11px] text-slate-600">
                <div className="border-t border-slate-400 pt-1">Investigating officer (signature / date)</div>
                <div className="border-t border-slate-400 pt-1">Supervising officer (signature / date)</div>
              </div>
            </section>
          </article>
        </div>
      )}
    </div>
  ), document.body);
}
