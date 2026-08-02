import { useApi } from "../api";
import { ErrorCard, Loading, PageHead, Tile } from "../components/Layout";
import { Link } from "../router";
import type { LegacyBacktest, LegacyRow } from "../types";
import { LegacyNav } from "./LegacyNav";

function scalarRows(value: unknown, prefix = "", depth = 0): { path: string; value: string }[] {
  if (depth > 4 || value === null || value === undefined) return [];
  if (typeof value !== "object") return [{ path: prefix, value: String(value) }];
  if (Array.isArray(value)) {
    if (value.every((item) => typeof item !== "object")) return [{ path: prefix, value: value.join(", ") }];
    return value.slice(0, 20).flatMap((item, index) => scalarRows(item, `${prefix}[${index}]`, depth + 1));
  }
  return Object.entries(value as LegacyRow).flatMap(([key, item]) =>
    scalarRows(item, prefix ? `${prefix}.${key}` : key, depth + 1),
  );
}

function StudyDetail({ family }: { family: string }) {
  const { data, error, loading } = useApi<LegacyBacktest>(`/api/legacy/backtests/${family}`);
  if (loading) return <Loading />;
  if (error) return <ErrorCard error={error} />;
  if (!data) return null;
  const rows = scalarRows(data.metrics).slice(0, 250);
  return (
    <>
      <div className="grid">
        <Tile label="Family" value={data.family.toUpperCase()} />
        <Tile label="Verdict" value={data.verdict ?? "Not recorded"} />
        <Tile label="Generated" value={data.generated_at?.slice(0, 10) ?? "—"} />
        <Tile label="Source artifacts" value={String(data.source_paths?.length ?? 0)} />
      </div>
      <section className="section"><h2>Study metrics</h2>
        {rows.length ? <div className="table-wrap"><table><thead><tr><th>Metric</th><th>Value</th></tr></thead><tbody>
          {rows.map((row, index) => <tr key={`${row.path}-${index}`}><td className="wide"><code>{row.path}</code></td><td>{row.value}</td></tr>)}
        </tbody></table></div> : <p className="empty">No study metrics are present.</p>}
      </section>
    </>
  );
}

export function LegacyBacktests({ family }: { family: string | null }) {
  const index = useApi<LegacyBacktest[]>("/api/legacy/backtests");
  if (index.loading) return <Loading />;
  if (index.error) return <ErrorCard error={index.error} />;
  if (!index.data) return null;
  return (
    <>
      <LegacyNav />
      <PageHead title="Legacy studies" subtitle="Retired pre-v1 research artifacts. Their historical verdicts do not enter the active top five unless re-evaluated under docs/PLAN.md." />
      <div className="tabs">
        <Link to="/legacy/backtests">Index</Link>
        {index.data.map((study) => <Link key={study.family} to={`/legacy/backtests/${study.family}`}>{study.family.toUpperCase()}</Link>)}
      </div>
      {family ? <StudyDetail family={family} /> : (
        <div className="grid">
          {index.data.map((study) => <Link key={study.family} to={`/legacy/backtests/${study.family}`} className="card cohort-card">
            <header><h3>{study.family.toUpperCase()}</h3><span className="badge">{study.verdict ?? "unjudged"}</span></header>
            <dl><dt>Generated</dt><dd>{study.generated_at?.slice(0, 10) ?? "—"}</dd><dt>Sources</dt><dd>{study.source_paths?.length ?? 0}</dd></dl>
          </Link>)}
          {!index.data.length && <p className="empty">No legacy study summaries are mounted.</p>}
        </div>
      )}
    </>
  );
}
