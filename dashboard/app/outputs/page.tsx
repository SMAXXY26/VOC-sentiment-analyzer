"use client";
import { useState, useEffect, useRef } from "react";
import useSWR from "swr";
import { fetchAnalyses, fetchSummary } from "@/lib/api";
import type { AnalysisItem, SearchFilters } from "@/lib/api";
import { SummaryCards } from "@/components/SummaryCards";
import { ExperienceGauges } from "@/components/ExperienceGauges";
import { SentimentChart, CategoryRadial } from "@/components/SentimentChart";
import { WordCloud } from "@/components/WordCloud";
import { DailyVolumeChart } from "@/components/DailyVolumeChart";
import { AnalysisTable } from "@/components/AnalysisTable";

const PAGE_SIZE = 20;

const SENTIMENTS = ["positive", "neutral", "negative", "mixed"];
const RISKS = ["low", "medium", "high", "critical"];

const selectCls =
  "glass rounded-lg px-2.5 py-1.5 text-xs text-slate-700 dark:text-slate-300 focus:outline-none focus:border-indigo-500/50 cursor-pointer";

function chipCls(active: boolean) {
  return `px-2.5 py-1.5 text-xs rounded-lg border transition-all cursor-pointer ${
    active
      ? "bg-indigo-500/20 text-indigo-600 dark:text-indigo-300 border-indigo-500/40"
      : "glass text-slate-600 dark:text-slate-400 border-transparent hover:text-slate-800 dark:hover:text-slate-200"
  }`;
}

function SearchBar({ query, onQuery, onSearch, onClear, filters, onFilters, categories }: {
  query: string;
  onQuery: (v: string) => void;
  onSearch: () => void;
  onClear: () => void;
  filters: SearchFilters;
  onFilters: (f: SearchFilters) => void;
  categories: string[];
}) {
  const set = (k: keyof SearchFilters, v: string | boolean | undefined) =>
    onFilters({ ...filters, [k]: v === "" || v === false ? undefined : v });
  const activeCount = Object.values(filters).filter((v) => v !== undefined && v !== "" && v !== false).length;

  return (
    <div className="flex flex-col gap-2">
      <div className="flex gap-2">
        <div className="relative flex-1">
          <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400 dark:text-slate-600 pointer-events-none"
            fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="m21 21-5.197-5.197m0 0A7.5 7.5 0 1 0 5.196 5.196a7.5 7.5 0 0 0 10.607 10.607Z" />
          </svg>
          <input
            type="text" value={query}
            onChange={e => onQuery(e.target.value)}
            onKeyDown={e => e.key === "Enter" && onSearch()}
            placeholder="Semantic search…"
            className="w-full glass rounded-xl pl-9 pr-4 py-2 text-sm text-slate-800 dark:text-slate-200 placeholder-slate-600 focus:outline-none focus:border-indigo-500/50 transition-colors"
          />
        </div>
        <button onClick={onSearch} className="px-4 py-2 bg-indigo-500/20 hover:bg-indigo-500/30 text-indigo-600 dark:text-indigo-300 text-sm font-medium rounded-xl border border-indigo-500/25 transition-all cursor-pointer">
          Search
        </button>
        {(query || activeCount > 0) && (
          <button onClick={onClear} className="px-3 py-2 glass hover:bg-slate-900/[0.06] dark:hover:bg-white/[0.06] text-slate-600 dark:text-slate-400 hover:text-slate-800 dark:hover:text-slate-200 text-sm rounded-xl transition-all cursor-pointer">
            ✕
          </button>
        )}
      </div>

      {/* Filters — applied live (no need to press Search) */}
      <div className="flex flex-wrap items-center gap-2">
        <select value={filters.sentiment ?? ""} onChange={e => set("sentiment", e.target.value)} className={selectCls}>
          <option value="">All sentiment</option>
          {SENTIMENTS.map(s => <option key={s} value={s}>{s}</option>)}
        </select>
        <select value={filters.risk_level ?? ""} onChange={e => set("risk_level", e.target.value)} className={selectCls}>
          <option value="">All risk</option>
          {RISKS.map(r => <option key={r} value={r}>{r}</option>)}
        </select>
        {categories.length > 0 && (
          <select value={filters.category ?? ""} onChange={e => set("category", e.target.value)} className={selectCls}>
            <option value="">All categories</option>
            {categories.map(c => <option key={c} value={c}>{c}</option>)}
          </select>
        )}
        <button onClick={() => set("escalate", !filters.escalate)} className={chipCls(!!filters.escalate)}>Escalated</button>
        <button onClick={() => set("churn_risk", !filters.churn_risk)} className={chipCls(!!filters.churn_risk)}>Churn risk</button>
        {activeCount > 0 && (
          <button onClick={() => onFilters({})} className="text-xs text-slate-500 hover:text-slate-700 dark:hover:text-slate-300 underline cursor-pointer ml-1">
            reset filters
          </button>
        )}
      </div>
    </div>
  );
}

export default function OutputsPage() {
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [filters, setFilters] = useState<SearchFilters>({});
  const [items, setItems] = useState<AnalysisItem[]>([]);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [initialLoaded, setInitialLoaded] = useState(false);
  // Tracks how many items are currently loaded so the periodic refresh can
  // re-fetch the same count instead of collapsing back to page 0 (which caused
  // a scroll jump + sentinel re-trigger loop = flicker).
  const loadedRef = useRef(PAGE_SIZE);

  const { data: summary } = useSWR("summary", fetchSummary, { refreshInterval: 30000 });
  const categories = Object.keys(summary?.top_categories ?? {});

  // Initial load + search + filters — always resets to page 0.
  // Load more is disabled for search queries (backend vector search has no offset).
  // No refreshInterval here: silent refresh is handled separately below so it
  // doesn't clobber loaded pages mid-scroll.
  useSWR(["analyses", search, filters], async () => {
    const res = await fetchAnalyses(PAGE_SIZE, search || undefined, filters, 0);
    setItems(res.items);
    setOffset(res.items.length);
    loadedRef.current = res.items.length;
    setHasMore(!search && res.items.length === PAGE_SIZE);
    setInitialLoaded(true);
    return res;
  }, { revalidateOnFocus: false });

  // Silent 30s refresh that preserves how many items are loaded — re-fetches the
  // current count at offset 0 so the list updates in place with no jump/flicker.
  // Disabled while a search query is active (vector search isn't paginated).
  useEffect(() => {
    if (search) return;
    const id = setInterval(async () => {
      const want = Math.max(loadedRef.current, PAGE_SIZE);
      try {
        const res = await fetchAnalyses(want, undefined, filters, 0);
        setItems(res.items);
        setOffset(res.items.length);
        loadedRef.current = res.items.length;
        setHasMore(res.items.length === want);
      } catch {
        // ignore — next tick retries
      }
    }, 30000);
    return () => clearInterval(id);
  }, [search, filters]);

  async function loadMore() {
    if (loadingMore || !hasMore) return;
    setLoadingMore(true);
    try {
      const res = await fetchAnalyses(PAGE_SIZE, undefined, filters, offset);
      setItems(prev => [...prev, ...res.items]);
      setOffset(prev => prev + res.items.length);
      loadedRef.current += res.items.length;
      setHasMore(res.items.length === PAGE_SIZE);
    } catch {
      // silently ignore — user can scroll again to retry
    } finally {
      setLoadingMore(false);
    }
  }

  return (
    <div className="flex flex-col lg:flex-row gap-4 lg:h-full w-full max-w-[1800px] mx-auto animate-fade-in">
      {/* LEFT — feedback list (panel scrolls on lg+, page scrolls below that) */}
      <div className="w-full lg:w-[42%] lg:min-w-[380px] xl:max-w-[600px] h-[65vh] lg:h-auto flex flex-col rounded-2xl glass overflow-hidden shrink-0">
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-slate-200/70 dark:border-white/[0.05] shrink-0">
          <p className="text-[10px] font-mono uppercase tracking-[0.2em] text-slate-500">Feedback Items</p>
          {initialLoaded && (
            <p className="text-[11px] text-slate-400 dark:text-slate-600">{items.length} loaded</p>
          )}
        </div>
        <div className="p-4 shrink-0 border-b border-slate-200/70 dark:border-white/[0.05]">
          <SearchBar
            query={query}
            onQuery={setQuery}
            onSearch={() => setSearch(query)}
            onClear={() => { setQuery(""); setSearch(""); setFilters({}); }}
            filters={filters}
            onFilters={setFilters}
            categories={categories}
          />
        </div>
        <div className="flex-1 overflow-y-auto p-4">
          <AnalysisTable
            items={items}
            onLoadMore={loadMore}
            hasMore={hasMore}
            loadingMore={loadingMore}
          />
        </div>
      </div>

      {/* RIGHT — all stats (panel scrolls on lg+, page scrolls below that) */}
      <div className="flex-1 min-w-0 lg:overflow-y-auto lg:pr-1 space-y-4">
        {/* Header */}
        <div className="flex items-center justify-between py-2">
          <div>
            <h1 className="text-lg font-semibold text-slate-900 dark:text-white tracking-tight">Analyzer Outputs</h1>
            <p className="text-[11px] text-slate-500 mt-0.5 font-mono">semantic pipeline results · 30s refresh</p>
          </div>
          {summary && (
            <div className="text-right">
              <p className="text-3xl font-bold text-indigo-600 dark:text-indigo-300 tabular-nums">{summary.total}</p>
              <p className="text-[10px] text-slate-500 font-mono uppercase tracking-wider">total items</p>
            </div>
          )}
        </div>

        {/* Top Feature Requests — surfaced at the top as the primary signal */}
        {summary && (
          <div className="rounded-2xl glass p-5 border-indigo-500/25 dark:border-indigo-500/20 bg-gradient-to-br from-indigo-500/[0.06] to-transparent">
            <div className="flex items-center justify-between mb-4">
              <p className="text-[10px] font-mono uppercase tracking-[0.2em] text-indigo-600 dark:text-indigo-300">Top Feature Requests</p>
              <span className="text-[10px] text-slate-500 font-mono">{summary.top_feature_requests?.length ?? 0} unique</span>
            </div>
            {summary.top_feature_requests?.length ? (
              <ol className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-2.5">
                {summary.top_feature_requests.slice(0, 8).map((f, i) => (
                  <li key={i} className="flex gap-3 items-start">
                    <span className="text-[9px] font-mono text-indigo-500/70 mt-0.5 w-5 shrink-0 tabular-nums">{String(i + 1).padStart(2, "0")}</span>
                    <span className="text-xs text-slate-700 dark:text-slate-300 leading-relaxed">{f}</span>
                  </li>
                ))}
              </ol>
            ) : <p className="text-slate-400 dark:text-slate-600 text-xs">No feature requests surfaced yet.</p>}
          </div>
        )}

        {/* Stat cards */}
        {summary && <SummaryCards data={summary} />}

        {/* Experience indices — CSI + CX Index gauges */}
        {summary && <ExperienceGauges data={summary} />}

        {/* Bento row 2 — asymmetric: donut (5) + categories (7) */}
        <div className="grid grid-cols-12 gap-3">
          <div className="col-span-12 xl:col-span-5 rounded-2xl glass p-5">
            {summary
              ? <SentimentChart distribution={summary.sentiment_distribution} />
              : <div className="h-40 flex items-center justify-center"><div className="w-5 h-5 border-2 border-indigo-500/30 border-t-indigo-400 rounded-full animate-spin" /></div>
            }
          </div>
          <div className="col-span-12 xl:col-span-7 rounded-2xl glass p-5">
            {summary && <CategoryRadial categories={summary.top_categories} />}
          </div>
        </div>

        {/* Daily volume bar chart */}
        <div className="rounded-2xl glass p-5">
          <p className="text-[10px] font-mono uppercase tracking-[0.2em] text-slate-500 mb-4">Feedback Volume by Day</p>
          {summary && <DailyVolumeChart counts={summary.daily_counts} />}
        </div>

        {/* Feature-request word cloud */}
        <div className="rounded-2xl glass p-5">
          <p className="text-[10px] font-mono uppercase tracking-[0.2em] text-slate-500 mb-4">Most-Used Words</p>
          {summary && <WordCloud counts={summary.word_frequencies} />}
        </div>

      </div>
    </div>
  );
}
