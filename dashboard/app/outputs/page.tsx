"use client";
import { useState } from "react";
import useSWR from "swr";
import { fetchAnalyses, fetchSummary } from "@/lib/api";
import type { AnalysisItem } from "@/lib/api";
import { SummaryCards } from "@/components/SummaryCards";
import { SentimentChart, CategoryRadial } from "@/components/SentimentChart";
import { AnalysisTable } from "@/components/AnalysisTable";

const PAGE_SIZE = 20;

function SearchBar({ query, onQuery, onSearch, onClear }: {
  query: string; onQuery: (v: string) => void; onSearch: () => void; onClear: () => void;
}) {
  return (
    <div className="flex gap-2">
      <div className="relative flex-1">
        <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-600 pointer-events-none"
          fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="m21 21-5.197-5.197m0 0A7.5 7.5 0 1 0 5.196 5.196a7.5 7.5 0 0 0 10.607 10.607Z" />
        </svg>
        <input
          type="text" value={query}
          onChange={e => onQuery(e.target.value)}
          onKeyDown={e => e.key === "Enter" && onSearch()}
          placeholder="Semantic search…"
          className="w-full glass rounded-xl pl-9 pr-4 py-2 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-indigo-500/50 transition-colors"
        />
      </div>
      <button onClick={onSearch} className="px-4 py-2 bg-indigo-500/20 hover:bg-indigo-500/30 text-indigo-300 text-sm font-medium rounded-xl border border-indigo-500/25 transition-all cursor-pointer">
        Search
      </button>
      {query && (
        <button onClick={onClear} className="px-3 py-2 glass hover:bg-white/[0.06] text-slate-400 hover:text-slate-200 text-sm rounded-xl transition-all cursor-pointer">
          ✕
        </button>
      )}
    </div>
  );
}

export default function OutputsPage() {
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [items, setItems] = useState<AnalysisItem[]>([]);
  const [initialLoaded, setInitialLoaded] = useState(false);

  const { data: summary } = useSWR("summary", fetchSummary, { refreshInterval: 30000 });

  // Initial load + search
  useSWR(["analyses", search], async () => {
    const res = await fetchAnalyses(PAGE_SIZE, search || undefined);
    setItems(res.items);
    setInitialLoaded(true);
    return res;
  }, { refreshInterval: 30000 });

  return (
    <div className="h-full flex gap-4 animate-fade-in">
      {/* LEFT — feedback list (panel scrolls, not the page) */}
      <div className="w-[44%] min-w-[400px] flex flex-col rounded-2xl bg-white/[0.02] border border-white/[0.07] overflow-hidden">
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-white/[0.05] shrink-0">
          <p className="text-[10px] font-mono uppercase tracking-[0.2em] text-slate-500">Feedback Items</p>
          {initialLoaded && (
            <p className="text-[11px] text-slate-600">{items.length} loaded</p>
          )}
        </div>
        <div className="p-4 shrink-0 border-b border-white/[0.05]">
          <SearchBar
            query={query}
            onQuery={setQuery}
            onSearch={() => setSearch(query)}
            onClear={() => { setQuery(""); setSearch(""); }}
          />
        </div>
        <div className="flex-1 overflow-y-auto p-4">
          <AnalysisTable items={items} />
        </div>
      </div>

      {/* RIGHT — all stats (panel scrolls, not the page) */}
      <div className="flex-1 min-w-0 overflow-y-auto pr-1 space-y-4">
        {/* Header */}
        <div className="flex items-center justify-between py-2">
          <div>
            <h1 className="text-lg font-semibold text-white tracking-tight">Analyzer Outputs</h1>
            <p className="text-[11px] text-slate-500 mt-0.5 font-mono">semantic pipeline results · 30s refresh</p>
          </div>
          {summary && (
            <div className="text-right">
              <p className="text-3xl font-bold text-indigo-300 tabular-nums">{summary.total}</p>
              <p className="text-[10px] text-slate-500 font-mono uppercase tracking-wider">total items</p>
            </div>
          )}
        </div>

        {/* Stat cards */}
        {summary && <SummaryCards data={summary} />}

        {/* Bento row 2 — asymmetric: donut (5) + categories (7) */}
        <div className="grid grid-cols-12 gap-3">
          <div className="col-span-12 xl:col-span-5 rounded-2xl bg-white/[0.03] border border-white/[0.07] p-5">
            {summary
              ? <SentimentChart distribution={summary.sentiment_distribution} />
              : <div className="h-40 flex items-center justify-center"><div className="w-5 h-5 border-2 border-indigo-500/30 border-t-indigo-400 rounded-full animate-spin" /></div>
            }
          </div>
          <div className="col-span-12 xl:col-span-7 rounded-2xl bg-white/[0.03] border border-white/[0.07] p-5">
            {summary && <CategoryRadial categories={summary.top_categories} />}
          </div>
        </div>

        {/* Bento row 3 — feature requests (5) + rate stats (7) */}
        <div className="grid grid-cols-12 gap-3">
          <div className="col-span-12 md:col-span-5 rounded-2xl bg-white/[0.03] border border-white/[0.07] p-5">
            <p className="text-[10px] font-mono uppercase tracking-[0.2em] text-slate-500 mb-4">Top Feature Requests</p>
            {summary?.top_feature_requests?.length ? (
              <ul className="space-y-2.5">
                {summary.top_feature_requests.slice(0, 6).map((f, i) => (
                  <li key={i} className="flex gap-3 items-start">
                    <span className="text-[9px] font-mono text-indigo-500/60 mt-0.5 w-5 shrink-0 tabular-nums">{String(i + 1).padStart(2, "0")}</span>
                    <span className="text-xs text-slate-300 leading-relaxed">{f}</span>
                  </li>
                ))}
              </ul>
            ) : <p className="text-slate-600 text-xs">None yet.</p>}
          </div>

          <div className="col-span-12 md:col-span-7 grid grid-cols-2 gap-3">
            {summary && [
              {
                label: "Escalation Rate",
                value: summary.total ? `${Math.round((summary.escalation_count / summary.total) * 100)}%` : "—",
                sub: `${summary.escalation_count} items flagged`,
                color: "text-red-300",
                from: "from-red-500/[0.08]",
              },
              {
                label: "Churn Rate",
                value: summary.total ? `${Math.round((summary.churn_count / summary.total) * 100)}%` : "—",
                sub: `${summary.churn_count} at risk`,
                color: "text-orange-300",
                from: "from-orange-500/[0.08]",
              },
            ].map((s) => (
              <div key={s.label} className={`rounded-2xl bg-gradient-to-br ${s.from} to-transparent border border-white/[0.07] p-5`}>
                <p className="text-[10px] font-mono uppercase tracking-[0.15em] text-slate-500 mb-3">{s.label}</p>
                <p className={`text-4xl font-bold ${s.color} tracking-tight tabular-nums`}>{s.value}</p>
                <p className="text-[11px] text-slate-600 mt-1.5">{s.sub}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
