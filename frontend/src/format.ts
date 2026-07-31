// Artifact decimals are strings with up to thirty significant digits. They are
// parsed to a JS number only for display and charting, never to be sent back.

export function num(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function money(value: string | number | null | undefined, digits = 0): string {
  const parsed = num(value);
  if (parsed === null) return "—";
  return parsed.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function signedMoney(value: string | number | null | undefined): string {
  const parsed = num(value);
  if (parsed === null) return "—";
  return (parsed > 0 ? "+" : "") + money(parsed);
}

export function percent(value: string | number | null | undefined, digits = 2): string {
  const parsed = num(value);
  if (parsed === null) return "—";
  return `${(parsed * 100).toFixed(digits)}%`;
}

export function ratio(value: string | number | null | undefined, digits = 2): string {
  const parsed = num(value);
  if (parsed === null) return "—";
  return parsed.toFixed(digits);
}

export function count(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : value.toLocaleString("en-US");
}

/** `1f2e…c0dd` — enough of an identity to recognise, short enough to scan. */
export function shortId(identity: string | null | undefined): string {
  if (!identity) return "—";
  return identity.length <= 16 ? identity : `${identity.slice(0, 8)}…${identity.slice(-4)}`;
}

/** `monthly-ema6-below__close-cross-sma10__atr14x1p5__target-risk2p5`
 *  -> `M6-below · close-cross-sma10 · atr14x1p5 · risk2p5` */
export function shortStrategy(name: string): string {
  if (!name) return "—";
  return name
    .replace(/^monthly-ema(\d+)-/, "M$1-")
    .replace(/^weekly-ema(\d+)-/, "W$1-")
    .replace(/__target-/g, "__")
    .split("__")
    .join(" · ");
}

export function sign(value: string | number | null | undefined): "gain" | "loss" | "flat" {
  const parsed = num(value);
  if (parsed === null || parsed === 0) return "flat";
  return parsed > 0 ? "gain" : "loss";
}

const TIER_LABELS: Record<string, string> = {
  decision_ready: "Decision-ready",
  descriptive_20: "Descriptive (20+)",
  descriptive_10: "Descriptive (10+)",
  pre_10: "Pre-evidence",
};

export function tierLabel(tier: string): string {
  return TIER_LABELS[tier] ?? tier.replace(/_/g, " ");
}
