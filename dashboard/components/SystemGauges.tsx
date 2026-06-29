"use client";
import type { SystemStats } from "@/lib/api";
import { useCountUp } from "@/lib/hooks";

const RING_COLORS = ["#6366f1", "#22d3ee", "#f472b6", "#fb923c"];
const LABELS = ["CPU", "RAM", "GPU VRAM", "GPU Util"];

function ArcGauge({ pct, color, isHigh }: { pct: number; color: string; isHigh: boolean }) {
  const r = 40; const cx = 50; const cy = 50;
  const toRad = (d: number) => (d * Math.PI) / 180;
  const sx = cx + r * Math.cos(toRad(210));
  const sy = cy - r * Math.sin(toRad(210));
  const ex = cx + r * Math.cos(toRad(330));
  const ey = cy - r * Math.sin(toRad(330));
  const arcLen = (240 / 360) * 2 * Math.PI * r;
  const fill = (pct / 100) * arcLen;
  const trackD = `M ${sx} ${sy} A ${r} ${r} 0 1 1 ${ex} ${ey}`;
  const strokeColor = isHigh ? "#ef4444" : color;

  return (
    <svg viewBox="0 0 100 70" className="w-full" style={{ maxWidth: 112 }}>
      <path d={trackD} fill="none" stroke="rgba(148,163,184,0.20)" strokeWidth={7} strokeLinecap="round" />
      <path
        d={trackD} fill="none" stroke={strokeColor} strokeWidth={7} strokeLinecap="round"
        strokeDasharray={arcLen} strokeDashoffset={arcLen - fill}
        style={{ transition: "stroke-dashoffset 0.7s cubic-bezier(0.16,1,0.3,1)" }}
      />
    </svg>
  );
}

function Gauge({ label, value, max, unit, color }: {
  label: string; value: number | null; max: number; unit: string; color: string;
}) {
  const pct = value != null ? Math.min(100, (value / max) * 100) : 0;
  const animatedPct = useCountUp(Math.round(pct), 600);
  const displayVal = value != null
    ? (Number.isInteger(value) ? `${value}${unit}` : `${value.toFixed(1)}${unit}`)
    : "N/A";
  const isHigh = pct > 85;

  return (
    <div className="glass glass-hover rounded-2xl p-4 flex flex-col items-center">
      <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-1">{label}</p>
      <div className="relative w-full flex items-center justify-center">
        <ArcGauge pct={pct} color={color} isHigh={isHigh} />
        <div className="absolute flex flex-col items-center" style={{ top: "68%", transform: "translateY(-50%)" }}>
          <span className={`text-sm font-bold ${isHigh ? "text-red-500 dark:text-red-400" : "text-slate-900 dark:text-white"}`}>
            {displayVal}
          </span>
          <span className="text-[10px] text-slate-500 tabular-nums">{animatedPct}%</span>
        </div>
      </div>
      {/* Thin bar */}
      <div className="w-full mt-1 h-0.5 rounded-full bg-slate-900/10 dark:bg-white/5 overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-700"
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
      unit: " GB", color: RING_COLORS[2],
    },
    { label: LABELS[3], value: data.gpu_util_percent, max: 100, unit: "%", color: RING_COLORS[3] },
  ];

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
      {gauges.map((g) => <Gauge key={g.label} {...g} />)}
    </div>
  );
}
