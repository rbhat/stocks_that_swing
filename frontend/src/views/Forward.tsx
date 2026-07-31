import { useApi } from "../api";
import { Link, useRouter } from "../router";
import type { CohortDetail, ForwardOverview } from "../types";
import { ErrorCard, IntegrityBanner, Loading, PageHead, Tile } from "../components/Layout";
import { LineChart, type Series } from "../components/Chart";
import {
  count,
  money,
  num,
  percent,
  ratio,
  shortStrategy,
  sign,
  signedMoney,
  tierLabel,
} from "../format";

const COHORT_ORDER = ["VF9", "MC5", "FO4"];

export function Forward({ cohort }: { cohort: string | null }) {
  const { navigate } = useRouter();
  const overview = useApi<ForwardOverview>("/api/forward");
  const detail = useApi<CohortDetail>(cohort ? `/api/forward/${cohort}` : null);

  if (overview.loading) return <Loading />;
  if (overview.error) return <ErrorCard error={overview.error} />;
  if (!overview.data) return null;
  const forward = overview.data;

  return (
    <>
      <PageHead
        title="Forward ledger"
        subtitle={`${forward.run_id} · no backfill · paper only${
          forward.last_processed_session
            ? ` · last session ${forward.last_processed_session}`
            : ` · awaiting ${forward.first_eligible_signal_session}`
        }`}
      />

      <IntegrityBanner reports={{ [forward.run_id]: forward.integrity }} />

      <div className="tabs">
        <button className={cohort === null ? "active" : ""} onClick={() => navigate("/forward")}>
          All cohorts
        </button>
        {forward.cohorts.map((row) => (
          <Link key={row.cohort} to={`/forward/${row.cohort}`}>
            {row.cohort}
          </Link>
        ))}
      </div>

      {cohort === null ? (
        <AllCohorts forward={forward} />
      ) : detail.loading ? (
        <Loading />
      ) : detail.error ? (
        <ErrorCard error={detail.error} />
      ) : detail.data ? (
        <CohortView detail={detail.data} />
      ) : null}
    </>
  );
}

function AllCohorts({ forward }: { forward: ForwardOverview }) {
  const series: Series[] = [];
  return (
    <>
      <div className="grid">
        {forward.cohorts.map((row) => (
          <Tile
            key={row.cohort}
            label={`${row.cohort} · ${row.role}`}
            value={money(row.current_equity)}
            hint={`${row.member_count} revisions · ${count(row.closed_trades)} closed · ${tierLabel(
              row.evidence_tier,
            )}`}
          />
        ))}
      </div>

      <section className="section">
        <h2>Revision books</h2>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Strategy revision</th>
                <th>Cohorts</th>
                <th className="num">Equity</th>
                <th className="num">P&amp;L</th>
                <th className="num">Closed</th>
                <th className="num">Open</th>
                <th className="num">Max DD</th>
                <th className="num">Turnover</th>
              </tr>
            </thead>
            <tbody>
              {forward.books.map((book) => {
                const pnl =
                  (num(book.current_equity) ?? 0) - (num(book.starting_equity) ?? 0);
                return (
                  <tr key={book.strategy_revision_identity}>
                    <td className="wide">{shortStrategy(book.strategy_name)}</td>
                    <td>
                      {book.memberships.map((m) => (
                        <span
                          key={m}
                          className={`badge ${
                            forward.forward_eligible_cohorts.includes(m) ? "primary" : ""
                          }`}
                          style={{ marginRight: 4 }}
                        >
                          {m}
                        </span>
                      ))}
                    </td>
                    <td className="num">{money(book.current_equity)}</td>
                    <td className={`num ${sign(pnl)}`}>{signedMoney(pnl)}</td>
                    <td className="num">{count(book.closed_trades)}</td>
                    <td className="num">{count(book.open_positions)}</td>
                    <td className="num">{percent(book.maximum_drawdown)}</td>
                    <td className="num">{ratio(book.turnover)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      {series.length === 0 && forward.session_count === 0 && (
        <p className="empty">
          No equity curve yet — the run has processed no sessions. It admits its first signals on{" "}
          {forward.first_eligible_signal_session}.
        </p>
      )}
    </>
  );
}

function CohortView({ detail }: { detail: CohortDetail }) {
  const summary = detail.summary;
  const slot = Math.max(0, COHORT_ORDER.indexOf(detail.cohort));
  const equitySeries: Series[] = detail.equity.length
    ? [
        {
          name: detail.cohort,
          slot,
          points: detail.equity.map((p) => ({ x: p.session, y: num(p.normalized_index) })),
        },
      ]
    : [];
  const drawdownSeries: Series[] = detail.equity.length
    ? [
        {
          name: detail.cohort,
          slot,
          points: detail.equity.map((p) => ({ x: p.session, y: num(p.drawdown) })),
        },
      ]
    : [];

  return (
    <>
      {summary && !summary.forward_eligible && (
        <div className="banner">
          <span aria-hidden>ⓘ</span>
          <div>
            <strong>{detail.cohort} is a diagnostic cohort</strong>
            <p>
              It is not forward-eligible under the charter. Its numbers are reported for
              concentration diagnostics and never as a forward recommendation.
            </p>
          </div>
        </div>
      )}

      {summary && (
        <div className="grid">
          <Tile label="Revisions" value={count(summary.member_count)} hint={summary.role} />
          <Tile label="Starting capital" value={money(summary.starting_capital)} />
          <Tile
            label="Current equity"
            value={money(summary.current_equity)}
            tone={sign(
              (num(summary.current_equity) ?? 0) - (num(summary.starting_capital) ?? 0),
            )}
          />
          <Tile
            label="Closed trades"
            value={count(summary.closed_trades)}
            hint={`${summary.minimum_closed_trades_per_revision} on the weakest revision · ${tierLabel(
              summary.evidence_tier,
            )}`}
          />
        </div>
      )}

      {equitySeries.length > 0 ? (
        <>
          <section className="section">
            <h2>Normalised cohort equity (start = 100)</h2>
            <div className="card">
              <LineChart
                title={`${detail.cohort} normalised forward equity`}
                series={equitySeries}
                baseline={100}
                formatY={(v) => v.toFixed(1)}
              />
            </div>
          </section>
          <section className="section">
            <h2>Drawdown</h2>
            <div className="card">
              <LineChart
                title={`${detail.cohort} forward drawdown`}
                series={drawdownSeries}
                baseline={0}
                formatY={(v) => `${(v * 100).toFixed(1)}%`}
              />
            </div>
          </section>
        </>
      ) : (
        <p className="empty">No forward equity recorded for {detail.cohort} yet.</p>
      )}

      <section className="section">
        <h2>Members</h2>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Strategy revision</th>
                <th className="num">Equity</th>
                <th className="num">P&amp;L</th>
                <th className="num">Closed</th>
                <th className="num">Open</th>
                <th className="num">Max DD</th>
              </tr>
            </thead>
            <tbody>
              {detail.members.map((book) => {
                const pnl = (num(book.current_equity) ?? 0) - (num(book.starting_equity) ?? 0);
                return (
                  <tr key={book.strategy_revision_identity}>
                    <td className="wide">{shortStrategy(book.strategy_name)}</td>
                    <td className="num">{money(book.current_equity)}</td>
                    <td className={`num ${sign(pnl)}`}>{signedMoney(pnl)}</td>
                    <td className="num">{count(book.closed_trades)}</td>
                    <td className="num">{count(book.open_positions)}</td>
                    <td className="num">{percent(book.maximum_drawdown)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      <section className="section">
        <h2>Closed trades</h2>
        {detail.trades.length ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Entry</th>
                  <th>Exit</th>
                  <th>Reason</th>
                  <th className="num">Quantity</th>
                  <th className="num">Entry price</th>
                  <th className="num">Exit price</th>
                  <th className="num">Gross P&amp;L</th>
                </tr>
              </thead>
              <tbody>
                {[...detail.trades].reverse().map((trade, index) => (
                  <tr key={`${trade.permanent_id}-${trade.exit_session}-${index}`}>
                    <td>{trade.symbol ?? "—"}</td>
                    <td>{trade.entry_session ?? "—"}</td>
                    <td>{trade.exit_session ?? "—"}</td>
                    <td>{trade.exit_reason ?? "—"}</td>
                    <td className="num">{count(num(trade.quantity))}</td>
                    <td className="num">{money(trade.entry_price, 2)}</td>
                    <td className="num">{money(trade.exit_price, 2)}</td>
                    <td className={`num ${sign(trade.gross_pnl)}`}>
                      {signedMoney(trade.gross_pnl)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="empty">No closed trades in this cohort yet.</p>
        )}
      </section>
    </>
  );
}
