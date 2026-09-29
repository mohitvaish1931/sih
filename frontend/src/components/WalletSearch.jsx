import React, { useEffect, useState } from 'react';
import { Clock, X, Crosshair, TerminalSquare, FlaskConical } from 'lucide-react';
import { getDemoScenarios, isDemoAddress } from '../services/api';

// Real, checksum-valid mainnet addresses with public attribution
const KNOWN_TARGETS = [
  { label: 'WANNACRY', address: '13AM4VW2dhxYgXeQepoHkHSQuy6NgaEb94', icon: '🦠' },
  { label: 'BITFINEX_HACK', address: 'bc1qazcm763858nkj2dj986etajv6wquslv8uxwczt', icon: '💀' },
  { label: 'SILK_ROAD', address: '1FfmbHfnpaZjKFvyi1okTjJJusN455paPH', icon: '🕸️' },
  { label: 'TWITTER_SCAM', address: 'bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh', icon: '🎭' },
  { label: 'GENESIS', address: '1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa', icon: '👑' },
];

const HISTORY_KEY = 'sifra_search_history';

// Format check only - the backend verifies Base58Check / Bech32(m) checksums.
function looksLikeAddress(address) {
  if (isDemoAddress(address)) return true;
  if (/^[13][a-km-zA-HJ-NP-Z1-9]{25,34}$/.test(address)) return true;
  return /^(bc1|BC1)[a-zA-HJ-NP-Z0-9]{11,87}$/.test(address);
}

function loadHistory() {
  try {
    const saved = localStorage.getItem(HISTORY_KEY);
    return saved ? JSON.parse(saved) : [];
  } catch {
    return [];
  }
}

export default function WalletSearch({ onSearch, loading, compact = false, initial = '' }) {
  const [input, setInput] = useState(initial);
  const [history, setHistory] = useState(loadHistory);
  const [showHistory, setShowHistory] = useState(false);
  const [validationError, setValidationError] = useState(null);
  const [scenarios, setScenarios] = useState([]);

  useEffect(() => {
    let alive = true;
    getDemoScenarios().then((d) => alive && setScenarios((d?.scenarios || []).filter((s) => s.available)));
    return () => { alive = false; };
  }, []);

  const saveToHistory = (address) => {
    const updated = [address, ...history.filter((h) => h !== address)].slice(0, 10);
    setHistory(updated);
    try { localStorage.setItem(HISTORY_KEY, JSON.stringify(updated)); } catch { /* storage unavailable */ }
  };

  const clearHistory = () => {
    setHistory([]);
    try { localStorage.removeItem(HISTORY_KEY); } catch { /* storage unavailable */ }
  };

  const run = (address) => {
    setInput(address);
    setValidationError(null);
    saveToHistory(address);
    onSearch(address);
    setShowHistory(false);
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    const trimmed = input.trim();
    if (!trimmed) return;
    if (!looksLikeAddress(trimmed)) {
      setValidationError('ERR_INVALID_ADDRESS: expected a mainnet address (1..., 3..., bc1...) or a demo scenario id');
      return;
    }
    run(trimmed);
  };

  return (
    <div className={`flex flex-col gap-4 w-full ${compact ? '' : 'p-2'}`}>
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <TerminalSquare className="w-5 h-5 text-cyan-400" />
          <h3 className="section-title text-base">Target Acquisition</h3>
        </div>
        <span className="hidden md:inline text-[10px] text-slate-500 font-mono tracking-widest">
          P2PKH · P2SH · SEGWIT · TAPROOT
        </span>
      </div>

      <form onSubmit={handleSubmit} className="flex flex-col md:flex-row gap-3 w-full relative z-20">
        <div className="relative flex-1 group">
          <div className="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none">
            <Crosshair className="h-5 w-5 text-cyan-500 group-focus-within:text-cyan-300 transition-colors" />
          </div>
          <input
            type="text"
            value={input}
            aria-label="Bitcoin address"
            spellCheck={false}
            autoComplete="off"
            onChange={(e) => { setInput(e.target.value); setValidationError(null); }}
            onFocus={() => history.length > 0 && setShowHistory(true)}
            onBlur={() => setTimeout(() => setShowHistory(false), 200)}
            placeholder="PASTE A BITCOIN ADDRESS OR PICK A SCENARIO BELOW..."
            className={`block w-full pl-12 pr-4 py-3.5 bg-[#020617]/80 border-2 rounded-sm text-cyan-200 placeholder-cyan-700/60 focus:outline-none transition-all font-mono text-sm tracking-wide ${
              validationError ? 'border-red-500/70 text-red-300' : 'border-cyan-500/30 focus:border-cyan-400'
            }`}
            disabled={loading}
          />

          {showHistory && history.length > 0 && (
            <div className="absolute top-full left-0 right-0 mt-2 bg-slate-900/95 backdrop-blur-xl border border-cyan-500/40 rounded-sm shadow-[0_10px_30px_rgba(0,0,0,0.8)] z-30 overflow-hidden">
              <div className="flex items-center justify-between px-4 py-2.5 border-b border-cyan-500/20 bg-cyan-950/30">
                <span className="text-[10px] text-cyan-400 font-mono uppercase tracking-[0.2em] flex items-center gap-2">
                  <Clock className="w-3.5 h-3.5" /> Query History
                </span>
                <button type="button" onMouseDown={(e) => { e.preventDefault(); clearHistory(); }}
                  className="text-[10px] text-red-400 hover:text-red-300 font-mono cursor-pointer">[ PURGE ]</button>
              </div>
              <div className="max-h-48 overflow-y-auto custom-scrollbar">
                {history.map((addr) => (
                  <button key={addr} type="button" onMouseDown={(e) => { e.preventDefault(); run(addr); }}
                    className="w-full text-left px-4 py-2.5 text-xs font-mono text-cyan-500/80 hover:bg-cyan-500/10 hover:text-cyan-300 border-l-2 border-transparent hover:border-cyan-400 transition-all cursor-pointer truncate">
                    {addr}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>

        <button type="submit" disabled={loading}
          className="glow-btn px-8 py-3.5 bg-cyan-500/10 hover:bg-cyan-500/20 text-cyan-300 border-2 border-cyan-500 hover:border-cyan-300 font-bold tracking-[0.2em] uppercase shadow-[0_0_15px_rgba(0,240,255,0.2)] transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center min-w-[180px] cursor-pointer font-mono rounded-sm">
          {loading ? (
            <span className="flex items-center gap-3">
              <span className="w-4 h-4 border-2 border-cyan-400/30 border-t-cyan-400 rounded-full animate-spin" />
              <span className="animate-pulse">SCANNING...</span>
            </span>
          ) : 'INVESTIGATE'}
        </button>
      </form>

      {validationError && (
        <div role="alert" className="flex items-center gap-2 text-[11px] text-red-400 font-mono tracking-wide bg-red-500/10 border-l-2 border-red-500 px-4 py-2">
          <X className="w-4 h-4 shrink-0" /> {validationError}
        </div>
      )}

      {!compact && (
        <div className="space-y-2.5">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[10px] text-cyan-600 font-bold font-mono tracking-[0.2em] w-32 shrink-0">KNOWN THREATS //</span>
            {KNOWN_TARGETS.map((item) => (
              <button key={item.address} type="button" disabled={loading} onClick={() => run(item.address)}
                title={item.address}
                className="px-3 py-1 bg-slate-900/80 hover:bg-cyan-900/40 text-cyan-500/90 hover:text-cyan-300 text-[10px] rounded-sm border border-cyan-500/30 hover:border-cyan-400 transition-all font-mono tracking-widest cursor-pointer disabled:opacity-50 flex items-center gap-2">
                <span>{item.icon}</span>{item.label}
              </button>
            ))}
          </div>
          {scenarios.length > 0 && (
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[10px] text-fuchsia-400/80 font-bold font-mono tracking-[0.2em] w-32 shrink-0 flex items-center gap-1">
                <FlaskConical className="w-3 h-3" /> DEMO CASES //
              </span>
              {scenarios.map((s) => (
                <button key={s.address} type="button" disabled={loading} onClick={() => run(s.address)}
                  title={`${s.title} — ${s.story}`}
                  className="px-3 py-1 bg-fuchsia-950/30 hover:bg-fuchsia-900/40 text-fuchsia-300/90 hover:text-fuchsia-200 text-[10px] rounded-sm border border-fuchsia-500/30 hover:border-fuchsia-400 transition-all font-mono tracking-widest cursor-pointer disabled:opacity-50 flex items-center gap-2">
                  <span>{s.icon}</span>{s.label}
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
