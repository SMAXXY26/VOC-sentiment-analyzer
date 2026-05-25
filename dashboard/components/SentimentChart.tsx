"use client";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from "recharts";

const COLORS: Record<string, string> = {
  positive: "#4ade80",
  negative: "#f87171",
  neutral: "#94a3b8",
  mixed: "#fbbf24",
};

export function SentimentChart({ distribution }: { distribution: Record<string, number> | undefined }) {
  const data = Object.entries(distribution ?? {}).map(([name, value]) => ({ name, value }));
  if (!data.length) return <p className="text-gray-500 text-sm">No data yet.</p>;
  return (
    <div className="bg-gray-900 rounded-xl p-4 border border-gray-800 mb-6">
      <p className="text-xs text-gray-500 mb-3">Sentiment Distribution</p>
      <ResponsiveContainer width="100%" height={160}>
        <BarChart data={data} margin={{ top: 0, right: 10, left: -20, bottom: 0 }}>
          <XAxis dataKey="name" tick={{ fill: "#94a3b8", fontSize: 12 }} />
          <YAxis tick={{ fill: "#94a3b8", fontSize: 12 }} allowDecimals={false} />
          <Tooltip
            contentStyle={{ backgroundColor: "#1f2937", border: "1px solid #374151", borderRadius: 8 }}
            labelStyle={{ color: "#e5e7eb" }}
          />
          <Bar dataKey="value" radius={[4, 4, 0, 0]}>
            {data.map((entry) => (
              <Cell key={entry.name} fill={COLORS[entry.name] ?? "#6366f1"} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
