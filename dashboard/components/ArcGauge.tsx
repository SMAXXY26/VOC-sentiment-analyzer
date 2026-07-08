"use client";

/**
 * Shared 240° speedometer arc gauge.
 *
 * Scalability: the SVG has only a viewBox (no fixed width/height), so it
 * adopts the container's width and derives height from the intrinsic
 * 100:74 aspect ratio. Arc geometry AND text all live in viewBox units,
 * so everything scales proportionally together — no absolutely-positioned
 * HTML overlay that can drift out of alignment. The width cap is fluid:
 * clamp(rem, %, rem) — percentage-driven, rem-bounded (no px).
 */

const R = 40;
const CX = 50;
const CY = 50;
const toRad = (d: number) => (d * Math.PI) / 180;

// Start = 210° (lower-left), end = 330° (lower-right), sweeping CW through top.
const SX = CX + R * Math.cos(toRad(210));
const SY = CY - R * Math.sin(toRad(210));
const EX = CX + R * Math.cos(toRad(330));
const EY = CY - R * Math.sin(toRad(330));
const ARC_LEN = (240 / 360) * 2 * Math.PI * R;
const TRACK_D = `M ${SX} ${SY} A ${R} ${R} 0 1 1 ${EX} ${EY}`;

export function ArcGauge({
  pct,
  color,
  value,
  caption,
  valueClassName = "text-slate-900 dark:text-white",
  maxWidth = "clamp(6rem, 70%, 8.5rem)",
  durationMs = 1000,
}: {
  pct: number;
  color: string;
  value: string;
  caption?: string;
  valueClassName?: string;
  maxWidth?: string;
  durationMs?: number;
}) {
  const fill = (Math.min(100, Math.max(0, pct)) / 100) * ARC_LEN;
  const twoLine = caption != null;

  return (
    // viewBox crops the dead space below the 240° opening but keeps 4 units
    // of headroom so the round caps (stroke 7 → 3.5 overhang) aren't clipped.
    <svg viewBox="0 0 100 74" preserveAspectRatio="xMidYMid meet" className="w-full" style={{ maxWidth }}>
      {/* Track */}
      <path d={TRACK_D} fill="none" stroke="rgba(148,163,184,0.20)" strokeWidth={7} strokeLinecap="round" />
      {/* Fill */}
      <path
        d={TRACK_D}
        fill="none"
        stroke={color}
        strokeWidth={7}
        strokeLinecap="round"
        strokeDasharray={ARC_LEN}
        strokeDashoffset={ARC_LEN - fill}
        style={{ transition: `stroke-dashoffset ${durationMs}ms cubic-bezier(0.16,1,0.3,1)` }}
      />
      {/* Value pinned to the arc center in viewBox units — scales with the gauge */}
      <text
        x={CX}
        y={twoLine ? 44 : CY}
        textAnchor="middle"
        dominantBaseline="central"
        fontSize={twoLine ? 12.5 : 17}
        fontWeight={700}
        className={valueClassName}
        style={{ fill: "currentColor" }}
      >
        {value}
      </text>
      {twoLine && (
        <text
          x={CX}
          y={58}
          textAnchor="middle"
          dominantBaseline="central"
          fontSize={8}
          className="text-slate-500"
          style={{ fill: "currentColor", fontVariantNumeric: "tabular-nums" }}
        >
          {caption}
        </text>
      )}
    </svg>
  );
}
