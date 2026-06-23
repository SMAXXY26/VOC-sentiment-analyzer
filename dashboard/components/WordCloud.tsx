"use client";
import { useMemo } from "react";

/**
 * Lightweight word cloud — no external dependency. Renders feature-request
 * phrases as flex-wrapped chips whose font size and opacity scale with frequency.
 * Themed for both light and dark mode.
 */
export function WordCloud({ counts }: { counts: Record<string, number> | undefined }) {
  const entries = useMemo(() => {
    const list = Object.entries(counts ?? {});
    // Sort by frequency desc, then shuffle within the displayed set is unnecessary —
    // keep deterministic order so layout is stable across refreshes.
    return list.sort((a, b) => b[1] - a[1]).slice(0, 40);
  }, [counts]);

  if (!entries.length) {
    return (
      <div className="h-full flex flex-col items-center justify-center py-8 text-center">
        <p className="text-slate-400 dark:text-slate-600 text-sm">No feature requests yet</p>
        <p className="text-slate-400/70 dark:text-slate-700 text-xs mt-1">Run the pipeline to populate</p>
      </div>
    );
  }

  const max = Math.max(...entries.map(([, c]) => c));
  const min = Math.min(...entries.map(([, c]) => c));
  const span = Math.max(1, max - min);

  // Color ramp by relative frequency — indigo → violet for emphasis.
  const HUES = ["#6366f1", "#7c6cf0", "#8b5cf6", "#a855f7"];

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
      {entries.map(([word, count]) => {
        const t = (count - min) / span; // 0..1
        const size = 11 + t * 17; // 11px..28px
        const weight = t > 0.66 ? 700 : t > 0.33 ? 600 : 500;
        const opacity = 0.55 + t * 0.45;
        const color = HUES[Math.min(HUES.length - 1, Math.round(t * (HUES.length - 1)))];
        return (
          <span
            key={word}
            title={`${word} — ${count}×`}
            className="leading-none whitespace-nowrap transition-colors"
            style={{ fontSize: `${size}px`, fontWeight: weight, color, opacity }}
          >
            {word}
          </span>
        );
      })}
    </div>
  );
}
