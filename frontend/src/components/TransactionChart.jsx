import React from 'react';
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts';
import { BarChart3 } from 'lucide-react';

export default function TransactionChart({ data }) {
  return (
    <div className="h-full flex flex-col">
      <h3 className="section-title flex items-center gap-2 mb-2"><BarChart3 className="w-4 h-4" /> Flow Activity</h3>
      {!data || data.length === 0 ? (
        <div className="flex-1 flex items-center justify-center text-slate-500 text-xs">No dated transactions.</div>
      ) : (
        <div className="flex-1 w-full min-h-[160px]">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={data} margin={{ top: 5, right: 8, left: -18, bottom: 0 }}>
              <defs>
                <linearGradient id="gIn" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#22c55e" stopOpacity={0.35} /><stop offset="95%" stopColor="#22c55e" stopOpacity={0} />
                </linearGradient>
                <linearGradient id="gOut" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#ef4444" stopOpacity={0.35} /><stop offset="95%" stopColor="#ef4444" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
              <XAxis dataKey="date" stroke="#64748b" fontSize={9} tickFormatter={(v) => v.slice(5).replace('-', '/')} />
              <YAxis stroke="#64748b" fontSize={9} />
              <Tooltip
                contentStyle={{ backgroundColor: '#0f172a', borderColor: '#334155', borderRadius: '0.5rem', fontSize: '11px' }}
                formatter={(v, name) => [`${Number(v).toLocaleString('en-US', { maximumFractionDigits: 6 })} BTC`, name]}
              />
              <Legend wrapperStyle={{ fontSize: 10 }} />
              <Area type="monotone" dataKey="received" name="Inflow" stroke="#22c55e" fill="url(#gIn)" strokeWidth={2} />
              <Area type="monotone" dataKey="sent" name="Outflow" stroke="#ef4444" fill="url(#gOut)" strokeWidth={2} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
