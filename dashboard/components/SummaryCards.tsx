import type { AnalysesSummary } from "@/lib/api";

interface CardConfig {
  label: string;
  value: string | number;
  sub?: string;
  from: string;
  to: string;
  border: string;
  text: string;
  icon: React.ReactNode;
}

function GlowCard({ label, value, sub, from, to, border, text, icon }: CardConfig) {
  return (
    <div className={`relative overflow-hidden rounded-2xl bg-gradient-to-br ${from} ${to} border ${border} p-5 shadow-lg transition-all duration-300 glass-hover`}>
      <div className="flex items-start justify-between mb-4">
        <p className="text-[11px] font-semibold uppercase tracking-widest text-slate-600 dark:text-slate-400">{label}</p>
        <div className={`${text} opacity-50`}>{icon}</div>
      </div>
      <p className={`text-3xl font-bold ${text} tracking-tight tabular-nums`}>{value ?? "—"}</p>
      {sub && <p className="text-[11px] text-slate-500 mt-1">{sub}</p>}
      {/* Subtle corner glow */}
      <div className={`absolute -bottom-4 -right-4 w-20 h-20 rounded-full ${from} blur-2xl opacity-40`} />
    </div>
  );
}

export function SummaryCards({ data }: { data: AnalysesSummary }) {
  const cards: CardConfig[] = [
    {
      label: "Total Analyzed",
      value: data.total,
      sub: "feedback items processed",
      from: "from-indigo-500/[0.12]",
      to: "to-transparent",
      border: "border-indigo-500/20",
      text: "text-indigo-600 dark:text-indigo-300",
      icon: (
        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 3v11.25A2.25 2.25 0 0 0 6 16.5h2.25M3.75 3h-1.5m1.5 0h16.5m0 0h1.5m-1.5 0v11.25A2.25 2.25 0 0 1 18 16.5h-2.25m-7.5 0h7.5m-7.5 0-1 3m8.5-3 1 3m0 0 .5 1.5m-.5-1.5h-9.5m0 0-.5 1.5M9 11.25v1.5M12 9v3.75m3-6v6" />
        </svg>
      ),
    },
    {
      label: "Escalated",
      value: data.escalation_count,
      sub: "require immediate action",
      from: "from-red-500/[0.12]",
      to: "to-transparent",
      border: "border-red-500/20",
      text: "text-red-600 dark:text-red-300",
      icon: (
        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126ZM12 15.75h.007v.008H12v-.008Z" />
        </svg>
      ),
    },
    {
      label: "Churn Risk",
      value: data.churn_count,
      sub: "customers at risk",
      from: "from-orange-500/[0.12]",
      to: "to-transparent",
      border: "border-orange-500/20",
      text: "text-orange-600 dark:text-orange-300",
      icon: (
        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 9V5.25A2.25 2.25 0 0 0 13.5 3h-6a2.25 2.25 0 0 0-2.25 2.25v13.5A2.25 2.25 0 0 0 7.5 21h6a2.25 2.25 0 0 0 2.25-2.25V15M12 9l-3 3m0 0 3 3m-3-3h12.75" />
        </svg>
      ),
    },
    {
      label: "Avg Intensity",
      value: data.avg_intensity ? `${data.avg_intensity}/10` : "—",
      sub: "emotional intensity score",
      from: "from-violet-500/[0.12]",
      to: "to-transparent",
      border: "border-violet-500/20",
      text: "text-violet-600 dark:text-violet-300",
      icon: (
        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 13.5l10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75z" />
        </svg>
      ),
    },
  ];

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
      {cards.map((c) => <GlowCard key={c.label} {...c} />)}
    </div>
  );
}
