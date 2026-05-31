const STYLES: Record<string, string> = {
  positive: "bg-emerald-500/15 text-emerald-300 border border-emerald-500/25",
  negative: "bg-red-500/15 text-red-300 border border-red-500/25",
  neutral:  "bg-slate-500/15 text-slate-300 border border-slate-500/25",
  mixed:    "bg-amber-500/15 text-amber-300 border border-amber-500/25",
};

export function SentimentBadge({ value }: { value: string }) {
  return (
    <span className={`inline-flex items-center text-[11px] font-medium px-2 py-0.5 rounded-full capitalize ${STYLES[value] ?? "bg-slate-700/40 text-slate-400 border border-slate-600/30"}`}>
      {value}
    </span>
  );
}
