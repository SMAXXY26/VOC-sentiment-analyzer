"use client";
import { useState } from "react";
import { analyzeText, AnalysisItem } from "@/lib/api";
import { SentimentBadge } from "@/components/SentimentBadge";
import { RiskBadge } from "@/components/RiskBadge";

export default function AnalyzePage() {
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<AnalysisItem | null>(null);
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
    <div className="max-w-3xl mx-auto">
      <h1 className="text-xl font-semibold text-white mb-6">Analyze Feedback</h1>

      <div className="bg-gray-900 rounded-xl border border-gray-800 p-6 mb-6">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Paste customer feedback here…"
          rows={6}
          className="w-full bg-gray-950 border border-gray-700 rounded-lg px-4 py-3 text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-indigo-500 resize-none"
        />
        <div className="flex items-center justify-between mt-4">
          <span className="text-xs text-gray-600">{text.length} chars</span>
          <button
            onClick={handleSubmit}
            disabled={loading || !text.trim()}
            className="px-6 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-medium rounded-lg transition-colors"
          >
            {loading ? "Analyzing…" : "Analyze"}
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-red-950 border border-red-800 rounded-xl p-4 text-red-300 text-sm mb-6">
          {error}
        </div>
      )}

      {result && (
        <div className="bg-gray-900 rounded-xl border border-gray-800 p-6 space-y-5">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-xs text-gray-500 mb-1">Summary</p>
              <p className="text-gray-200 text-sm leading-relaxed">{result.summary}</p>
            </div>
            <div className="flex flex-col items-end gap-2 shrink-0">
              <SentimentBadge sentiment={result.sentiment} />
              <RiskBadge level={result.risk_level} />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <Stat label="Category" value={[result.category, result.subcategory].filter(Boolean).join(" › ")} />
            <Stat label="Intensity Score" value={`${result.intensity} / 10`} highlight />
            <Stat label="Escalate" value={result.escalate ? "Yes" : "No"} warn={result.escalate} />
            <Stat label="Churn Risk" value={result.churn_risk ? "Yes" : "No"} warn={result.churn_risk} />
          </div>

          {result.emotions?.length > 0 && (
            <div>
              <p className="text-xs text-gray-500 mb-2">Emotions Detected</p>
              <div className="flex flex-wrap gap-2">
                {result.emotions.map((e) => (
                  <span key={e} className="bg-gray-800 text-gray-300 text-xs px-2.5 py-1 rounded-full">{e}</span>
                ))}
              </div>
            </div>
          )}

          {result.feature_requests?.length > 0 && (
            <div>
              <p className="text-xs text-gray-500 mb-2">Feature Requests</p>
              <ul className="space-y-1">
                {result.feature_requests.map((f, i) => (
                  <li key={i} className="text-sm text-gray-300 flex gap-2">
                    <span className="text-indigo-500 font-mono text-xs mt-0.5">{i + 1}.</span>{f}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function Stat({ label, value, highlight, warn }: { label: string; value: string; highlight?: boolean; warn?: boolean }) {
  return (
    <div className="bg-gray-950 rounded-lg px-4 py-3">
      <p className="text-xs text-gray-500 mb-0.5">{label}</p>
      <p className={`text-sm font-medium ${highlight ? "text-indigo-400" : warn ? "text-red-400" : "text-gray-200"}`}>
        {value}
      </p>
    </div>
  );
}
