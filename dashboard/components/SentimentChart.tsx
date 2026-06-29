"use client";
import { useEffect, useState } from "react";
import {
  PieChart, Pie, Cell, ResponsiveContainer, Tooltip,
  RadialBarChart, RadialBar, PolarAngleAxis,
} from "recharts";

const SENTIMENT_COLORS: Record<string, string> = {
  positive: "#34d399",
  negative: "#f87171",
  neutral:  "#64748b",
  mixed:    "#fbbf24",
};

function CustomTooltip({ active, payload }: { active?: boolean; payload?: { name: string; value: number }[] }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="px-3 py-2 rounded-xl bg-black/80 backdrop-blur-xl border border-white/10 text-xs shadow-xl">
      <p className="text-slate-300 capitalize font-medium">{payload[0].name}</p>
      <p className="text-white font-bold">{payload[0].value}</p>
    </div>
  );
}

function DonutLegend({ data, total }: { data: { name: string; value: number }[]; total: number }) {
  return (
    <div className="space-y-2">
      {data.map((d) => (
        <div key={d.name} className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span
              className="w-2 h-2 rounded-full shrink-0"
              style={{ background: SENTIMENT_COLORS[d.name] ?? "#6366f1" }}
            />
            <span className="text-xs text-slate-600 dark:text-slate-400 capitalize">{d.name}</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium text-slate-800 dark:text-slate-200 tabular-nums">{d.value}</span>
            <span className="text-[10px] text-slate-400 dark:text-slate-600 tabular-nums w-8 text-right">
              {total > 0 ? `${Math.round((d.value / total) * 100)}%` : "—"}
            </span>
          </div>
        </div>
      ))}
    </div>
  );
}

export function SentimentChart({ distribution }: { distribution: Record<string, number> | undefined }) {
  const data = Object.entries(distribution ?? {}).map(([name, value]) => ({ name, value }));
  const total = data.reduce((s, d) => s + d.value, 0);

  if (!data.length) {
    return (
      <div className="flex items-center justify-center h-full">
        <p className="text-slate-400 dark:text-slate-600 text-sm">No data yet.</p>
      </div>
    );
  }

  return (
    <div className="h-full">
      <p className="text-[10px] font-mono uppercase tracking-[0.2em] text-slate-500 mb-4">Sentiment Distribution</p>
      <div className="flex items-center gap-6">
        {/* Donut */}
        <div className="relative w-36 h-36 shrink-0">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={data}
                innerRadius="62%"
                outerRadius="85%"
                paddingAngle={3}
                dataKey="value"
                startAngle={90}
                endAngle={-270}
              >
                {data.map((entry) => (
                  <Cell
                    key={entry.name}
                    fill={SENTIMENT_COLORS[entry.name] ?? "#6366f1"}
                    stroke="transparent"
                  />
                ))}
              </Pie>
              <Tooltip content={<CustomTooltip />} />
            </PieChart>
          </ResponsiveContainer>
          {/* Center label */}
          <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
            <span className="text-xl font-bold text-slate-900 dark:text-white tabular-nums">{total}</span>
            <span className="text-[9px] text-slate-500 uppercase tracking-wider">total</span>
          </div>
        </div>
        {/* Legend */}
        <div className="flex-1">
          <DonutLegend data={data} total={total} />
        </div>
      </div>
    </div>
  );
}


export function CategoryRadial({ categories }: { categories: Record<string, number> | undefined }) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => { const t = setTimeout(() => setMounted(true), 80); return () => clearTimeout(t); }, []);

  if (!categories) return null;
  const data = Object.entries(categories)
    .sort(([, a], [, b]) => b - a)
    .slice(0, 6)
    .map(([name, value]) => ({ name, value }));
  const max = Math.max(...data.map(d => d.value));

  return (
    <div>
      <p className="text-[10px] font-mono uppercase tracking-[0.2em] text-slate-500 mb-4">Top Categories</p>
      <div className="space-y-2.5">
        {data.map((d, i) => (
          <div
            key={d.name}
            className="animate-fade-in animate-fill-both"
            style={{ animationDelay: `${i * 60}ms` }}
          >
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs text-slate-700 dark:text-slate-300">{d.name}</span>
              <span className="text-xs font-mono text-slate-500 tabular-nums">{d.value}</span>
            </div>
            <div className="h-1 rounded-full bg-slate-900/[0.06] dark:bg-white/[0.04] overflow-hidden">
              <div
                className="h-full rounded-full transition-all duration-700 ease-out"
                style={{
                  width: mounted ? `${(d.value / max) * 100}%` : "0%",
                  transitionDelay: `${i * 60}ms`,
                  background: `hsl(${240 - i * 30}, 70%, 60%)`,
                }}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
