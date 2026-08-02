import { useId, useMemo, useRef, useState } from "react";
import type { ReportTradeExample } from "../types";

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

type CandleChartProps = {
  example: ReportTradeExample;
  title: string;
};

const INDICATOR_TOKENS = ["var(--series-1)", "var(--series-2)", "var(--series-3)", "var(--accent)"];

function f(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function compactNumber(value: number): string {
  if (Math.abs(value) >= 1_000_000_000) return `${(value / 1_000_000_000).toFixed(1)}B`;
  if (Math.abs(value) >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (Math.abs(value) >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
  return value.toFixed(0);
}

export function CandlestickChart({ example, title }: CandleChartProps) {
  const width = 880;
  const height = 370;
  const pad = { top: 16, right: 88, bottom: 28, left: 58 };
  const priceH = 250;
  const volumeTop = pad.top + priceH + 14;
  const volumeH = 56;
  const candles = example.candles;

  if (!candles.length) {
    return <p className="empty">No OHLCV bars available for this trade.</p>;
  }

  const sessions = candles.map((c) => c.session);
  const plotW = width - pad.left - pad.right;
  const xStep = candles.length <= 1 ? plotW : plotW / (candles.length - 1);
  const bodyW = Math.max(4, Math.min(12, xStep * 0.56));
  const xAt = (index: number) => pad.left + (candles.length === 1 ? plotW / 2 : index * xStep);

  const levelValues = [
    f(example.trade.entry_price),
    f(example.trade.exit_price),
    f(example.geometry.target_price),
    f(example.geometry.initial_stop_price),
  ];
  const indicatorValues = candles.flatMap((c) =>
    example.plotted_indicators.map((name) => f(c.indicators[name])).filter((v): v is number => v !== null),
  );
  const priceValues = candles.flatMap((c) => [f(c.high), f(c.low)]).filter((v): v is number => v !== null);
  const allPrices = [...priceValues, ...indicatorValues, ...levelValues.filter((v): v is number => v !== null)];
  const min = Math.min(...allPrices);
  const max = Math.max(...allPrices);
  const pricePad = (max - min) * 0.08 || Math.abs(max || 1) * 0.04;
  const lo = min - pricePad;
  const hi = max + pricePad;
  const yAt = (value: number) => pad.top + priceH - ((value - lo) / (hi - lo)) * priceH;

  const maxVolume = Math.max(...candles.map((c) => c.volume), 1);
  const volumeY = (value: number) => volumeTop + volumeH - (value / maxVolume) * volumeH;
  const ticks = niceTicks(lo, hi, 5);
  const xTickEvery = Math.max(1, Math.ceil(candles.length / 6));
  const entryIndex = sessions.indexOf(example.trade.entry_session);
  const exitIndex = sessions.indexOf(example.trade.exit_session);

  const levels = [
    { name: "entry", value: f(example.trade.entry_price), color: "var(--foreground)" },
    { name: "target", value: f(example.geometry.target_price), color: "var(--gain)" },
    { name: "stop", value: f(example.geometry.initial_stop_price), color: "var(--loss)" },
    { name: "exit", value: f(example.trade.exit_price), color: "var(--accent)" },
  ].filter((level): level is { name: string; value: number; color: string } => level.value !== null);

  return (
    <figure className="chart candle-chart" style={{ margin: 0 }}>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={title}>
        <g className="axis">
          {ticks.map((tick) => (
            <g key={tick}>
              <line className="grid-line" x1={pad.left} x2={pad.left + plotW} y1={yAt(tick)} y2={yAt(tick)} />
              <text x={pad.left - 8} y={yAt(tick)} textAnchor="end" dominantBaseline="middle">
                {tick.toFixed(2)}
              </text>
            </g>
          ))}
          {sessions.map((session, index) =>
            index % xTickEvery === 0 || index === sessions.length - 1 ? (
              <text key={session} x={xAt(index)} y={height - 8} textAnchor="middle">
                {session.slice(5)}
              </text>
            ) : null,
          )}
        </g>

        <line x1={pad.left} x2={pad.left + plotW} y1={volumeTop + volumeH} y2={volumeTop + volumeH} stroke="var(--border)" />

        {candles.map((candle, index) => {
          const open = f(candle.open) ?? 0;
          const high = f(candle.high) ?? open;
          const low = f(candle.low) ?? open;
          const close = f(candle.close) ?? open;
          const up = close >= open;
          const color = up ? "var(--gain)" : "var(--loss)";
          const x = xAt(index);
          const y1 = yAt(Math.max(open, close));
          const y2 = yAt(Math.min(open, close));
          const bodyH = Math.max(1, y2 - y1);
          return (
            <g key={candle.session}>
              <line x1={x} x2={x} y1={yAt(high)} y2={yAt(low)} stroke={color} strokeWidth={1.3} />
              <rect x={x - bodyW / 2} y={y1} width={bodyW} height={bodyH} fill={color} opacity={up ? 0.72 : 0.92} />
              <rect
                x={x - bodyW / 2}
                y={volumeY(candle.volume)}
                width={bodyW}
                height={volumeTop + volumeH - volumeY(candle.volume)}
                fill={color}
                opacity={0.26}
              />
            </g>
          );
        })}

        {example.plotted_indicators.map((name, slot) => {
          let path = "";
          let pen = false;
          candles.forEach((candle, index) => {
            const value = f(candle.indicators[name]);
            if (value === null) {
              pen = false;
              return;
            }
            path += `${pen ? "L" : "M"}${xAt(index).toFixed(2)},${yAt(value).toFixed(2)}`;
            pen = true;
          });
          return (
            <path
              key={name}
              d={path}
              fill="none"
              stroke={INDICATOR_TOKENS[slot % INDICATOR_TOKENS.length]}
              strokeWidth={1.6}
              strokeLinejoin="round"
            />
          );
        })}

        {levels.map((level, index) => (
          <g key={level.name}>
            <line
              x1={pad.left}
              x2={pad.left + plotW}
              y1={yAt(level.value)}
              y2={yAt(level.value)}
              stroke={level.color}
              strokeWidth={1.2}
              strokeDasharray={level.name === "entry" ? "none" : "4 3"}
              opacity={0.85}
            />
            <text
              x={pad.left + plotW + 8}
              y={yAt(level.value) + index * 2}
              dominantBaseline="middle"
              fontSize={10.5}
              fontWeight={600}
              fill={level.color}
            >
              {level.name} {level.value.toFixed(2)}
            </text>
          </g>
        ))}

        {[
          { index: entryIndex, label: "entry", color: "var(--foreground)" },
          { index: exitIndex, label: "exit", color: "var(--accent)" },
        ]
          .filter((marker) => marker.index >= 0)
          .map((marker) => (
            <g key={marker.label}>
              <line
                x1={xAt(marker.index)}
                x2={xAt(marker.index)}
                y1={pad.top}
                y2={volumeTop + volumeH}
                stroke={marker.color}
                strokeWidth={1}
                strokeDasharray="3 3"
                opacity={0.7}
              />
              <text x={xAt(marker.index) + 4} y={pad.top + 10} fontSize={10.5} fill={marker.color} fontWeight={600}>
                {marker.label}
              </text>
            </g>
          ))}

        <text x={pad.left - 8} y={volumeTop + volumeH / 2} textAnchor="end" dominantBaseline="middle" className="axis">
          Vol
        </text>
        <text x={pad.left} y={volumeTop - 4} fontSize={10.5} fill="var(--muted-foreground)">
          max {compactNumber(maxVolume)}
        </text>
      </svg>
      <figcaption className="chart-legend">
        <span>
          <i className="swatch" style={{ background: "var(--gain)" }} />
          up candle / volume
        </span>
        <span>
          <i className="swatch" style={{ background: "var(--loss)" }} />
          down candle / volume
        </span>
        {example.plotted_indicators.map((name, slot) => (
          <span key={name}>
            <i className="swatch" style={{ background: INDICATOR_TOKENS[slot % INDICATOR_TOKENS.length] }} />
            {name.replace("daily_", "")}
          </span>
        ))}
      </figcaption>
    </figure>
  );
}
