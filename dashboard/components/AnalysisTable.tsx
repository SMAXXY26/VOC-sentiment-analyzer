"use client";
import { useState } from "react";
import type { AnalysisItem } from "@/lib/api";
import { SentimentBadge } from "./SentimentBadge";
import { RiskBadge } from "./RiskBadge";

export function AnalysisTable({ items }: { items: AnalysisItem[] }) {
  const [expanded, setExpanded] = useState<number | null>(null);

  if (!items.length) {
    return <p className="text-gray-500 text-sm text-center py-12">No analyses yet. Run the pipeline to populate data.</p>;
  }

  return (
    <div className="bg-gray-900 rounded-xl border border-gray-800 overflow-hidden">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-gray-800 text-gray-400 text-xs uppercase tracking-wider">
            <th className="px-4 py-3 text-left">Summary</th>
            <th className="px-4 py-3 text-left">Category</th>
            <th className="px-4 py-3 text-left">Sentiment</th>
            <th className="px-4 py-3 text-left">Risk</th>
            <th className="px-4 py-3 text-center">Churn</th>
            <th className="px-4 py-3 text-left">Source</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item, i) => (
            <>
              <tr
                key={i}
                className="border-b border-gray-800/50 hover:bg-gray-800/50 cursor-pointer transition-colors"
                onClick={() => setExpanded(expanded === i ? null : i)}
              >
                <td className="px-4 py-3 max-w-xs truncate text-gray-200">{item.summary}</td>
                <td className="px-4 py-3 text-gray-400">{item.category}</td>
                <td className="px-4 py-3"><SentimentBadge value={item.sentiment} /></td>
                <td className="px-4 py-3"><RiskBadge value={item.risk_level} /></td>
                <td className="px-4 py-3 text-center">
                  {item.churn_risk
                    ? <span className="text-red-400 font-medium">Yes</span>
                    : <span className="text-gray-600">—</span>}
                </td>
                <td className="px-4 py-3 text-gray-500 text-xs">{item.source}</td>
              </tr>
              {expanded === i && (
                <tr key={`${i}-detail`} className="border-b border-gray-800 bg-gray-800/30">
                  <td colSpan={6} className="px-6 py-4">
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
                      {item.raw_text && (
                        <div>
                          <p className="text-gray-500 text-xs mb-1">Raw Text</p>
                          <p className="text-gray-300 italic">&ldquo;{item.raw_text}&rdquo;</p>
                        </div>
                      )}
                      {item.feature_requests?.length > 0 && (
                        <div>
                          <p className="text-gray-500 text-xs mb-1">Feature Requests</p>
                          <ul className="list-disc list-inside text-gray-300 space-y-0.5">
                            {item.feature_requests.map((f, j) => <li key={j}>{f}</li>)}
                          </ul>
                        </div>
                      )}
                      {item.emotions?.length > 0 && (
                        <div>
                          <p className="text-gray-500 text-xs mb-1">Emotions</p>
                          <p className="text-gray-300">{item.emotions.join(", ")}</p>
                        </div>
                      )}
                      {item.subcategory && (
                        <div>
                          <p className="text-gray-500 text-xs mb-1">Subcategory</p>
                          <p className="text-gray-300">{item.subcategory}</p>
                        </div>
                      )}
                    </div>
                  </td>
                </tr>
              )}
            </>
          ))}
        </tbody>
      </table>
    </div>
  );
}
