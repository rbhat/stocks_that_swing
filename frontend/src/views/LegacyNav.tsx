import { Link } from "../router";

export function LegacyNav() {
  return (
    <>
      <div className="legacy-marker"><span className="badge warn">Legacy</span> Retired H1/H2 books</div>
      <div className="tabs legacy-tabs">
        <Link to="/legacy">Overview</Link>
        <Link to="/legacy/forward/h1">H1 ledger</Link>
        <Link to="/legacy/forward/h2">H2 ledger</Link>
        <Link to="/legacy/backtests">Studies</Link>
        <Link to="/legacy/config">Config</Link>
        <Link to="/legacy/jobs">Jobs</Link>
      </div>
    </>
  );
}

export function valueOf(row: Record<string, unknown>, key: string): string {
  const value = row[key];
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export function columns(rows: Record<string, unknown>[], preferred: string[]): string[] {
  const available = new Set(rows.flatMap((row) => Object.keys(row)));
  const selected = preferred.filter((key) => available.has(key));
  for (const key of available) if (!selected.includes(key) && selected.length < 9) selected.push(key);
  return selected;
}
