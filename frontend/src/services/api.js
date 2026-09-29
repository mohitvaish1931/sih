import axios from 'axios';

// VITE_API_BASE may be given with or without the /api suffix (https://host or https://host/api)
const API_BASE_URL = (() => {
  const base = (import.meta.env.VITE_API_BASE || '/api').trim().replace(/\/+$/, '');
  return base.endsWith('/api') ? base : `${base}/api`;
})();
const http = axios.create({ baseURL: API_BASE_URL, timeout: 120000 });

/** Human-readable message from an axios error (uses the API's `detail`). */
export const errorMessage = (error) => {
  const detail = error?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) return detail.map((d) => d.msg).join('; ');
  if (error?.code === 'ECONNABORTED') return 'The analysis timed out. Blockchain providers may be slow - try again.';
  if (!error?.response) return 'Backend unreachable. Start it with: uvicorn main:app --reload (in /backend).';
  return `Request failed (${error.response.status}).`;
};

const get = async (url, config) => (await http.get(url, config)).data;
const soft = (fallback) => (promise) => promise.catch((err) => {
  console.warn(errorMessage(err));
  return fallback;
});

// ---------------------------------------------------------------------------
// Investigation
// ---------------------------------------------------------------------------
export const analyzeWallet = (address, { refresh = false } = {}) =>
  get(`/wallet/${encodeURIComponent(address)}/analyze`, { params: refresh ? { refresh: true } : {} });

export const getWalletGraph = (address) => get(`/wallet/${encodeURIComponent(address)}/graph`);

export const expandGraphNode = (address, rootAddress) =>
  get(`/wallet/${encodeURIComponent(address)}/graph/expand`, { params: { root: rootAddress } });

export const getCaseReport = (address, { analyst, caseRef } = {}) =>
  get(`/wallet/${encodeURIComponent(address)}/report`, {
    params: { ...(analyst ? { analyst } : {}), ...(caseRef ? { case_ref: caseRef } : {}) },
  });

export const verifyReport = async (payload, digest) => (await http.post('/report/verify', { payload, digest })).data;

// ---------------------------------------------------------------------------
// Platform / meta
// ---------------------------------------------------------------------------
export const getHealth = () => soft(null)(get('/health', { timeout: 8000 }));
export const getPlatformStats = () => soft(null)(get('/stats'));
export const getDemoScenarios = () => soft({ seeded: false, scenarios: [] })(get('/demo/scenarios'));
export const getWatchlist = () => soft({ entities: [] })(get('/entities/watchlist'));
export const getAlerts = (params = {}) => soft({ alerts: [] })(get('/alerts', { params }));
export const acknowledgeAlert = async (id) => (await http.post(`/alerts/${id}/ack`)).data;
export const getTelemetryStats = () => soft(null)(get('/telemetry/stats'));

// ---------------------------------------------------------------------------
// Live data
// ---------------------------------------------------------------------------
export const getLiveMempool = () => soft(null)(get('/live/mempool'));
export const getLiveBlocks = () => soft([])(get('/live/blocks'));
export const getLivePrice = () => soft({ usd: 0, usd_24h_change: 0 })(get('/live/price'));
export const getWhaleAlerts = () => soft({ whales: [] })(get('/live/whale-alerts'));

/** Server-Sent Events wallet monitor. Returns a close function. */
export const monitorWallet = (address, onMessage, onError) => {
  const eventSource = new EventSource(`${API_BASE_URL}/live/monitor/${encodeURIComponent(address)}`);
  eventSource.onmessage = (event) => {
    try {
      onMessage(JSON.parse(event.data));
    } catch (e) {
      console.error('Monitor parse error:', e);
    }
  };
  eventSource.onerror = (err) => onError && onError(err);
  return () => eventSource.close();
};

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------
export const formatUSD = (amount) => {
  if (!amount && amount !== 0) return '$0';
  return new Intl.NumberFormat('en-US', {
    style: 'currency', currency: 'USD', minimumFractionDigits: 0, maximumFractionDigits: amount > 1000 ? 0 : 2,
  }).format(amount);
};

export const formatBTC = (amount, digits = 4) => {
  if (!amount && amount !== 0) return '0 BTC';
  const n = Number(amount);
  const d = n !== 0 && Math.abs(n) < 0.001 ? 8 : digits;
  return `${n.toLocaleString('en-US', { maximumFractionDigits: d })} BTC`;
};

export const shortAddr = (addr, head = 8, tail = 6) => {
  if (!addr) return 'unknown';
  return addr.length > head + tail + 1 ? `${addr.slice(0, head)}…${addr.slice(-tail)}` : addr;
};

export const timeAgo = (iso) => {
  if (!iso) return '—';
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${Math.floor(s)}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
};

export const isDemoAddress = (a) => /^bc1_[a-z0-9_]{2,60}$/.test(a || '') || /^(Exchange|Darknet)_[A-Za-z0-9_]+$/.test(a || '');

/** Block explorer link for real transactions (demo txids are synthetic). */
export const txLink = (txid) => (txid && !txid.startsWith('demo') ? `https://mempool.space/tx/${txid}` : null);
export const addressLink = (addr) => (addr && !isDemoAddress(addr) ? `https://mempool.space/address/${addr}` : null);

export const SEVERITY_STYLES = {
  CRITICAL: { text: 'text-red-400', bg: 'bg-red-500/15', border: 'border-red-500/60', dot: 'bg-red-500', hex: '#ff003c' },
  HIGH: { text: 'text-orange-400', bg: 'bg-orange-500/15', border: 'border-orange-500/60', dot: 'bg-orange-500', hex: '#f97316' },
  MEDIUM: { text: 'text-yellow-300', bg: 'bg-yellow-500/10', border: 'border-yellow-500/50', dot: 'bg-yellow-400', hex: '#fcee0a' },
  LOW: { text: 'text-cyan-300', bg: 'bg-cyan-500/10', border: 'border-cyan-500/40', dot: 'bg-cyan-400', hex: '#00f0ff' },
  INFO: { text: 'text-slate-400', bg: 'bg-slate-500/10', border: 'border-slate-600/50', dot: 'bg-slate-500', hex: '#64748b' },
};
