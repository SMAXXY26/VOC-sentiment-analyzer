const STYLES: Record<string, string> = {
  low:      "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border border-emerald-500/25",
  medium:   "bg-amber-500/15 text-amber-700 dark:text-amber-300 border border-amber-500/25",
  high:     "bg-orange-500/15 text-orange-700 dark:text-orange-300 border border-orange-500/25",
  critical: "bg-red-500/15 text-red-700 dark:text-red-300 border border-red-500/25",
};

const DOTS: Record<string, string> = {
  low: "bg-emerald-400", medium: "bg-amber-400", high: "bg-orange-400", critical: "bg-red-400 animate-pulse",
};

export function RiskBadge({ value }: { value: string }) {
  return (
    <span className={`inline-flex items-center gap-1.5 text-[11px] font-medium px-2 py-0.5 rounded-full capitalize ${STYLES[value] ?? "bg-slate-700/40 text-slate-600 dark:text-slate-400 border border-slate-600/30"}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${DOTS[value] ?? "bg-slate-400"}`} />
      {value}
    </span>
  );
}
