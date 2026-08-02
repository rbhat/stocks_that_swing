import { useApi } from "../api";
import { LineChart, type Series } from "../components/Chart";
import { ErrorCard, Loading, PageHead, Tile } from "../components/Layout";
import { money, percent, signedMoney, sign } from "../format";
import type { LegacyOverview as Payload, LegacyRow } from "../types";
import { LegacyNav, columns, valueOf } from "./LegacyNav";

function LegacyTable({ rows, preferred }: { rows: LegacyRow[]; preferred: string[] }) {
  if (!rows.length) return <p className="empty">No records.</p>;
  const fields = columns(rows, preferred);
  return (
    <div className="table-wrap">
      <table>
        <thead><tr>{fields.map((field) => <th key={field}>{field.replaceAll("_", " ")}</th>)}</tr></thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={String(row.entry_id ?? row.date ?? index)}>
              {fields.map((field) => <td key={field}>{valueOf(row, field)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function LegacyOverview() {
  const { data, error, loading } = useApi<Payload>("/api/legacy/overview");
  if (loading) return <Loading />;
  if (error) return <ErrorCard error={error} />;
  if (!data) return null;

  const books = [...new Set(data.equity.map((row) => String(row.book ?? "book")))];
  const series: Series[] = books.map((book, slot) => ({
    name: book,
    slot,
    points: data.equity
      .filter((row) => String(row.book ?? "book") === book)
      .map((row) => ({ x: String(row.date ?? ""), y: Number(row.equity ?? NaN) }))
      .map((point) => ({ ...point, y: Number.isFinite(point.y) ? point.y : null })),
  }));

  return (
    <>
      <LegacyNav />
      <PageHead title="Legacy overview" subtitle="Retired H1/H2 forward books. Kept separate from the Swing Ranking v1 evidence and forward ledger." />
      <div className="grid">
        <Tile label="Realized P&L" value={signedMoney(data.tiles.total_pnl)} tone={sign(data.tiles.total_pnl)} />
        <Tile label="Open positions" value={String(data.tiles.open_count)} />
        <Tile label="Capital deployed" value={money(data.tiles.usd_deployed)} />
        <Tile label="Win rate" value={percent(data.tiles.win_rate)} />
      </div>
      <section className="section">
        <h2>Book equity</h2>
        <div className="card"><LineChart title="Legacy book equity" series={series} formatY={(value) => money(value)} /></div>
      </section>
      <section className="section">
        <h2>Open positions</h2>
        <LegacyTable rows={data.open_positions} preferred={["family", "symbol", "status", "entry_date", "entry_price", "quantity", "usd_deployed"]} />
      </section>
      <section className="section">
        <h2>Recent signals</h2>
        <LegacyTable rows={data.recent_signals} preferred={["date", "signal_date", "book", "family", "symbol", "kind", "entry_id"]} />
      </section>
    </>
  );
}
