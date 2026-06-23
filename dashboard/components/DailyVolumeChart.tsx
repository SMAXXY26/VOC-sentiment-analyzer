"use client";
import { BarChart, Bar, XAxis, YAxis, ResponsiveContainer, Tooltip, CartesianGrid, Cell } from "recharts";
import { useMemo, useState } from "react";

/**
 * Feedback volume bar chart with drill-down: months → weeks → days.
 * Fed once by the summary `daily_counts` map ("YYYY-MM-DD" -> count); weekly and
 * monthly buckets are aggregated entirely on the client. Click a bar to zoom in.
 */

type Level = "month" | "week" | "day";
type Bucket = { key: string; label: string; count: number };

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function utc(dateStr: string): Date {
  return new Date(dateStr + "T00:00:00Z");
}

// Monday (YYYY-MM-DD) of the ISO week containing dateStr.
function mondayOf(dateStr: string): string {
  const d = utc(dateStr);
  const dow = d.getUTCDay(); // 0=Sun..6=Sat
  d.setUTCDate(d.getUTCDate() + (dow === 0 ? -6 : 1 - dow));
  return d.toISOString().slice(0, 10);
}

function CustomTooltip({ active, payload, label }: { active?: boolean; payload?: { value: number }[]; label?: string }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="px-3 py-2 rounded-xl bg-black/80 backdrop-blur-xl border border-white/10 text-xs shadow-xl">
      <p className="text-slate-300 font-medium">{label}</p>
      <p className="text-white font-bold tabular-nums">{payload[0].value} items</p>
    </div>
  );
}

export function DailyVolumeChart({ counts }: { counts: Record<string, number> | undefined }) {
  // drill state: which month, then which week (Monday key) are selected
  const [month, setMonth] = useState<string | null>(null); // "YYYY-MM"
  const [week, setWeek] = useState<string | null>(null); // Monday "YYYY-MM-DD"

  const days = useMemo(() => Object.entries(counts ?? {}), [counts]);

  const level: Level = week ? "day" : month ? "week" : "month";

  const data = useMemo<Bucket[]>(() => {
    if (level === "month") {
      const m = new Map<string, number>();
      for (const [date, c] of days) {
        const k = date.slice(0, 7); // YYYY-MM
        m.set(k, (m.get(k) ?? 0) + c);
      }
      return Array.from(m.entries())
        .sort((a, b) => a[0].localeCompare(b[0]))
        .map(([key, count]) => {
          const [y, mo] = key.split("-");
          return { key, label: `${MONTHS[+mo - 1]} ${y.slice(2)}`, count };
        });
    }
    if (level === "week") {
      const m = new Map<string, number>();
      for (const [date, c] of days) {
        if (date.slice(0, 7) !== month) continue;
        const k = mondayOf(date);
        m.set(k, (m.get(k) ?? 0) + c);
      }
      return Array.from(m.entries())
        .sort((a, b) => a[0].localeCompare(b[0]))
        .map(([key, count]) => {
          const d = utc(key);
          return { key, label: `Wk ${MONTHS[d.getUTCMonth()]} ${d.getUTCDate()}`, count };
        });
    }
    // day level — 7 consecutive days starting from the selected Monday
    const start = utc(week as string);
    const map = new Map(days);
    const out: Bucket[] = [];
    for (let i = 0; i < 7; i++) {
      const d = new Date(start);
      d.setUTCDate(start.getUTCDate() + i);
      const key = d.toISOString().slice(0, 10);
      out.push({ key, label: `${MONTHS[d.getUTCMonth()]} ${d.getUTCDate()}`, count: map.get(key) ?? 0 });
    }
    return out;
  }, [days, level, month, week]);

  const onBarClick = (b: Bucket) => {
    if (level === "month") setMonth(b.key);
    else if (level === "week") setWeek(b.key);
  };

  const crumbs: { label: string; onClick: () => void }[] = [
    { label: "All months", onClick: () => { setMonth(null); setWeek(null); } },
  ];
  if (month) {
    const [y, mo] = month.split("-");
    crumbs.push({ label: `${MONTHS[+mo - 1]} ${y}`, onClick: () => setWeek(null) });
  }
  if (week) {
    const d = utc(week);
    crumbs.push({ label: `Wk of ${MONTHS[d.getUTCMonth()]} ${d.getUTCDate()}`, onClick: () => {} });
  }

  if (!days.length) {
    return (
      <div className="h-44 flex flex-col items-center justify-center text-center">
        <p className="text-slate-400 dark:text-slate-600 text-sm">No dated feedback yet</p>
        <p className="text-slate-400/70 dark:text-slate-700 text-xs mt-1">
          Only items analyzed after this release carry a timestamp
        </p>
      </div>
    );
  }

  const max = Math.max(1, ...data.map((d) => d.count));
  const canDrill = level !== "day";

  return (
    <div>
      {/* Breadcrumb / drill-down trail */}
      <div className="flex items-center gap-1.5 mb-3 text-[11px] flex-wrap">
        {crumbs.map((c, i) => (
          <span key={i} className="flex items-center gap-1.5">
            {i > 0 && <span className="text-slate-400 dark:text-slate-600">›</span>}
            <button
              onClick={c.onClick}
              disabled={i === crumbs.length - 1}
              className={
                i === crumbs.length - 1
                  ? "text-slate-700 dark:text-slate-300 font-medium cursor-default"
                  : "text-indigo-600 dark:text-indigo-400 hover:underline cursor-pointer"
              }
            >
              {c.label}
            </button>
          </span>
        ))}
        <span className="ml-auto text-slate-400 dark:text-slate-600">
          {canDrill ? "click a bar to zoom in" : "daily view"}
        </span>
      </div>

      <div className="h-44 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 4, right: 8, left: -18, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="currentColor" className="text-slate-300/40 dark:text-white/[0.06]" vertical={false} />
            <XAxis dataKey="label" tick={{ fontSize: 10, fill: "currentColor" }} className="text-slate-500" axisLine={false} tickLine={false} interval="preserveStartEnd" />
            <YAxis allowDecimals={false} tick={{ fontSize: 10, fill: "currentColor" }} className="text-slate-500" axisLine={false} tickLine={false} width={32} />
            <Tooltip content={<CustomTooltip />} cursor={{ fill: "rgba(99,102,241,0.08)" }} />
            <Bar
              dataKey="count"
              radius={[4, 4, 0, 0]}
              maxBarSize={48}
              onClick={(_, i) => onBarClick(data[i])}
              cursor={canDrill ? "pointer" : "default"}
            >
              {data.map((d, i) => (
                <Cell key={i} fill={`hsl(243, 75%, ${58 + (1 - d.count / max) * 16}%)`} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
