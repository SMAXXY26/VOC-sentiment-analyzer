"use client";
import type { AnalysesSummary } from "@/lib/api";
import { useCountUp } from "@/lib/hooks";

// SVG arc gauge: 240° sweep from lower-left (210°) to lower-right (330°), opening at bottom.
// r=40, viewBox 100×80 — cropped below center so empty space under the arc is clipped.
function ArcGauge({ pct, color }: { pct: number; color: string }) {
  const r = 40;
  const cx = 50;
  const cy = 50;
  const toRad = (d: number) => (d * Math.PI) / 180;

  // Start = 210° (lower-left), end = 330° (lower-right), sweeping CW through top.
  const sx = cx + r * Math.cos(toRad(210));
  const sy = cy - r * Math.sin(toRad(210));
  const ex = cx + r * Math.cos(toRad(330));
  const ey = cy - r * Math.sin(toRad(330));

  const totalDeg = 240;
  const arcLen = (totalDeg / 360) * 2 * Math.PI * r;
  const fill = (pct / 100) * arcLen;

  const trackD = `M ${sx} ${sy} A ${r} ${r} 0 1 1 ${ex} ${ey}`;

  return (
    // viewBox crops 20px below center — eliminates dead space under the arc.
    <svg viewBox="0 0 100 70" className="w-full" style={{ maxWidth: 120 }}>
      {/* Track */}
      <path d={trackD} fill="none" stroke="rgba(148,163,184,0.20)" strokeWidth={7} strokeLinecap="round" />
      {/* Fill */}
      <path
        d={trackD}
        fill="none"
        stroke={color}
        strokeWidth={7}
        strokeLinecap="round"
        strokeDasharray={arcLen}
        strokeDashoffset={arcLen - fill}
        style={{ transition: "stroke-dashoffset 1s cubic-bezier(0.16,1,0.3,1)" }}
      />
    </svg>
  );
}

function IndexGauge({ label, sub, value, color }: {
  label: string; sub: string; value: number | null; color: string;
}) {
  const pct = value != null ? Math.min(100, Math.max(0, value)) : 0;
  const animated = useCountUp(pct, 900, 0);
  const display = value != null ? `${animated}%` : "N/A";

  return (
    <div className="glass glass-hover rounded-2xl p-5 flex flex-col items-center">
      <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-2">{label}</p>
      <div className="relative w-full flex items-center justify-center">
        <ArcGauge pct={pct} color={color} />
        {/* SVG arc center is at (50,50) in a 100×70 viewBox → 71.4% from top */}
        <span className="absolute text-xl font-bold text-slate-900 dark:text-white" style={{ top: "71%", transform: "translateY(-50%)" }}>
          {display}
        </span>
      </div>
      <p className="text-[10px] text-slate-500 text-center -mt-1">{sub}</p>
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
