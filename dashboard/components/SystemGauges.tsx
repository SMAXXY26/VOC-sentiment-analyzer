"use client";
import { RadialBarChart, RadialBar, ResponsiveContainer, PolarAngleAxis } from "recharts";
import type { SystemStats } from "@/lib/api";

const RING_COLORS = ["#6366f1", "#22d3ee", "#f472b6", "#fb923c"];
const LABELS = ["CPU", "RAM", "GPU VRAM", "GPU Util"];

function Gauge({
  label, value, max, unit, color,
}: {
  label: string; value: number | null; max: number; unit: string; color: string;
}) {
  const pct = value != null ? Math.min(100, (value / max) * 100) : 0;
  const display = value != null ? `${value}${unit}` : "N/A";
  const isHigh = pct > 85;

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
              fill={isHigh ? "#ef4444" : color}
              background={{ fill: "rgba(255,255,255,0.04)" }}
            />
          </RadialBarChart>
        </ResponsiveContainer>
        {/* Center value */}
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-base font-bold text-white">{display}</span>
          <span className="text-[10px] text-slate-500">{Math.round(pct)}%</span>
        </div>
      </div>
      {/* Thin bottom bar */}
      <div className="w-full mt-3 h-0.5 rounded-full bg-white/5 overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{ width: `${pct}%`, backgroundColor: isHigh ? "#ef4444" : color }}
        />
      </div>
    </div>
  );
}

export function SystemGauges({ data }: { data: SystemStats }) {
  const gauges = [
    { label: LABELS[0], value: data.cpu_percent, max: 100, unit: "%", color: RING_COLORS[0] },
    { label: LABELS[1], value: data.ram_used_gb, max: data.ram_total_gb, unit: " GB", color: RING_COLORS[1] },
    {
      label: LABELS[2],
      value: data.gpu_used_mb != null ? Math.round(data.gpu_used_mb / 1024) : null,
      max: data.gpu_total_mb != null ? Math.round(data.gpu_total_mb / 1024) : 8,
      unit: " GB",
      color: RING_COLORS[2],
    },
    { label: LABELS[3], value: data.gpu_util_percent, max: 100, unit: "%", color: RING_COLORS[3] },
  ];

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
      {gauges.map((g) => <Gauge key={g.label} {...g} />)}
    </div>
  );
}
