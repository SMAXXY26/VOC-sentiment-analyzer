"use client";
import { useEffect, useMemo, useRef, useState } from "react";

const HUES = ["#6366f1", "#7c6cf0", "#8b5cf6", "#a855f7", "#c084fc", "#38bdf8", "#34d399"];
const HEIGHT = 260;
const PAD = 4;
const FONT = "Inter, ui-sans-serif, system-ui, sans-serif";

function hash(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
  return Math.abs(h);
}

type Box = { x1: number; y1: number; x2: number; y2: number };
type Placed = { text: string; size: number; weight: number; x: number; y: number; rotate: number; color: string; count: number };

function overlaps(a: Box, boxes: Box[]): boolean {
  for (const b of boxes) {
    if (a.x1 < b.x2 && a.x2 > b.x1 && a.y1 < b.y2 && a.y2 > b.y1) return true;
  }
  return false;
}

// Shared offscreen canvas for accurate text measurement (browser only).
let measureCtx: CanvasRenderingContext2D | null = null;
function measure(text: string, size: number, weight: number): number {
  if (typeof document === "undefined") return text.length * size * 0.55;
  if (!measureCtx) measureCtx = document.createElement("canvas").getContext("2d");
  if (!measureCtx) return text.length * size * 0.55;
  measureCtx.font = `${weight} ${size}px ${FONT}`;
  return measureCtx.measureText(text).width;
}

function layout(entries: [string, number][], w: number, h: number): Placed[] {
  if (!w || !h || !entries.length) return [];

  const max = entries[0][1];
  const min = entries[entries.length - 1][1];
  const span = Math.max(1, max - min);
  const sizeOf = (c: number) => 12 + Math.sqrt((c - min) / span) * 30; // 12 → 42px

  const placed: Placed[] = [];
  const boxes: Box[] = [];
  const cx = w / 2;
  const cy = h / 2;
  // Aspect-corrected spiral so it spreads across the (wide) container instead
  // of piling up where the circular spiral first clears the short axis.
  const aspect = w / h;

  for (const [text, count] of entries) {
    const size = sizeOf(count);
    const weight = size > 30 ? 700 : size > 20 ? 600 : 500;
    const rIdx = hash(text) % 5;
    const rotate = rIdx < 3 ? 0 : rIdx === 3 ? 90 : -90;

    // Real measured glyph box (+small padding). Height ≈ cap+descender ≈ size.
    const textW = measure(text, size, weight) + PAD;
    const textH = size + PAD;
    const bw = rotate === 0 ? textW : textH;
    const bh = rotate === 0 ? textH : textW;

    // Skip words that simply can't fit on either axis.
    if (bw > w || bh > h) continue;

    let found = false;
    // Archimedean spiral, x stretched by aspect ratio.
    for (let t = 0; t < 2500 && !found; t++) {
      const angle = 0.5 * t * (Math.PI / 12);   // ~24 samples per turn
      const radius = 1.6 * angle;                // tight Archimedean growth
      const px = cx + radius * aspect * Math.cos(angle);
      const py = cy + radius * Math.sin(angle);

      const box: Box = {
        x1: px - bw / 2 - PAD, y1: py - bh / 2 - PAD,
        x2: px + bw / 2 + PAD, y2: py + bh / 2 + PAD,
      };
      // Stay inside the canvas.
      if (box.x1 < 0 || box.x2 > w || box.y1 < 0 || box.y2 > h) continue;
      if (overlaps(box, boxes)) continue;

      boxes.push(box);
      placed.push({ text, size, weight, x: px, y: py, rotate, color: HUES[hash(text) % HUES.length], count });
      found = true;
    }
  }

  return placed;
}

export function WordCloud({ counts }: { counts?: Record<string, number> }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);

  const entries = useMemo(
    () => Object.entries(counts ?? {}).sort((a, b) => b[1] - a[1]).slice(0, 50),
    [counts],
  );

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setWidth(Math.floor(e.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const placed = useMemo(() => layout(entries, width, HEIGHT), [entries, width]);

  if (!entries.length) {
    return (
      <div className="h-full flex flex-col items-center justify-center py-8 text-center">
        <p className="text-slate-400 dark:text-slate-600 text-sm">No words yet</p>
        <p className="text-slate-400/70 dark:text-slate-700 text-xs mt-1">Run the pipeline to populate</p>
      </div>
    );
  }

  return (
    <div ref={containerRef} className="w-full" style={{ height: HEIGHT }}>
      {width > 0 && placed.length > 0 && (
        <svg width={width} height={HEIGHT}>
          {placed.map((w, i) => (
            <text
              key={w.text}
              textAnchor="middle"
              dominantBaseline="central"
              transform={`translate(${w.x},${w.y}) rotate(${w.rotate})`}
              style={{
                fontSize: w.size,
                fontFamily: FONT,
                fontWeight: w.weight,
                fill: w.color,
                opacity: 0,
                animation: `fadeIn 0.35s ease-out ${Math.min(i, 40) * 20}ms forwards`,
                cursor: "default",
              }}
            >
              <title>{`${w.text} — ${w.count}×`}</title>
              {w.text}
            </text>
          ))}
        </svg>
      )}
    </div>
  );
}
