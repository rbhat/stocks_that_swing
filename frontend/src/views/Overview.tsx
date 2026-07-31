import { useApi } from "../api";
import { Link } from "../router";
import type { Overview as OverviewPayload } from "../types";
import { ErrorCard, IntegrityBanner, Loading, PageHead, Tile } from "../components/Layout";
import { count, money, shortId, tierLabel } from "../format";

export function Overview() {
  const { data, error, loading } = useApi<OverviewPayload>("/api/overview");
  if (loading) return <Loading />;
  if (error) return <ErrorCard error={error} />;
  if (!data) return null;

  const forward = data.forward;
  const decisionTrades = forward.evidence_thresholds.decision_ready_closed_trades_per_revision ?? 30;
  const awaitingFirst = forward.last_processed_session === null;

  return (
    <>
      <PageHead
        title="Overview"
        subtitle={`Paper-only forward run ${forward.run_id}, sealed against the out-of-sample evidence.`}
      />

      <IntegrityBanner reports={data.integrity} />

      {awaitingFirst && (
        <div className="banner">
          <span aria-hidden>◷</span>
          <div>
            <strong>The forward book has not traded yet</strong>
            <p>
              No session has been processed. Backfill is disabled and the first eligible
              signal session is {forward.first_eligible_signal_session}, so every number
              below the cohorts is backtest evidence.
            </p>
          </div>
        </div>
      )}

      <div className="grid">
        <Tile
          label="Forward status"
          value={forward.status.replace(/_/g, " ")}
          hint={
            forward.last_processed_session
              ? `last session ${forward.last_processed_session}`
              : `next eligible ${forward.next_eligible_signal_session ?? "—"}`
          }
        />
        <Tile
          label="Closed trades"
          value={count(forward.closed_trades)}
          hint={`${forward.minimum_closed_trades_per_revision} on the weakest of ${forward.strategy_count} revisions`}
        />
        <Tile
          label="Open positions"
          value={count(forward.open_positions)}
          hint={`${count(forward.session_count)} sessions processed`}
        />
        <Tile
          label="Decision readiness"
          value={forward.decision_readiness === "ready" ? "Ready" : "Not ready"}
          tone={forward.decision_readiness === "ready" ? "gain" : "flat"}
          hint={`needs ${decisionTrades} closed trades per revision`}
        />
      </div>

      <section className="section">
        <h2>Cohorts</h2>
        <div className="grid">
          {forward.cohorts.map((cohort) => (
            <Link key={cohort.cohort} to={`/forward/${cohort.cohort}`} className="card cohort-card">
              <header>
                <h3>{cohort.cohort}</h3>
                <span className={`badge ${cohort.forward_eligible ? "primary" : ""}`}>
                  {cohort.forward_eligible ? "forward" : "diagnostic only"}
                </span>
              </header>
              <dl>
                <dt>Revisions</dt>
                <dd>{cohort.member_count}</dd>
                <dt>Starting capital</dt>
                <dd>{money(cohort.starting_capital)}</dd>
                <dt>Current equity</dt>
                <dd>{money(cohort.current_equity)}</dd>
                <dt>Closed trades</dt>
                <dd>{count(cohort.closed_trades)}</dd>
                <dt>Evidence</dt>
                <dd>{tierLabel(cohort.evidence_tier)}</dd>
              </dl>
            </Link>
          ))}
        </div>
      </section>

      <section className="section">
        <h2>Backtest evidence</h2>
        <div className="grid">
          {data.backtests.map((window) => (
            <Link key={window.window} to={`/backtests/${window.window}`} className="card cohort-card">
              <header>
                <h3>{window.evidence_window || window.window}</h3>
                <span className="badge">{count(window.strategy_count)} revisions</span>
              </header>
              <dl>
                <dt>Evidence window</dt>
                <dd>
                  {window.evidence_start || "—"} → {window.evidence_end_exclusive || "—"}
                </dd>
                <dt>Trades</dt>
                <dd>{count(window.record_counts.trades ?? null)}</dd>
                <dt>Artifact</dt>
                <dd className="mono">{shortId(window.artifact_identity)}</dd>
              </dl>
            </Link>
          ))}
        </div>
      </section>

      <section className="section">
        <h2>Seal</h2>
        <div className="card">
          <p style={{ marginTop: 0 }}>
            The forward run is bound to the sealed out-of-sample evidence. Cohort equity from
            that window and forward equity are reported separately and are never joined.
          </p>
          <div className="table-wrap">
            <table>
              <tbody>
                <tr>
                  <td>Seal status</td>
                  <td className="num">
                    {data.seal.status || "—"}
                    {data.seal.sealed_on && <span className="muted"> · {data.seal.sealed_on}</span>}
                  </td>
                </tr>
                <tr>
                  <td>Forward-eligible cohorts</td>
                  <td className="num">{data.seal.forward_eligible_cohorts.join(", ") || "—"}</td>
                </tr>
                <tr>
                  <td>Seal identity</td>
                  <td className="num mono">{shortId(data.seal.seal_identity)}</td>
                </tr>
                <tr>
                  <td>Selection identity</td>
                  <td className="num mono">{shortId(data.seal.selection_identity)}</td>
                </tr>
                <tr>
                  <td>Forward identity</td>
                  <td className="num mono">{shortId(forward.identities.forward_identity)}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <div className="footnote">
        <p>
          Zero trading costs are assumed anywhere in this study; turnover and break-even cost are
          diagnostics and never change equity, profit, or rankings.
        </p>
        <p>
          Ten- and twenty-trade forward views are descriptive. Decision-ready evidence requires at
          least {decisionTrades} closed trades per revision.
        </p>
      </div>
    </>
  );
}
