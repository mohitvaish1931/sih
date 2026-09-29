import React, { useEffect, useMemo, useRef, useState } from 'react';
import CytoscapeComponent from 'react-cytoscapejs';
import { expandGraphNode, errorMessage, formatBTC, shortAddr, addressLink } from '../services/api';
import { Maximize2, ZoomIn, ZoomOut, RefreshCw, Download, ExternalLink } from 'lucide-react';

const CATEGORY_COLORS = {
  exchange: '#22c55e', exchange_defunct: '#f59e0b', darknet: '#ef4444', ransomware: '#dc2626', hack: '#f97316',
  scam: '#fb7185', sanctioned: '#b91c1c', mixer: '#a855f7', coinjoin_cluster: '#c084fc', government: '#3b82f6',
  government_seizure: '#3b82f6', whale: '#06b6d4', institutional: '#10b981', mining: '#8b5cf6',
  historical: '#f59e0b', gambling: '#eab308', service: '#14b8a6', unknown: '#38bdf8',
};

const label = (ele) => {
  const name = ele.data('entity_name');
  if (name) return name.length > 18 ? `${name.slice(0, 18)}…` : name;
  const id = ele.data('id') || '';
  return id.length > 12 ? `${id.slice(0, 6)}…${id.slice(-4)}` : id;
};

// Stylesheet is static - defined once so Cytoscape isn't restyled on every render
const STYLESHEET = [
  {
    selector: 'node',
    style: {
      'background-color': (ele) => CATEGORY_COLORS[ele.data('entity_category')] || CATEGORY_COLORS.unknown,
      label,
      color: '#cbd5e1', 'text-valign': 'bottom', 'text-halign': 'center', 'text-margin-y': 6,
      'font-size': 8, 'font-family': '"Share Tech Mono", monospace',
      width: (ele) => 14 + Math.min(18, Math.log10((ele.data('volume_btc') || 0) + 1) * 6),
      height: (ele) => 14 + Math.min(18, Math.log10((ele.data('volume_btc') || 0) + 1) * 6),
      'border-width': 1.5, 'border-color': '#020617', 'text-outline-color': '#020617', 'text-outline-width': 2,
      'transition-property': 'opacity, border-width', 'transition-duration': '200ms',
    },
  },
  { selector: 'node[?is_known]', style: { 'border-width': 3, 'border-color': '#e2e8f0', 'font-size': 9, 'font-weight': 'bold', color: '#f1f5f9' } },
  { selector: 'node[?illicit]', style: { 'border-color': '#ff003c', 'border-width': 4, 'underlay-color': '#ff003c', 'underlay-opacity': 0.35, 'underlay-padding': 6, color: '#fecaca' } },
  { selector: 'node[?in_cluster]', style: { 'border-style': 'dashed', 'border-color': '#c084fc', 'border-width': 3 } },
  {
    selector: 'node[?is_root]',
    style: {
      'background-color': '#ff003c', width: 36, height: 36, 'border-width': 4, 'border-color': '#fff',
      'font-size': 11, 'font-weight': 'bold', color: '#ff6b8b', 'z-index': 100,
      'underlay-color': '#ff003c', 'underlay-opacity': 0.25, 'underlay-padding': 10,
    },
  },
  { selector: 'node.expanded', style: { 'border-color': '#22d3ee', 'border-width': 3 } },
  { selector: 'node:selected', style: { 'border-color': '#fff', 'border-width': 5, 'underlay-color': '#22d3ee', 'underlay-opacity': 0.4, 'underlay-padding': 8 } },
  {
    selector: 'edge',
    style: {
      width: (ele) => Math.max(1, Math.min(7, Math.log10((ele.data('amount') || 0) + 1) * 2.5 + 0.8)),
      'line-color': 'rgba(56, 189, 248, 0.35)', 'target-arrow-color': 'rgba(56, 189, 248, 0.6)',
      'target-arrow-shape': 'triangle', 'arrow-scale': 0.8, 'curve-style': 'bezier',
      label: (ele) => {
        const amt = ele.data('amount');
        return amt > 0 ? `${+amt.toFixed(amt < 0.01 ? 6 : 3)}₿${ele.data('tx_count') > 1 ? ` ×${ele.data('tx_count')}` : ''}` : '';
      },
      'font-size': 7, 'font-family': '"Share Tech Mono", monospace', color: '#7dd3fc',
      'text-rotation': 'autorotate', 'text-margin-y': -8, 'text-outline-color': '#020617', 'text-outline-width': 2,
      'text-opacity': 0.85,
    },
  },
  { selector: 'edge[kind = "peel"]', style: { 'line-color': 'rgba(249, 115, 22, 0.8)', 'target-arrow-color': '#f97316', 'line-style': 'solid', color: '#fdba74' } },
  { selector: 'edge[kind = "cluster"]', style: { 'line-color': 'rgba(192, 132, 252, 0.6)', 'line-style': 'dashed', 'target-arrow-shape': 'none', width: 1.2, label: '' } },
  { selector: 'edge[?illicit]', style: { 'line-color': 'rgba(255, 0, 60, 0.75)', 'target-arrow-color': '#ff003c', color: '#fca5a5' } },
  { selector: '.dimmed', style: { opacity: 0.12 } },
  { selector: 'node.on-path', style: { 'border-color': '#fde047', 'border-width': 5, opacity: 1 } },
  { selector: 'edge.on-path', style: { 'line-color': '#fde047', 'target-arrow-color': '#fde047', width: 5, opacity: 1, 'z-index': 99 } },
];

const LAYOUT = {
  name: 'cose', idealEdgeLength: 110, nodeOverlap: 20, fit: true, padding: 40, componentSpacing: 100,
  nodeRepulsion: 450000, edgeElasticity: 100, nestingFactor: 5, gravity: 60, numIter: 1200,
  initialTemp: 200, coolingFactor: 0.95, minTemp: 1.0,
};

const LEGEND = [
  { color: '#ff003c', label: 'TARGET' },
  { color: '#22c55e', label: 'EXCHANGE' },
  { color: '#ef4444', label: 'ILLICIT (glow)' },
  { color: '#a855f7', label: 'MIXER' },
  { color: '#f97316', label: 'PEEL HOP' },
  { color: '#c084fc', label: 'CLUSTER (dashed)' },
  { color: '#38bdf8', label: 'UNATTRIBUTED' },
];

export default function TransactionGraph({ data, rootAddress, onNodeSelect, onExpand, highlightPath = [], onReady }) {
  const cyRef = useRef(null);
  const containerRef = useRef(null);
  const handlers = useRef({});
  const [expanding, setExpanding] = useState(null);
  const [expandError, setExpandError] = useState(null);
  const [hovered, setHovered] = useState(null);
  const [expanded, setExpanded] = useState(() => new Set());
  const nodeCount = data.nodes.length;
  const prevCount = useRef(0);

  const elements = useMemo(() => [...data.nodes, ...data.edges], [data]);

  // Keep the latest callbacks reachable from the (once-registered) Cytoscape handlers
  useEffect(() => {
    handlers.current = {
    select: (id) => onNodeSelect && onNodeSelect(id),
    expand: async (id) => {
      if (expanded.has(id) || expanding) return;
      setExpanding(id);
      setExpandError(null);
      try {
        const result = await expandGraphNode(id, rootAddress);
        setExpanded((prev) => new Set(prev).add(id));
        if (result?.nodes?.length && onExpand) onExpand(result);
      } catch (err) {
        setExpandError(errorMessage(err));
      } finally {
        setExpanding(null);
      }
    },
    };
  });

  const bindCy = (cy) => {
    if (cyRef.current === cy) return;
    cyRef.current = cy;
    cy.on('tap', 'node', (evt) => handlers.current.select(evt.target.id()));
    cy.on('dbltap', 'node', (evt) => handlers.current.expand(evt.target.id()));
    cy.on('mouseover', 'node', (evt) => {
      const n = evt.target;
      setHovered({
        id: n.id(), name: n.data('entity_name'), category: n.data('entity_category'), icon: n.data('entity_icon'),
        volume: n.data('volume_btc'), txs: n.data('tx_count'), illicit: n.data('illicit'), cluster: n.data('in_cluster'),
      });
    });
    cy.on('mouseout', 'node', () => setHovered(null));
    if (onReady) onReady(cy);
  };

  // Layout: full on first render, gentle (non-random) re-layout when nodes are added
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy || nodeCount === prevCount.current) return undefined;
    // The container is measured after mount; resize first so cose gets the real viewport.
    // prevCount is only committed once the layout actually runs (StrictMode re-runs effects).
    const raf = requestAnimationFrame(() => {
      const live = cyRef.current;
      if (!live || live.destroyed()) return;
      const first = prevCount.current === 0;
      prevCount.current = nodeCount;
      live.resize();
      live.layout({ ...LAYOUT, randomize: first, animate: !first, animationDuration: 600 }).run();
    });
    return () => cancelAnimationFrame(raf);
  }, [nodeCount]);

  // Keep Cytoscape's viewport in sync with its container
  useEffect(() => {
    const el = containerRef.current;
    if (!el || typeof ResizeObserver === 'undefined') return undefined;
    const ro = new ResizeObserver(() => {
      const cy = cyRef.current;
      if (cy && !cy.destroyed()) cy.resize();
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Mark expanded nodes
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.nodes().removeClass('expanded');
    expanded.forEach((id) => cy.getElementById(id).addClass('expanded'));
  }, [expanded, nodeCount]);

  // Highlight a traced path
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.elements().removeClass('dimmed on-path');
    if (highlightPath.length < 2) return;
    const onPath = new Set(highlightPath);
    cy.elements().addClass('dimmed');
    highlightPath.forEach((id) => cy.getElementById(id).removeClass('dimmed').addClass('on-path'));
    for (let i = 0; i < highlightPath.length - 1; i++) {
      const a = highlightPath[i];
      const b = highlightPath[i + 1];
      cy.edges().filter((e) => (e.source().id() === a && e.target().id() === b) || (e.source().id() === b && e.target().id() === a))
        .removeClass('dimmed').addClass('on-path');
    }
    cy.nodes().filter((n) => onPath.has(n.id())).forEach((n) => n.removeClass('dimmed'));
  }, [highlightPath, nodeCount]);

  const exportPng = () => {
    const cy = cyRef.current;
    if (!cy) return;
    const a = document.createElement('a');
    a.href = cy.png({ full: true, scale: 2, bg: '#020617' });
    a.download = `sifra-graph-${(rootAddress || 'wallet').slice(0, 16)}.png`;
    a.click();
  };

  const btn = 'p-1.5 bg-cyan-950/80 backdrop-blur-md rounded-sm border border-cyan-500/40 text-cyan-400 hover:text-cyan-200 hover:bg-cyan-900/60 transition-all cursor-pointer';

  return (
    <div className="w-full h-full relative overflow-hidden">
      <div className="absolute inset-0 overflow-hidden opacity-20 pointer-events-none"><div className="radar-bg" /></div>

      <div className="absolute top-3 right-3 z-20 flex items-center gap-1.5">
        <span className="bg-cyan-950/80 px-2.5 py-1 rounded-sm border border-cyan-500/40 text-[10px] font-mono text-cyan-300 tracking-widest">
          EXPANDED {expanded.size}
        </span>
        <button type="button" aria-label="Zoom in" className={btn} onClick={() => cyRef.current?.zoom(cyRef.current.zoom() * 1.2)}><ZoomIn className="w-4 h-4" /></button>
        <button type="button" aria-label="Zoom out" className={btn} onClick={() => cyRef.current?.zoom(cyRef.current.zoom() * 0.8)}><ZoomOut className="w-4 h-4" /></button>
        <button type="button" aria-label="Fit graph" className={btn} onClick={() => cyRef.current?.fit(undefined, 40)}><Maximize2 className="w-4 h-4" /></button>
        <button type="button" aria-label="Re-run layout" className={btn} onClick={() => cyRef.current?.layout({ ...LAYOUT, randomize: true }).run()}><RefreshCw className="w-4 h-4" /></button>
        <button type="button" aria-label="Export graph as PNG" className={btn} onClick={exportPng}><Download className="w-4 h-4" /></button>
      </div>

      {expanding && (
        <div className="absolute inset-0 z-30 flex items-center justify-center bg-slate-950/50 backdrop-blur-[2px]">
          <div className="flex items-center gap-3 bg-cyan-950/90 px-6 py-4 rounded-sm border border-cyan-500/50">
            <span className="w-5 h-5 border-2 border-cyan-400/30 border-t-cyan-400 rounded-full animate-spin" />
            <span className="text-xs font-mono text-cyan-300 tracking-[0.2em]">EXPANDING {shortAddr(expanding, 6, 4)}…</span>
          </div>
        </div>
      )}
      {expandError && (
        <div className="absolute top-12 right-3 z-30 text-[11px] font-mono text-red-300 bg-red-950/80 border border-red-500/40 px-3 py-1.5 rounded max-w-xs">
          {expandError}
        </div>
      )}

      <div className="absolute bottom-3 left-3 z-20 bg-slate-900/90 backdrop-blur-md p-2.5 rounded-sm border-l-2 border-cyan-500 text-[9px] font-mono space-y-1">
        {LEGEND.map((item) => (
          <div key={item.label} className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full" style={{ backgroundColor: item.color, boxShadow: `0 0 5px ${item.color}` }} />
            <span className="text-slate-300 tracking-widest">{item.label}</span>
          </div>
        ))}
        <div className="text-cyan-500/70 pt-1 border-t border-cyan-500/20 tracking-widest">CLICK = TRACE · DBL-CLICK = EXPAND</div>
      </div>

      {data.truncated > 0 && (
        <div className="absolute bottom-3 right-3 z-20 text-[10px] font-mono text-slate-400 bg-slate-900/85 border border-slate-700 px-2 py-1 rounded">
          +{data.truncated} low-volume counterparties hidden
        </div>
      )}

      {hovered && (
        <div className="absolute top-3 left-3 z-20 bg-slate-900/95 backdrop-blur-md border border-cyan-500/40 p-3 rounded-sm text-xs font-mono max-w-[300px] border-l-4"
          style={{ borderLeftColor: hovered.illicit ? '#ff003c' : '#22d3ee' }}>
          <div className="text-cyan-200 font-bold mb-1 flex items-center gap-2 text-sm">
            <span>{hovered.icon}</span><span className="truncate">{hovered.name || shortAddr(hovered.id, 10, 6)}</span>
          </div>
          {hovered.category && hovered.category !== 'unknown' && (
            <div className={`text-[10px] uppercase tracking-[0.2em] mb-1 ${hovered.illicit ? 'text-red-400' : 'text-cyan-500'}`}>{hovered.category}</div>
          )}
          <div className="text-slate-400 text-[10px]">Flow with case: {formatBTC(hovered.volume)} · {hovered.txs} tx</div>
          {hovered.cluster && <div className="text-violet-300 text-[10px]">Co-spend cluster member</div>}
          <div className="text-slate-500 text-[10px] mt-1.5 break-all bg-slate-950 p-1.5 border border-slate-800 rounded-sm flex items-start gap-1">
            <span className="flex-1">{hovered.id}</span>
            {addressLink(hovered.id) && <ExternalLink className="w-3 h-3 shrink-0 text-cyan-600" />}
          </div>
        </div>
      )}

      <div ref={containerRef} className="absolute inset-0 z-10">
        <CytoscapeComponent
          elements={elements}
          style={{ width: '100%', height: '100%' }}
          stylesheet={STYLESHEET}
          layout={{ name: 'preset' }}
          minZoom={0.15}
          maxZoom={3}
          wheelSensitivity={0.2}
          cy={bindCy}
        />
      </div>
    </div>
  );
}
