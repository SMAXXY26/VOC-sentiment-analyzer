"use client";
import { useState } from "react";
import { analyzeText, FeedbackAnalysis } from "@/lib/api";
import { SentimentBadge } from "@/components/SentimentBadge";
import { RiskBadge } from "@/components/RiskBadge";

function ResultCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="glass rounded-2xl p-5 glass-hover animate-fade-in">
      <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-3">{title}</p>
      {children}
    </div>
  );
}

function ScoreChip({ label, value, variant = "default" }: {
  label: string;
  value: string;
  variant?: "default" | "warn" | "accent";
}) {
  const colors = {
    default: "text-slate-800 dark:text-slate-200 border-slate-200/70 dark:border-white/[0.08] bg-slate-900/[0.03] dark:bg-white/[0.03]",
    warn: "text-red-600 dark:text-red-300 border-red-500/20 bg-red-500/[0.08]",
    accent: "text-indigo-600 dark:text-indigo-300 border-indigo-500/20 bg-indigo-500/[0.08]",
  };
  return (
    <div className={`rounded-xl border px-4 py-3 ${colors[variant]}`}>
      <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">{label}</p>
      <p className="text-sm font-semibold">{value}</p>
    </div>
  );
}

function HealthOrb({ score }: { score: number }) {
  const color = score >= 7 ? "#34d399" : score >= 4 ? "#fbbf24" : "#f87171";
  const label = score >= 7 ? "Healthy" : score >= 4 ? "Moderate" : "At Risk";
  return (
    <div className="flex items-center gap-4">
      <div
        className="relative w-16 h-16 rounded-full flex items-center justify-center"
        style={{ boxShadow: `0 0 24px ${color}40, inset 0 0 12px ${color}20`, background: `${color}15`, border: `1px solid ${color}30` }}
      >
        <span className="text-lg font-bold" style={{ color }}>{score}</span>
      </div>
      <div>
        <p className="text-sm font-semibold text-slate-800 dark:text-slate-200">{label}</p>
        <p className="text-xs text-slate-500">Health Score / 10</p>
      </div>
    </div>
  );
}

export default function AnalyzePage() {
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<FeedbackAnalysis | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit() {
    if (!text.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const data = await analyzeText(text.trim());
      setResult(data);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="max-w-3xl mx-auto space-y-4 animate-fade-in">
      {/* Header */}
      <div className="py-2">
        <h1 className="text-lg font-semibold text-slate-900 dark:text-white tracking-tight">Analyze Feedback</h1>
        <p className="text-xs text-slate-500 mt-0.5">Run the 10-stage LLM pipeline on any customer feedback</p>
      </div>

      {/* Input card */}
      <div className="glass rounded-2xl p-5">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Paste customer feedback here…"
          rows={5}
          className="w-full bg-slate-900/[0.03] dark:bg-white/[0.03] border border-slate-200/70 dark:border-white/[0.08] rounded-xl px-4 py-3 text-sm text-slate-800 dark:text-slate-200 placeholder-slate-600 focus:outline-none focus:border-indigo-500/40 resize-none transition-colors font-sans"
        />
        <div className="flex items-center justify-between mt-3">
          <span className="text-xs text-slate-400 dark:text-slate-600 tabular-nums">{text.length} chars</span>
          <button
            onClick={handleSubmit}
            disabled={loading || !text.trim()}
            className="flex items-center gap-2 px-5 py-2 bg-indigo-500/20 hover:bg-indigo-500/30 disabled:opacity-40 disabled:cursor-not-allowed text-indigo-600 dark:text-indigo-300 text-sm font-medium rounded-xl border border-indigo-500/25 transition-all duration-200 cursor-pointer"
          >
            {loading ? (
              <>
                <span className="w-3.5 h-3.5 border-2 border-indigo-400/30 border-t-indigo-300 rounded-full animate-spin" />
                Analyzing…
              </>
            ) : (
              <>
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="m3.75 13.5 10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75z" />
                </svg>
                Analyze
              </>
            )}
          </button>
        </div>
      </div>

      {error && (
        <div className="rounded-2xl bg-red-500/[0.08] border border-red-500/20 p-4 text-red-600 dark:text-red-300 text-sm animate-fade-in">
          {error}
        </div>
      )}

      {result && (
        <div className="space-y-3 animate-fade-in">
          {/* Summary + badges */}
          <ResultCard title="Analysis Summary">
            <div className="flex items-start gap-4">
              <p className="text-slate-800 dark:text-slate-200 text-sm leading-relaxed flex-1">{result.enrichment.summary}</p>
              <div className="flex flex-col gap-2 shrink-0">
                <SentimentBadge value={result.sentiment.sentiment} />
                <RiskBadge value={result.risk.risk_level} />
              </div>
            </div>
          </ResultCard>

          {/* Score chips */}
          <div className="grid grid-cols-2 gap-3">
            <ScoreChip label="Category" value={[result.taxonomy.category, result.taxonomy.subcategory].filter(Boolean).join(" › ")} />
            <ScoreChip label="Intensity Score" value={`${result.sentiment.intensity} / 10`} variant="accent" />
            <ScoreChip label="Escalate" value={result.risk.escalate ? "Yes — Immediate Action" : "No"} variant={result.risk.escalate ? "warn" : "default"} />
            <ScoreChip label="Churn Risk" value={result.signals.churn_risk ? "High Risk" : "Low Risk"} variant={result.signals.churn_risk ? "warn" : "default"} />
          </div>

          {/* Executive + health */}
          <ResultCard title="Executive Intelligence">
            <HealthOrb score={result.executive.overall_health_score} />
            <p className="text-slate-700 dark:text-slate-300 text-sm leading-relaxed mt-4 mb-4">{result.executive.executive_summary}</p>
            {result.executive.key_action_items?.length > 0 && (
              <ul className="space-y-1.5">
                {result.executive.key_action_items.map((a, i) => (
                  <li key={i} className="flex gap-2.5 text-xs text-slate-600 dark:text-slate-400">
                    <span className="text-emerald-500 shrink-0 mt-0.5">→</span>{a}
                  </li>
                ))}
              </ul>
            )}
          </ResultCard>

          {/* Suggested action */}
          <div className="glass rounded-2xl p-4 border-l-2 border-indigo-500/40 glass-hover">
            <p className="text-[10px] uppercase tracking-widest text-slate-500 mb-1.5">Suggested Action</p>
            <p className="text-sm text-slate-700 dark:text-slate-300">{result.risk.suggested_action}</p>
          </div>

          {/* Emotions */}
          {result.sentiment.emotions?.length > 0 && (
            <ResultCard title="Emotions Detected">
              <div className="flex flex-wrap gap-1.5">
                {result.sentiment.emotions.map((e) => (
                  <span key={e} className="text-xs px-2.5 py-1 rounded-full bg-violet-500/10 text-violet-600 dark:text-violet-300 border border-violet-500/20">
                    {e}
                  </span>
                ))}
              </div>
            </ResultCard>
          )}

          {/* Feature requests */}
          {result.signals.feature_requests?.length > 0 && (
            <ResultCard title="Feature Requests">
              <ul className="space-y-1.5">
                {result.signals.feature_requests.map((f, i) => (
                  <li key={i} className="flex gap-2.5 text-xs text-slate-600 dark:text-slate-400">
                    <span className="text-indigo-500 font-mono shrink-0">{String(i + 1).padStart(2, "0")}.</span>{f}
                  </li>
                ))}
              </ul>
            </ResultCard>
          )}

          {/* Key topics */}
          {result.enrichment.key_topics?.length > 0 && (
            <ResultCard title="Key Topics">
              <div className="flex flex-wrap gap-1.5">
                {result.enrichment.key_topics.map((t) => (
                  <span key={t} className="text-xs px-2.5 py-1 rounded-full bg-cyan-500/10 text-cyan-300 border border-cyan-500/20">
                    {t}
                  </span>
                ))}
              </div>
            </ResultCard>
          )}
        </div>
      )}
    </div>
  );
}
