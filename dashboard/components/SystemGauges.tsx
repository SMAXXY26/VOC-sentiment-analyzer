"use client";
import { RadialBarChart, RadialBar, ResponsiveContainer, PolarAngleAxis } from "recharts";
import type { SystemStats } from "@/lib/api";

function Gauge({ label, value, max, unit, color }: {
  label: string; value: number | null; max: number; unit: string; color: string;
}) {
  const pct = value != null ? Math.min(100, (value / max) * 100) : 0;
  const display = value != null ? `${value}${unit}` : "N/A";
  return (
    <div className="bg-gray-900 rounded-xl border border-gray-800 p-4 flex flex-col items-center">
      <p className="text-xs text-gray-500 mb-2">{label}</p>
      <div className="relative w-32 h-32">
        <ResponsiveContainer width="100%" height="100%">
          <RadialBarChart
            innerRadius="70%"
            outerRadius="100%"
            data={[{ value: pct }]}
            startAngle={210}
            endAngle={-30}
          >
            <PolarAngleAxis type="number" domain={[0, 100]} tick={false} />
            <RadialBar
              dataKey="value"
              cornerRadius={4}
              fill={color}
              background={{ fill: "#1f2937" }}
            />
          </RadialBarChart>
        </ResponsiveContainer>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-lg font-bold text-white">{display}</span>
          <span className="text-xs text-gray-500">{Math.round(pct)}%</span>
        </div>
      </div>
    </div>
  );
}

export function SystemGauges({ data }: { data: SystemStats }) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
      <Gauge label="CPU" value={data.cpu_percent} max={100} unit="%" color="#6366f1" />
      <Gauge label="RAM" value={data.ram_used_gb} max={data.ram_total_gb} unit=" GB" color="#22d3ee" />
      <Gauge
        label="GPU VRAM"
        value={data.gpu_used_mb != null ? Math.round(data.gpu_used_mb / 1024) : null}
        max={data.gpu_total_mb != null ? Math.round(data.gpu_total_mb / 1024) : 8}
        unit=" GB"
        color="#f472b6"
      />
      <Gauge label="GPU Util" value={data.gpu_util_percent} max={100} unit="%" color="#fb923c" />
    </div>
  );
}
