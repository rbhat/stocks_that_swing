import { useApi } from "../api";
import { ErrorCard, Loading, PageHead } from "../components/Layout";
import { Link } from "../router";
import type { LegacyForward as Payload, LegacyRow } from "../types";
import { LegacyNav, columns, valueOf } from "./LegacyNav";

function LedgerTable({ rows }: { rows: LegacyRow[] }) {
  if (!rows.length) return <p className="empty">No ledger rows have been recorded for this family.</p>;
  const fields = columns(rows, ["seq", "status", "symbol", "entry_date", "exit_date", "entry_price", "exit_price", "quantity", "pnl_usd"]);
  return (
    <div className="table-wrap"><table>
      <thead><tr>{fields.map((field) => <th key={field}>{field.replaceAll("_", " ")}</th>)}</tr></thead>
      <tbody>{rows.map((row, index) => <tr key={`${String(row.entry_id ?? index)}-${String(row.seq ?? index)}`}>{fields.map((field) => <td key={field}>{valueOf(row, field)}</td>)}</tr>)}</tbody>
    </table></div>
  );
}

export function LegacyForward({ family }: { family: string }) {
  const normalized = family.toLowerCase();
  const { data, error, loading } = useApi<Payload>(`/api/legacy/forward/${normalized}`);
  if (loading) return <Loading />;
  if (error) return <ErrorCard error={error} />;
  if (!data) return null;
  return (
    <>
      <LegacyNav />
      <PageHead title={`Legacy ${normalized.toUpperCase()} ledger`} subtitle="Append-only retired-book history. This is not the v1 forward paper book." />
      <div className="tabs">
        <Link to="/legacy/forward/h1">H1</Link><Link to="/legacy/forward/h2">H2</Link>
      </div>
      <section className="section"><h2>Open positions ({data.open.length})</h2><LedgerTable rows={data.open} /></section>
      <section className="section"><h2>Ledger history ({data.rows.length})</h2><LedgerTable rows={data.rows} /></section>
    </>
  );
}
