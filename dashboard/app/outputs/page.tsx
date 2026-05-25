"use client";
import { useState } from "react";
import useSWR from "swr";
import { fetchAnalyses, fetchSummary } from "@/lib/api";
import { SummaryCards } from "@/components/SummaryCards";
import { SentimentChart } from "@/components/SentimentChart";
import { AnalysisTable } from "@/components/AnalysisTable";

export default function OutputsPage() {
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");

  const { data: summary } = useSWR("summary", fetchSummary, { refreshInterval: 30000 });
  const { data: analyses, isLoading } = useSWR(
    ["analyses", search],
    () => fetchAnalyses(50, search || undefined),
    { refreshInterval: 30000 }
  );

  return (
    <div className="max-w-7xl mx-auto">
      <h1 className="text-xl font-semibold text-white mb-6">Analyzer Outputs</h1>

      {summary && <SummaryCards data={summary} />}

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
        <div className="md:col-span-2">
          {summary && <SentimentChart distribution={summary.sentiment_distribution} />}
        </div>
        <div className="bg-gray-900 rounded-xl border border-gray-800 p-4">
          <p className="text-xs text-gray-500 mb-3">Top Feature Requests</p>
          {summary?.top_feature_requests?.length ? (
            <ul className="space-y-1.5">
              {summary.top_feature_requests.map((f, i) => (
                <li key={i} className="text-sm text-gray-300 flex gap-2">
                  <span className="text-indigo-500 font-mono text-xs mt-0.5">{i + 1}.</span> {f}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-gray-600 text-sm">None yet.</p>
          )}
        </div>
      </div>

      <div className="flex gap-2 mb-4">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && setSearch(query)}
          placeholder="Semantic search… (press Enter)"
          className="flex-1 bg-gray-900 border border-gray-700 rounded-lg px-4 py-2 text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-indigo-500"
        />
        <button
          onClick={() => { setSearch(query); }}
          className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white text-sm rounded-lg transition-colors"
        >
          Search
        </button>
        {search && (
          <button
            onClick={() => { setQuery(""); setSearch(""); }}
            className="px-4 py-2 bg-gray-800 hover:bg-gray-700 text-gray-300 text-sm rounded-lg transition-colors"
          >
            Clear
          </button>
        )}
      </div>

      {isLoading ? (
        <p className="text-gray-500 text-sm text-center py-12">Loading…</p>
      ) : (
        <AnalysisTable items={analyses?.items ?? []} />
      )}
    </div>
  );
}
