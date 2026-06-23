"use client";
import { RadialBarChart, RadialBar, ResponsiveContainer, PolarAngleAxis } from "recharts";
import type { AnalysesSummary } from "@/lib/api";

function IndexGauge({
  label, sub, value, color,
}: {
  label: string; sub: string; value: number | null; color: string;
}) {
  // value is already a 0-100 percentage from the API.
  const pct = value != null ? Math.min(100, Math.max(0, value)) : 0;
  const display = value != null ? `${value}%` : "N/A";

  return (
    <div className="glass glass-hover rounded-2xl p-5 flex flex-col items-center group">
      <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-3">{label}</p>
      <div className="relative w-28 h-28">
        <ResponsiveContainer width="100%" height="100%">
          <RadialBarChart
            innerRadius="68%"
            outerRadius="100%"
            data={[{ value: pct }]}
            startAngle={210}
            endAngle={-30}
          >
            <PolarAngleAxis type="number" domain={[0, 100]} tick={false} />
            <RadialBar
              dataKey="value"
              cornerRadius={6}
              fill={color}
              background={{ fill: "rgba(148,163,184,0.18)" }}
            />
          </RadialBarChart>
        </ResponsiveContainer>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-lg font-bold text-slate-900 dark:text-white">{display}</span>
        </div>
      </div>
      <p className="text-[10px] text-slate-500 mt-2 text-center">{sub}</p>
    </div>
  );
}

export function ExperienceGauges({ data }: { data: AnalysesSummary }) {
  return (
    <div className="rounded-2xl bg-slate-900/[0.03] dark:bg-white/[0.03] border border-slate-200/70 dark:border-white/[0.07] p-5">
      <p className="text-[10px] font-mono uppercase tracking-[0.2em] text-slate-500 mb-4">Experience Indices</p>
      <div className="grid grid-cols-2 gap-3">
        <IndexGauge
          label="CSI"
          sub="Customer Satisfaction Index"
          value={data.avg_csi}
          color="#34d399"
        />
        <IndexGauge
          label="CX Index"
          sub="Customer Experience Index"
          value={data.avg_cxi}
          color="#38bdf8"
        />
      </div>
    </div>
  );
}
