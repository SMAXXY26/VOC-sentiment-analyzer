"use client";
import type { AnalysesSummary } from "@/lib/api";
import { useCountUp } from "@/lib/hooks";
import { ArcGauge } from "./ArcGauge";

function IndexGauge({ label, sub, value, color }: {
  label: string; sub: string; value: number | null; color: string;
}) {
  const pct = value != null ? Math.min(100, Math.max(0, value)) : 0;
  const animated = useCountUp(pct, 900, 0);
  const display = value != null ? `${animated}%` : "N/A";

  return (
    <div className="glass glass-hover rounded-2xl p-5 flex flex-col items-center">
      <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-2">{label}</p>
      <ArcGauge pct={pct} color={color} value={display} />
      <p className="text-[10px] text-slate-500 text-center mt-1">{sub}</p>
    </div>
  );
}

export function ExperienceGauges({ data }: { data: AnalysesSummary }) {
  return (
    <div className="rounded-2xl glass p-5">
      <p className="text-[10px] font-mono uppercase tracking-[0.2em] text-slate-500 mb-4">Experience Indices</p>
      <div className="grid grid-cols-2 gap-3">
        <IndexGauge label="CSI" sub="Customer Satisfaction Index" value={data.avg_csi} color="#34d399" />
        <IndexGauge label="CX Index" sub="Customer Experience Index" value={data.avg_cxi} color="#38bdf8" />
      </div>
    </div>
  );
}
