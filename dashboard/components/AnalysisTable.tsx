"use client";
import { Fragment, useState, useEffect, useRef } from "react";
import type { AnalysisItem } from "@/lib/api";
import { SentimentBadge } from "./SentimentBadge";
import { RiskBadge } from "./RiskBadge";

function ConfidenceBar({ value }: { value?: number }) {
  if (value == null) return <span className="text-slate-300 dark:text-slate-700 text-[11px]">—</span>;
  const pct = Math.round(value * 100);
  const color = pct >= 80 ? "bg-emerald-400" : pct >= 65 ? "bg-amber-400" : "bg-red-400";
  return (
    <div className="flex items-center gap-2">
      <div className="w-14 h-1 rounded-full bg-slate-900/[0.05] dark:bg-white/[0.05] overflow-hidden">
        <div className={`h-full rounded-full ${color} transition-all`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-[11px] text-slate-500 tabular-nums">{pct}%</span>
    </div>
  );
}

function SkeletonRow() {
  return (
    <tr className="border-b border-slate-200/70 dark:border-white/[0.04]">
      {[220, 80, 60, 60, 70, 40, 50].map((w, i) => (
        <td key={i} className="px-4 py-3">
          <div className="h-3 rounded-full bg-slate-900/[0.04] dark:bg-white/[0.04] animate-pulse" style={{ width: w }} />
        </td>
      ))}
    </tr>
  );
}

interface Props {
  items: AnalysisItem[];
  onLoadMore?: () => void;
  hasMore?: boolean;
  loadingMore?: boolean;
}

export function AnalysisTable({ items, onLoadMore, hasMore = false, loadingMore = false }: Props) {
  const [expanded, setExpanded] = useState<number | null>(null);
  const sentinelRef = useRef<HTMLDivElement>(null);

  // Intersection Observer for infinite scroll
  useEffect(() => {
    if (!onLoadMore || !hasMore) return;
    const el = sentinelRef.current;
    if (!el) return;
    const observer = new IntersectionObserver(
      (entries) => { if (entries[0].isIntersecting) onLoadMore(); },
      { rootMargin: "200px" },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [onLoadMore, hasMore]);

  if (!items.length && !loadingMore) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-center">
        <div className="w-10 h-10 rounded-xl bg-slate-900/[0.03] dark:bg-white/[0.03] border border-slate-200/70 dark:border-white/[0.06] flex items-center justify-center mb-3">
          <svg className="w-5 h-5 text-slate-300 dark:text-slate-700" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M20.25 6.375c0 2.278-3.694 4.125-8.25 4.125S3.75 8.653 3.75 6.375m16.5 0c0-2.278-3.694-4.125-8.25-4.125S3.75 4.097 3.75 6.375m16.5 0v11.25c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125V6.375" />
          </svg>
        </div>
        <p className="text-slate-500 text-sm">No analyses yet</p>
        <p className="text-slate-400 dark:text-slate-600 text-xs mt-1">Run the pipeline to populate data</p>
      </div>
    );
  }

  return (
    <div>
      <div className="overflow-x-auto rounded-xl border border-slate-200/70 dark:border-white/[0.07]">
        <table className="w-full text-sm min-w-[700px]">
          <thead>
            <tr className="border-b border-slate-200/70 dark:border-white/[0.06]">
              {["Summary", "Category", "Sentiment", "Risk", "Confidence", "Churn", "Source"].map((h) => (
                <th key={h} className="px-4 py-2.5 text-left text-xs font-medium text-slate-500">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {items.map((item, i) => (
              <Fragment key={i}>
                <tr
                  onClick={() => setExpanded(expanded === i ? null : i)}
                  className={`border-b border-slate-200/70 dark:border-white/[0.03] cursor-pointer transition-all duration-150 animate-fade-in animate-fill-both ${
                    i % 2 === 1 ? "bg-slate-900/[0.01] dark:bg-white/[0.01]" : ""
                  } ${
                    expanded === i
                      ? "bg-slate-900/[0.04] dark:bg-white/[0.04] border-l-2 border-l-indigo-500/50"
                      : "hover:bg-slate-900/[0.025] dark:hover:bg-white/[0.025] hover:border-l-2 hover:border-l-indigo-500/30"
                  }`}
                  style={{ animationDelay: `${Math.min(i, 15) * 30}ms` }}
                >
                  <td className="px-4 py-2.5 max-w-[200px]">
                    <p className="truncate text-slate-800 dark:text-slate-200 text-xs">{item.summary}</p>
                  </td>
                  <td className="px-4 py-2.5">
                    <span className="text-xs text-slate-600 dark:text-slate-400">{item.category}</span>
                    {item.subcategory && <span className="text-[10px] text-slate-400 dark:text-slate-600 block">{item.subcategory}</span>}
                  </td>
                  <td className="px-4 py-2.5"><SentimentBadge value={item.sentiment} /></td>
                  <td className="px-4 py-2.5"><RiskBadge value={item.risk_level} /></td>
                  <td className="px-4 py-2.5">
                    <ConfidenceBar value={item.pipeline_confidence} />
                  </td>
                  <td className="px-4 py-2.5 text-center">
                    {item.churn_risk
                      ? <span className="text-[11px] font-medium text-orange-400">Yes</span>
                      : <span className="text-slate-300 dark:text-slate-700">—</span>}
                  </td>
                  <td className="px-4 py-2.5">
                    <span className="text-[10px] text-slate-400 dark:text-slate-600 font-mono">{item.source}</span>
                  </td>
                </tr>
                {expanded === i && (
                  <tr className="border-b border-slate-200/70 dark:border-white/[0.04]">
                    <td colSpan={7} className="px-5 py-4 bg-slate-900/[0.02] dark:bg-white/[0.02]">
                      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 animate-fade-in">
                        {item.raw_text && (
                          <div className="lg:col-span-2">
                            <p className="text-[10px] font-mono uppercase tracking-[0.15em] text-slate-400 dark:text-slate-600 mb-1.5">Raw Text</p>
                            <p className="text-slate-700 dark:text-slate-300 text-xs italic leading-relaxed border-l-2 border-indigo-500/30 pl-3">
                              &ldquo;{item.raw_text}&rdquo;
                            </p>
                          </div>
                        )}
                        {item.emotions?.length > 0 && (
                          <div>
                            <p className="text-[10px] font-mono uppercase tracking-[0.15em] text-slate-400 dark:text-slate-600 mb-1.5">Emotions</p>
                            <div className="flex flex-wrap gap-1">
                              {item.emotions.map((e) => (
                                <span key={e} className="text-[10px] px-2 py-0.5 rounded-full bg-violet-500/10 text-violet-400 border border-violet-500/20">{e}</span>
                              ))}
                            </div>
                          </div>
                        )}
                        {item.feature_requests?.length > 0 && (
                          <div>
                            <p className="text-[10px] font-mono uppercase tracking-[0.15em] text-slate-400 dark:text-slate-600 mb-1.5">Feature Requests</p>
                            <ul className="space-y-1">
                              {item.feature_requests.map((f, j) => (
                                <li key={j} className="flex gap-2 text-xs text-slate-600 dark:text-slate-400">
                                  <span className="text-indigo-500 shrink-0">›</span>{f}
                                </li>
                              ))}
                            </ul>
                          </div>
                        )}
                      </div>
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
            {loadingMore && [0, 1, 2].map((i) => <SkeletonRow key={`sk-${i}`} />)}
          </tbody>
        </table>
      </div>

      {/* Infinite scroll sentinel */}
      {hasMore && <div ref={sentinelRef} className="h-4" />}
      {!hasMore && items.length > 0 && (
        <p className="text-center text-[11px] text-slate-300 dark:text-slate-700 py-4">All {items.length} items loaded</p>
      )}
    </div>
  );
}
