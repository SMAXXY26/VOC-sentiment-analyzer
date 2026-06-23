"use client";
import {
  BarChart, Bar, XAxis, YAxis, ResponsiveContainer, Tooltip, CartesianGrid, Cell,
} from "recharts";
import { useMemo } from "react";

function CustomTooltip({ active, payload, label }: {
  active?: boolean; payload?: { value: number }[]; label?: string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="px-3 py-2 rounded-xl bg-black/80 backdrop-blur-xl border border-white/10 text-xs shadow-xl">
      <p className="text-slate-300 font-medium">{label}</p>
      <p className="text-white font-bold tabular-nums">{payload[0].value} items</p>
    </div>
  );
}

/** Feedback volume per calendar day. Fed by the summary `daily_counts` map. */
export function DailyVolumeChart({ counts }: { counts: Record<string, number> | undefined }) {
  const data = useMemo(
    () =>
      Object.entries(counts ?? {})
        .sort((a, b) => a[0].localeCompare(b[0]))
        .map(([date, count]) => ({
          // Short label e.g. "Jun 20"
          date: new Date(date + "T00:00:00Z").toLocaleDateString("en-US", {
            month: "short", day: "numeric", timeZone: "UTC",
          }),
          count,
        })),
    [counts],
  );

  if (!data.length) {
    return (
      <div className="h-44 flex flex-col items-center justify-center text-center">
        <p className="text-slate-400 dark:text-slate-600 text-sm">No dated feedback yet</p>
        <p className="text-slate-400/70 dark:text-slate-700 text-xs mt-1">
          Only items analyzed after this release carry a timestamp
        </p>
      </div>
    );
  }

  const max = Math.max(...data.map((d) => d.count));

  return (
    <div className="h-44 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 4, right: 8, left: -18, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="currentColor" className="text-slate-300/40 dark:text-white/[0.06]" vertical={false} />
          <XAxis
            dataKey="date"
            tick={{ fontSize: 10, fill: "currentColor" }}
            className="text-slate-500"
            axisLine={false}
            tickLine={false}
            interval="preserveStartEnd"
          />
          <YAxis
            allowDecimals={false}
            tick={{ fontSize: 10, fill: "currentColor" }}
            className="text-slate-500"
            axisLine={false}
            tickLine={false}
            width={32}
          />
          <Tooltip content={<CustomTooltip />} cursor={{ fill: "rgba(99,102,241,0.08)" }} />
          <Bar dataKey="count" radius={[4, 4, 0, 0]} maxBarSize={48}>
            {data.map((d, i) => (
              <Cell
                key={i}
                fill={`hsl(243, 75%, ${58 + (1 - d.count / max) * 16}%)`}
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
