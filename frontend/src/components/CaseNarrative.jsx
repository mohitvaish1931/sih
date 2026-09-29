import React from 'react';
import { Bot, ListChecks } from 'lucide-react';

const PRIORITY = {
  HIGH: 'text-red-300 border-red-500/50 bg-red-500/10',
  MEDIUM: 'text-amber-300 border-amber-500/40 bg-amber-500/10',
  LOW: 'text-cyan-300 border-cyan-500/30 bg-cyan-500/5',
};

export default function CaseNarrative({ explanation, source, recommendations = [] }) {
  const isLLM = source?.startsWith('llm');
  return (
    <div className="hud-panel p-5 flex flex-col gap-4">
      <div>
        <div className="flex items-center justify-between mb-2">
          <h3 className="section-title flex items-center gap-2"><Bot className="w-4 h-4" /> Investigator Summary</h3>
          <span className={`text-[9px] font-mono px-1.5 py-0.5 rounded border ${isLLM ? 'border-violet-500/50 text-violet-300' : 'border-slate-600 text-slate-400'}`}
            title={isLLM ? 'Rewritten by the local LLM from the evidence' : 'Generated deterministically from the evidence'}>
            {isLLM ? source.replace('llm:', 'LLM · ') : 'EVIDENCE-DERIVED'}
          </span>
        </div>
        <p className="text-[13px] text-slate-300 leading-relaxed font-body">{explanation}</p>
      </div>

      {recommendations.length > 0 && (
        <div>
          <h4 className="text-[10px] font-mono tracking-widest text-slate-400 uppercase mb-2 flex items-center gap-1.5">
            <ListChecks className="w-3.5 h-3.5" /> Recommended actions
          </h4>
          <ol className="space-y-1.5">
            {recommendations.map((r, i) => (
              <li key={i} className={`text-xs rounded border px-2.5 py-2 ${PRIORITY[r.priority] || PRIORITY.LOW}`}>
                <div className="font-mono font-bold text-[10px] tracking-widest uppercase mb-0.5">{r.priority} · {r.action}</div>
                <div className="text-slate-300 font-body leading-snug">{r.detail}</div>
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}
