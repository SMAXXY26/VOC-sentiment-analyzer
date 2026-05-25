import type { AnalysesSummary } from "@/lib/api";

export function SummaryCards({ data }: { data: AnalysesSummary }) {
  const cards = [
    { label: "Total Analyzed", value: data.total, color: "text-indigo-400" },
    { label: "Escalated", value: data.escalation_count, color: "text-red-400" },
    { label: "Churn Risk", value: data.churn_count, color: "text-orange-400" },
    { label: "Avg Intensity", value: data.avg_intensity ? `${data.avg_intensity}/10` : "—", color: "text-yellow-400" },
  ];
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
      {cards.map((c) => (
        <div key={c.label} className="bg-gray-900 rounded-xl p-4 border border-gray-800">
          <p className="text-xs text-gray-500 mb-1">{c.label}</p>
          <p className={`text-2xl font-bold ${c.color}`}>{c.value}</p>
        </div>
      ))}
    </div>
  );
}
