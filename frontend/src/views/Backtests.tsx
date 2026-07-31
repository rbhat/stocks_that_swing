import { useApi } from "../api";
import { Link, useRouter } from "../router";
import type { CohortComparison, Seal, WindowDetail, WindowSummary } from "../types";
import { ErrorCard, IntegrityBanner, Loading, PageHead, Tile } from "../components/Layout";
import { BarChart, LineChart, type Series } from "../components/Chart";
import {
  count,
  money,
  num,
  percent,
  ratio,
  shortId,
  shortStrategy,
  sign,
  signedMoney,
} from "../format";

const COHORT_ORDER = ["VF9", "MC5", "FO4"];

const AXES: { key: string; title: string; blurb: string }[] = [
  { key: "profit", title: "Gross profit", blurb: "Ranked by gross profit alone." },
  { key: "drawdown", title: "Maximum drawdown", blurb: "Ranked by shallowest drawdown alone." },
  {
    key: "profit_drawdown",
    title: "Profit / drawdown",
    blurb: "Ranked by the ratio alone; undefined ratios rank last.",
  },
];

export function Backtests({ window: windowId }: { window: string | null }) {
  const { navigate } = useRouter();
  const index = useApi<{ windows: WindowSummary[]; seal: Seal }>("/api/backtests");

  if (index.loading) return <Loading />;
  if (index.error) return <ErrorCard error={index.error} />;
  if (!index.data) return null;

  return (
    <>
      <PageHead
        title="Backtests"
        subtitle="Retrospective screening evidence. Zero assumed trading costs; the three rankings are independent and are never combined into a composite."
      />

      <div className="tabs">
        <button className={windowId === null ? "active" : ""} onClick={() => navigate("/backtests")}>
          Cohort analysis
        </button>
        {index.data.windows.map((w) => (
          <Link key={w.window} to={`/backtests/${w.window}`}>
            {w.evidence_window || w.window}
          </Link>
        ))}
      </div>

      {windowId === null ? <CohortAnalysis /> : <WindowView window={windowId} />}
    </>
  );
}

function CohortAnalysis() {
  const { data, error, loading } = useApi<CohortComparison>("/api/backtests/cohorts");
  if (loading) return <Loading />;
  if (error) return <ErrorCard error={error} />;
  if (!data) return null;
  if (!data.present) return <p className="empty">The cohort analysis is not present on this host.</p>;

  const cohorts = [...new Set(data.cohort_equity.map((p) => p.cohort))].sort(
    (a, b) => COHORT_ORDER.indexOf(a) - COHORT_ORDER.indexOf(b),
  );
  const toSeries = (field: "normalized_index" | "drawdown"): Series[] =>
    cohorts.map((cohort) => ({
      name: cohort,
      slot: Math.max(0, COHORT_ORDER.indexOf(cohort)),
      points: data.cohort_equity
        .filter((p) => p.cohort === cohort)
        .map((p) => ({ x: p.session, y: num(p[field]) })),
    }));

  const bars = [...data.strategy_metrics]
    .map((row) => ({
      label: `${row.membership} · ${shortStrategy(row.display_name || row.strategy_name)}`,
      value: num(row.gross_profit) ?? 0,
    }))
    .sort((a, b) => b.value - a.value);

  return (
    <>
      <IntegrityBanner reports={{ "oos-cohort-comparison-v1": data.integrity }} />

      <div className="banner">
        <span aria-hidden>ⓘ</span>
        <div>
          <strong>This is out-of-sample evidence, not forward performance</strong>
          <p>
            Evidence window {data.source.evidence_start} → {data.source.evidence_end_exclusive} with
            outcomes to {data.source.outcome_end_exclusive}. It is reported separately from the
            forward ledger and the two curves are never joined.
          </p>
        </div>
      </div>

      <div className="grid">
        {data.cohort_metrics.map((row) => (
          <Tile
            key={row.cohort}
            label={row.cohort}
            value={signedMoney(row.gross_profit)}
            tone={sign(row.gross_profit)}
            hint={`${row.member_count} revisions · ${count(row.closed_trades)} closed · DD ${percent(
              row.maximum_drawdown,
            )}`}
          />
        ))}
      </div>

      <section className="section">
        <h2>Normalised cohort equity (start = 100)</h2>
        <div className="card">
          <LineChart
            title="Normalised out-of-sample cohort equity"
            series={toSeries("normalized_index")}
            baseline={100}
            formatY={(v) => v.toFixed(1)}
          />
        </div>
      </section>

      <section className="section">
        <h2>Cohort drawdown</h2>
        <div className="card">
          <LineChart
            title="Out-of-sample cohort drawdown"
            series={toSeries("drawdown")}
            baseline={0}
            formatY={(v) => `${(v * 100).toFixed(1)}%`}
          />
        </div>
      </section>

      <section className="section">
        <h2>Gross profit by revision</h2>
        <div className="card">
          <BarChart
            title="Out-of-sample gross profit by strategy revision"
            bars={bars}
            formatValue={(v) => signedMoney(v)}
          />
        </div>
      </section>

      <section className="section">
        <h2>Cohort metrics</h2>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Cohort</th>
                <th className="num">Members</th>
                <th className="num">Closed</th>
                <th className="num">Ending equity</th>
                <th className="num">Gross profit</th>
                <th className="num">Return</th>
                <th className="num">Max DD</th>
                <th className="num">Profit/DD</th>
                <th className="num">+ / − / flat</th>
              </tr>
            </thead>
            <tbody>
              {data.cohort_metrics.map((row) => (
                <tr key={row.cohort}>
                  <td>{row.cohort}</td>
                  <td className="num">{count(row.member_count)}</td>
                  <td className="num">{count(row.closed_trades)}</td>
                  <td className="num">{money(row.ending_equity)}</td>
                  <td className={`num ${sign(row.gross_profit)}`}>
                    {signedMoney(row.gross_profit)}
                  </td>
                  <td className={`num ${sign(row.gross_return)}`}>{percent(row.gross_return)}</td>
                  <td className="num">{percent(row.maximum_drawdown)}</td>
                  <td className="num">{ratio(row.profit_drawdown)}</td>
                  <td className="num">
                    {row.positive_revision_count} / {row.negative_revision_count} /{" "}
                    {row.flat_revision_count}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="section">
        <h2>Leave-one-out</h2>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Cohort</th>
                <th>Omitted revision</th>
                <th className="num">Gross profit</th>
                <th className="num">Return</th>
                <th className="num">Max DD</th>
              </tr>
            </thead>
            <tbody>
              {data.leave_one_out.map((row) => (
                <tr key={`${row.cohort}-${row.omitted_strategy_revision_identity}`}>
                  <td>{row.cohort}</td>
                  <td className="wide">{shortStrategy(row.omitted_strategy_name)}</td>
                  <td className={`num ${sign(row.gross_profit)}`}>
                    {signedMoney(row.gross_profit)}
                  </td>
                  <td className={`num ${sign(row.gross_return)}`}>{percent(row.gross_return)}</td>
                  <td className="num">{percent(row.maximum_drawdown)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="section">
        <h2>Report</h2>
        <div className="card">
          <div className="report">{data.report || "No report recorded."}</div>
        </div>
      </section>
    </>
  );
}

function WindowView({ window: windowId }: { window: string }) {
  const { data, error, loading } = useApi<WindowDetail>(`/api/backtests/${windowId}`);
  if (loading) return <Loading />;
  if (error) return <ErrorCard error={error} />;
  if (!data) return null;
  if (!data.present) {
    return (
      <p className="empty">
        <code>{windowId}</code> is not present on this host. Push it with{" "}
        <code>deploy/push_backtests.sh</code>.
      </p>
    );
  }

  const summary = data.summary;

  return (
    <>
      <IntegrityBanner reports={{ [windowId]: data.integrity }} />

      {summary && (
        <div className="grid">
          <Tile
            label="Evidence window"
            value={summary.evidence_window || windowId}
            hint={`${summary.evidence_start || "—"} → ${summary.evidence_end_exclusive || "—"}`}
          />
          <Tile label="Revisions" value={count(summary.strategy_count)} />
          <Tile label="Trades" value={count(summary.record_counts.trades ?? null)} />
          <Tile
            label="Artifact"
            value={shortId(summary.artifact_identity)}
            hint={summary.evidence_label.replace(/_/g, " ")}
          />
        </div>
      )}

      {AXES.map((axis) => (
        <section className="section" key={axis.key}>
          <h2>
            Top five by {axis.title.toLowerCase()}
          </h2>
          <div className="card">
            <p className="muted" style={{ marginTop: 0 }}>
              {axis.blurb}
            </p>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th className="num">#</th>
                    <th>Strategy revision</th>
                    <th className="num">Gross profit</th>
                    <th className="num">Return</th>
                    <th className="num">Max DD</th>
                    <th className="num">Profit/DD</th>
                    <th className="num">Trades</th>
                    <th className="num">Break-even cost</th>
                  </tr>
                </thead>
                <tbody>
                  {(data.rankings[axis.key] ?? []).map((entry) => (
                    <tr key={`${axis.key}-${entry.strategy_revision_identity}`}>
                      <td className="num">{entry.rank}</td>
                      <td className="wide">
                        {entry.strategy_name
                          ? shortStrategy(entry.strategy_name)
                          : shortId(entry.strategy_revision_identity)}
                      </td>
                      <td className={`num ${sign(entry.gross_profit)}`}>
                        {signedMoney(entry.gross_profit)}
                      </td>
                      <td className={`num ${sign(entry.gross_return)}`}>
                        {percent(entry.gross_return)}
                      </td>
                      <td className="num">{percent(entry.maximum_drawdown)}</td>
                      <td className="num">
                        {entry.profit_drawdown_status === "defined"
                          ? ratio(entry.profit_drawdown)
                          : entry.profit_drawdown_status || "—"}
                      </td>
                      <td className="num">{count(entry.trade_count)}</td>
                      <td className="num">{percent(entry.break_even_proportional_cost, 3)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </section>
      ))}

      {data.limitations.length > 0 && (
        <section className="section">
          <h2>Limitations</h2>
          <div className="card">
            {data.limitations.map((limitation) => (
              <p key={limitation.kind} className="muted" style={{ marginTop: 0 }}>
                <code>{limitation.kind}</code> — {limitation.statement}
              </p>
            ))}
          </div>
        </section>
      )}

      <section className="section">
        <h2>Report</h2>
        <div className="card">
          <div className="report">{data.report || "No report recorded."}</div>
        </div>
      </section>
    </>
  );
}
