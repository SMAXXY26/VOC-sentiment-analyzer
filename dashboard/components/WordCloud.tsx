"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import cloud from "d3-cloud";

/**
 * Word cloud using d3-cloud (jasondavies/d3-cloud) for spiral layout.
 * Word size scales with frequency; placement and rotation are made deterministic
 * (seeded PRNG + hashed rotation) so the cloud doesn't reshuffle on the 30s refresh.
 */

type Placed = { text: string; size: number; x: number; y: number; rotate: number; count: number };

// Stable hash → deterministic rotation per word.
function hash(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
  return Math.abs(h);
}

// Seeded PRNG (mulberry32) so d3-cloud's spiral placement is deterministic.
function mulberry32(seed: number): () => number {
  return () => {
    seed |= 0;
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), seed | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const HUES = ["#6366f1", "#7c6cf0", "#8b5cf6", "#a855f7", "#c084fc"];
const FONT = "Inter, ui-sans-serif, system-ui, sans-serif";
const HEIGHT = 260;

export function WordCloud({ counts }: { counts?: Record<string, number> }) {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  const [placed, setPlaced] = useState<Placed[]>([]);

  const entries = useMemo(
    () =>
      Object.entries(counts ?? {})
        .sort((a, b) => b[1] - a[1])
        .slice(0, 35),
    [counts],
  );

  // Re-run layout once webfonts load — measuring with the fallback font
  // produces boxes that don't match the final Inter rendering.
  const [fontsReady, setFontsReady] = useState(false);
  useEffect(() => {
    let mounted = true;
    document.fonts?.ready.then(() => {
      if (mounted) setFontsReady(true);
    });
    return () => {
      mounted = false;
    };
  }, []);

  // Inject an opacity-only @keyframes for the word cloud.
  // The global Tailwind `fadeIn` keyframe includes `transform: translateY()`
  // which overwrites d3-cloud's per-word translate/rotate positioning,
  // collapsing every word to the vertical center.
  useEffect(() => {
    if (document.getElementById("wc-fade")) return;
    const style = document.createElement("style");
    style.id = "wc-fade";
    style.textContent = `
      @keyframes wcFadeIn {
        from { opacity: 0; }
        to   { opacity: 1; }
      }
    `;
    document.head.appendChild(style);
  }, []);

  // Track container width responsively — read immediately on mount to avoid blank flash.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    // Seed width immediately from the DOM so layout starts on first render.
    const initial = Math.floor(el.getBoundingClientRect().width);
    if (initial > 0) setWidth(initial);

    const ro = new ResizeObserver(([e]) => setWidth(Math.floor(e.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Run the d3-cloud layout whenever the data or width changes.
  useEffect(() => {
    if (!width || !entries.length) {
      setPlaced([]);
      return;
    }
    const max = entries[0][1];
    const min = entries[entries.length - 1][1];
    const span = Math.max(1, max - min);
    // sqrt scale dampens huge outliers; 13px → 54px.
    const fontFor = (c: number) => 13 + Math.sqrt((c - min) / span) * 41;

    let cancelled = false;
    const layout = cloud<cloud.Word & { count: number }>()
      .size([width, HEIGHT])
      .words(entries.map(([text, count]) => ({ text, count, size: fontFor(count) })))
      .padding(3)
      .rotate((d) => {
        const r = hash(d.text ?? "") % 5; // mostly horizontal, some vertical
        return r < 3 ? 0 : r === 3 ? 90 : -90;
      })
      .font(FONT)
      // Must match the rendered fontWeight (600) — measuring at normal
      // weight yields boxes narrower than the bold text, causing overlap.
      .fontWeight(600)
      .fontSize((d) => d.size ?? 14)
      .random(mulberry32(42))
      .on("end", (words) => {
        if (cancelled) return;
        setPlaced(
          words.map((w) => ({
            text: w.text ?? "",
            size: w.size ?? 14,
            x: w.x ?? 0,
            y: w.y ?? 0,
            rotate: w.rotate ?? 0,
            count: (w as cloud.Word & { count: number }).count,
          })),
        );
      });
    layout.start();
    return () => {
      cancelled = true;
      layout.stop();
    };
  }, [entries, width, fontsReady]);

  if (!entries.length) {
    return (
      <div className="h-full flex flex-col items-center justify-center py-8 text-center">
        <p className="text-slate-400 dark:text-slate-600 text-sm">No words yet</p>
        <p className="text-slate-400/70 dark:text-slate-700 text-xs mt-1">Run the pipeline to populate</p>
      </div>
    );
  }

  const max = entries[0][1];
  const min = entries[entries.length - 1][1];
  const span = Math.max(1, max - min);
  const colorFor = (c: number) => HUES[Math.min(HUES.length - 1, Math.round(((c - min) / span) * (HUES.length - 1)))];

  return (
    <div ref={ref} className="w-full" style={{ height: HEIGHT }}>
      {width > 0 && placed.length > 0 && (
        // d3-cloud positions each word relative to the canvas center,
        // so the <g> must be translated to (width/2, height/2).
        <svg width={width} height={HEIGHT} className="overflow-visible">
          <g transform={`translate(${width / 2},${HEIGHT / 2})`}>
            {placed.map((w, i) => (
              <text
                key={`${w.text}-${i}`}
                // No dominantBaseline here: d3-cloud's collision boxes assume the
                // default alphabetic baseline at (x, y). Overriding the baseline
                // (e.g. "central") shifts words out of their measured boxes → overlap.
                textAnchor="middle"
                transform={`translate(${w.x},${w.y}) rotate(${w.rotate})`}
                style={{
                  fontSize: w.size,
                  fontFamily: FONT,
                  fontWeight: 600,
                  fill: colorFor(w.count),
                  opacity: 0,
                  animation: `wcFadeIn 0.35s ease-out ${Math.min(i, 40) * 20}ms forwards`,
                  cursor: "default",
                }}
              >
                <title>{`${w.text} — ${w.count}×`}</title>
                {w.text}
              </text>
            ))}
          </g>
        </svg>
      )}
    </div>
  );
}
