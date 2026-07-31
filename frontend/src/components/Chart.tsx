import { useId, useMemo, useRef, useState } from "react";

/* Hand-rolled SVG charts. Two forms cover everything the dashboard plots:
 * a multi-series line for change-over-time, and a polarity bar for signed
 * per-strategy profit. Neither pulls in a charting library, so the bundle
 * stays self-contained and the container needs no CDN.
 *
 * Colour follows the entity, never its rank: a series keeps its slot when the
 * set is filtered. Categorical slots are the validated --series-N tokens, in
 * fixed order and never cycled; polarity uses --gain/--loss. */

export const SERIES_TOKENS = ["var(--series-1)", "var(--series-2)", "var(--series-3)"];

export type Series = {
  name: string;
  /** Fixed slot for this entity, so filtering never repaints the survivors. */
  slot: number;
  points: { x: string; y: number | null }[];
};

type LineChartProps = {
  series: Series[];
  height?: number;
  /** Formats the y axis and the tooltip. */
  formatY: (value: number) => string;
  /** Drawn as a dashed rule; the equity baseline, usually 100 or 0. */
  baseline?: number;
  title: string;
};

const PAD = { top: 12, right: 76, bottom: 26, left: 60 };

function niceTicks(min: number, max: number, count = 4): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max)) return [];
  if (min === max) return [min];
  const raw = (max - min) / count;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((s) => s >= raw) ?? magnitude * 10;
  const ticks: number[] = [];
  for (let t = Math.ceil(min / step) * step; t <= max + step / 1000; t += step) ticks.push(t);
  return ticks;
}

/** Push overlapping end-of-line labels apart, keeping them inside the plot. */
function spreadLabels<T extends { y: number }>(labels: T[], top: number, bottom: number): T[] {
  const minGap = 13;
  const ordered = [...labels].sort((a, b) => a.y - b.y);
  for (let i = 1; i < ordered.length; i += 1) {
    const gap = ordered[i].y - ordered[i - 1].y;
    if (gap < minGap) ordered[i] = { ...ordered[i], y: ordered[i - 1].y + minGap };
  }
  const overflow = ordered.length ? ordered[ordered.length - 1].y - bottom : 0;
  if (overflow > 0) {
    for (let i = 0; i < ordered.length; i += 1) {
      ordered[i] = { ...ordered[i], y: Math.max(top, ordered[i].y - overflow) };
    }
  }
  return ordered;
}

export function LineChart({ series, height = 240, formatY, baseline, title }: LineChartProps) {
  const clipId = useId();
  const svgRef = useRef<SVGSVGElement>(null);
  const [hover, setHover] = useState<number | null>(null);
  const width = 720;

  const labels = useMemo(() => {
    const seen: string[] = [];
    for (const s of series) for (const p of s.points) if (!seen.includes(p.x)) seen.push(p.x);
    return seen.sort();
  }, [series]);

  const { lo, hi } = useMemo(() => {
    const values = series.flatMap((s) => s.points.map((p) => p.y)).filter((v): v is number => v !== null);
    if (baseline !== undefined) values.push(baseline);
    if (!values.length) return { lo: 0, hi: 1 };
    const min = Math.min(...values);
    const max = Math.max(...values);
    const pad = (max - min) * 0.08 || Math.abs(max || 1) * 0.08;
    return { lo: min - pad, hi: max + pad };
  }, [series, baseline]);

  if (!labels.length) {
    return <p className="empty">No sessions recorded yet.</p>;
  }

  const plotW = width - PAD.left - PAD.right;
  const plotH = height - PAD.top - PAD.bottom;
  const xAt = (index: number) =>
    PAD.left + (labels.length === 1 ? plotW / 2 : (index / (labels.length - 1)) * plotW);
  const yAt = (value: number) => PAD.top + plotH - ((value - lo) / (hi - lo)) * plotH;

  const ticks = niceTicks(lo, hi);
  const xTickEvery = Math.max(1, Math.ceil(labels.length / 6));

  function onMove(event: React.MouseEvent<SVGSVGElement>) {
    const svg = svgRef.current;
    if (!svg) return;
    const box = svg.getBoundingClientRect();
    const x = ((event.clientX - box.left) / box.width) * width;
    const index = Math.round(((x - PAD.left) / plotW) * (labels.length - 1));
    setHover(index >= 0 && index < labels.length ? index : null);
  }

  const hovered = hover === null ? null : labels[hover];

  return (
    <figure className="chart" style={{ margin: 0 }}>
      <svg
        ref={svgRef}
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={title}
        onMouseMove={onMove}
        onMouseLeave={() => setHover(null)}
      >
        <defs>
          <clipPath id={clipId}>
            <rect x={PAD.left} y={PAD.top} width={plotW} height={plotH} />
          </clipPath>
        </defs>

        <g className="axis">
          {ticks.map((tick) => (
            <g key={tick}>
              <line className="grid-line" x1={PAD.left} x2={PAD.left + plotW} y1={yAt(tick)} y2={yAt(tick)} />
              <text x={PAD.left - 8} y={yAt(tick)} textAnchor="end" dominantBaseline="middle">
                {formatY(tick)}
              </text>
            </g>
          ))}
          {labels.map((label, index) =>
            index % xTickEvery === 0 || index === labels.length - 1 ? (
              <text key={label} x={xAt(index)} y={height - 8} textAnchor="middle">
                {label.slice(5)}
              </text>
            ) : null,
          )}
        </g>

        {baseline !== undefined && (
          <line
            x1={PAD.left}
            x2={PAD.left + plotW}
            y1={yAt(baseline)}
            y2={yAt(baseline)}
            stroke="var(--muted-foreground)"
            strokeDasharray="3 3"
            strokeWidth={1}
            opacity={0.6}
          />
        )}

        <g clipPath={`url(#${clipId})`}>
          {series.map((s) => {
            const color = SERIES_TOKENS[s.slot % SERIES_TOKENS.length];
            const byLabel = new Map(s.points.map((p) => [p.x, p.y]));
            let path = "";
            let pen = false;
            labels.forEach((label, index) => {
              const value = byLabel.get(label);
              if (value === null || value === undefined) {
                pen = false;
                return;
              }
              path += `${pen ? "L" : "M"}${xAt(index).toFixed(2)},${yAt(value).toFixed(2)}`;
              pen = true;
            });
            return (
              <path key={s.name} d={path} fill="none" stroke={color} strokeWidth={2} strokeLinejoin="round" />
            );
          })}
        </g>

        {/* Direct labels: with three series they carry identity alongside the
         * legend, which is also what lets the dark palette's tightest CVD pair
         * stay legible. Curves that end close together — three cohorts all
         * starting at 100 — would stack their labels, so nudge them apart. */}
        {spreadLabels(
          series
            .map((s) => {
              const last = [...s.points].reverse().find((p) => p.y !== null);
              return last && last.y !== null
                ? { name: s.name, slot: s.slot, y: yAt(last.y) }
                : null;
            })
            .filter((label): label is { name: string; slot: number; y: number } => label !== null),
          PAD.top,
          PAD.top + plotH,
        ).map((label) => (
          <text
            key={`label-${label.name}`}
            x={PAD.left + plotW + 8}
            y={label.y}
            dominantBaseline="middle"
            fontSize={11}
            fontWeight={600}
            fill={SERIES_TOKENS[label.slot % SERIES_TOKENS.length]}
          >
            {label.name}
          </text>
        ))}

        {hover !== null && (
          <g>
            <line
              x1={xAt(hover)}
              x2={xAt(hover)}
              y1={PAD.top}
              y2={PAD.top + plotH}
              stroke="var(--muted-foreground)"
              strokeWidth={1}
              opacity={0.5}
            />
            {series.map((s) => {
              const value = s.points.find((p) => p.x === labels[hover])?.y;
              if (value === null || value === undefined) return null;
              return (
                <circle
                  key={`dot-${s.name}`}
                  cx={xAt(hover)}
                  cy={yAt(value)}
                  r={4}
                  fill={SERIES_TOKENS[s.slot % SERIES_TOKENS.length]}
                  stroke="var(--surface)"
                  strokeWidth={2}
                />
              );
            })}
          </g>
        )}
      </svg>

      <figcaption className="chart-legend">
        {series.map((s) => (
          <span key={s.name}>
            <i className="swatch" style={{ background: SERIES_TOKENS[s.slot % SERIES_TOKENS.length] }} />
            {s.name}
          </span>
        ))}
        {hovered && (
          <span className="mono" style={{ marginLeft: "auto" }}>
            {hovered}
            {series.map((s) => {
              const value = s.points.find((p) => p.x === hovered)?.y;
              return value === null || value === undefined
                ? null
                : ` · ${s.name} ${formatY(value)}`;
            })}
          </span>
        )}
      </figcaption>
    </figure>
  );
}

type Bar = { label: string; value: number; group?: string };

type BarChartProps = {
  bars: Bar[];
  formatValue: (value: number) => string;
  title: string;
};

/** Horizontal polarity bars around a zero baseline: profit is signed, so the
 *  encoding is gain/loss, not a categorical hue per strategy. */
export function BarChart({ bars, formatValue, title }: BarChartProps) {
  const [hover, setHover] = useState<string | null>(null);
  if (!bars.length) return <p className="empty">Nothing to plot.</p>;

  const rowH = 26;
  const gap = 2;
  const width = 960;
  const labelW = 330;
  // Value labels sit outside the bar end, so the plot has to stop short of
  // both edges by a gutter or the longest bar's value collides with the row
  // label on one side and runs off the canvas on the other.
  const gutter = 80;
  const height = bars.length * rowH + 24;
  const plotW = width - labelW - gutter * 2;
  const extent = Math.max(...bars.map((b) => Math.abs(b.value)), 1);
  const zero = labelW + gutter + plotW / 2;
  const scale = (value: number) => (value / extent) * (plotW / 2);
  const truncate = (text: string, max = 56) =>
    text.length <= max ? text : `${text.slice(0, max - 1)}…`;

  return (
    <figure className="chart" style={{ margin: 0 }}>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={title}>
        <line
          x1={zero}
          x2={zero}
          y1={4}
          y2={height - 20}
          stroke="var(--border)"
          strokeWidth={1}
        />
        {bars.map((bar, index) => {
          const y = index * rowH + 4;
          const w = Math.abs(scale(bar.value));
          const x = bar.value >= 0 ? zero : zero - w;
          const color = bar.value >= 0 ? "var(--gain)" : "var(--loss)";
          return (
            <g
              key={bar.label}
              onMouseEnter={() => setHover(bar.label)}
              onMouseLeave={() => setHover(null)}
              opacity={hover === null || hover === bar.label ? 1 : 0.55}
            >
              <rect x={0} y={y} width={width} height={rowH - gap} fill="transparent" />
              <text
                x={labelW - 12}
                y={y + (rowH - gap) / 2}
                textAnchor="end"
                dominantBaseline="middle"
                fontSize={11}
                fill="var(--muted-foreground)"
              >
                {truncate(bar.label)}
                <title>{bar.label}</title>
              </text>
              <rect
                x={x}
                y={y + 3}
                width={Math.max(w, 1)}
                height={rowH - gap - 6}
                rx={4}
                fill={color}
              />
              <text
                x={bar.value >= 0 ? x + w + 8 : x - 8}
                y={y + (rowH - gap) / 2}
                textAnchor={bar.value >= 0 ? "start" : "end"}
                dominantBaseline="middle"
                fontSize={11}
                fontWeight={500}
                fill="var(--foreground)"
              >
                {formatValue(bar.value)}
              </text>
            </g>
          );
        })}
      </svg>
      <figcaption className="chart-legend">
        <span>
          <i className="swatch" style={{ background: "var(--gain)" }} />
          gross profit
        </span>
        <span>
          <i className="swatch" style={{ background: "var(--loss)" }} />
          gross loss
        </span>
      </figcaption>
    </figure>
  );
}
