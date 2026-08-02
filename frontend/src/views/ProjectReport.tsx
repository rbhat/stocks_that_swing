import { useApi } from "../api";
import { CandlestickChart, LineChart, BarChart, type Series } from "../components/Chart";
import { ErrorCard, IntegrityBanner, Loading, PageHead, Tile } from "../components/Layout";
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
import type { ProjectReport, ReportStrategy, ReportTradeExample } from "../types";

const COHORT_ORDER = ["VF9", "MC5", "FO4"];

export function ProjectReportView() {
  const { data, error, loading } = useApi<ProjectReport>("/api/backtests/project-report");

  if (loading) return <Loading />;
  if (error) return <ErrorCard error={error} />;
  if (!data) return null;
  if (!data.present) return <p className="empty">The project report is not present on this host.</p>;

  const cohorts = data.cohorts.map((c) => c.cohort);
  const toSeries = (field: "normalized_index" | "drawdown"): Series[] =>
    cohorts.map((cohort) => ({
      name: cohort,
      slot: Math.max(0, COHORT_ORDER.indexOf(cohort)),
      points: data.cohort_equity
        .filter((p) => p.cohort === cohort)
        .map((p) => ({ x: p.session, y: num(p[field]) })),
    }));

  const strategyBars = data.cohorts
    .find((cohort) => cohort.cohort === "VF9")
    ?.strategies.map((strategy) => ({
      label: shortStrategy(strategy.display_name || strategy.strategy_name),
      value: num(strategy.stats.gross_profit) ?? 0,
    }))
    .sort((a, b) => b.value - a.value) ?? [];

  return (
    <>
      <PageHead
        title={data.title}
        subtitle={`Sealed OOS evidence ${data.source.evidence_start} to ${data.source.evidence_end_exclusive}; outcomes through ${data.source.outcome_end_exclusive}.`}
      />

      <IntegrityBanner reports={{ "oos-cohort-comparison-v1": data.integrity }} />

      <section className="report-intro">
        <div>
          <h2>Goal</h2>
          <p>{data.goal}</p>
        </div>
        <div>
          <h2>Conclusion</h2>
          {data.conclusion.map((line) => (
            <p key={line}>{line}</p>
          ))}
        </div>
      </section>

      <details className="collapsible" open>
        <summary>
          <span>Overall OOS Evidence</span>
          <small>{shortId(data.source.analysis_identity)}</small>
        </summary>
        <div className="collapsible-body">
          <div className="grid">
            {data.cohorts.map((cohort) => (
              <Tile
                key={cohort.cohort}
                label={cohort.cohort}
                value={signedMoney(cohort.metrics.gross_profit)}
                tone={sign(cohort.metrics.gross_profit)}
                hint={`${cohort.metrics.member_count} books · ${count(
                  cohort.metrics.closed_trades,
                )} trades · DD ${percent(cohort.metrics.maximum_drawdown)}`}
              />
            ))}
          </div>

          <div className="grid-2 report-chart-grid">
            <div className="card">
              <h3>Normalized Equity</h3>
              <LineChart
                title="Normalized OOS equity by cohort"
                series={toSeries("normalized_index")}
                baseline={100}
                formatY={(v) => v.toFixed(1)}
              />
            </div>
            <div className="card">
              <h3>Cohort Drawdown</h3>
              <LineChart
                title="OOS drawdown by cohort"
                series={toSeries("drawdown")}
                baseline={0}
                formatY={(v) => `${(v * 100).toFixed(1)}%`}
              />
            </div>
          </div>

          <div className="card report-wide-chart">
            <h3>Strategy Gross P&L</h3>
            <BarChart
              title="Strategy gross P&L"
              bars={strategyBars}
              formatValue={(value) => signedMoney(value)}
            />
          </div>
        </div>
      </details>

      {data.cohorts.map((cohort) => (
        <details className="collapsible cohort-report" key={cohort.cohort} open={cohort.cohort !== "VF9"}>
          <summary>
            <span>{cohort.cohort}</span>
            <small>
              {signedMoney(cohort.metrics.gross_profit)} · {count(cohort.metrics.closed_trades)} trades
            </small>
          </summary>
          <div className="collapsible-body">
            <p className="report-description">{cohort.description}</p>
            <CohortStats metrics={cohort.metrics} />
            <div className="strategy-stack">
              {cohort.strategies.map((strategy) => (
                <StrategySection key={`${cohort.cohort}-${strategy.strategy_revision_identity}`} strategy={strategy} />
              ))}
            </div>
          </div>
        </details>
      ))}

      {data.limitations.length > 0 && (
        <details className="collapsible">
          <summary>
            <span>Limitations</span>
            <small>{data.limitations.length} recorded</small>
          </summary>
          <div className="collapsible-body limitation-list">
            {data.limitations.map((limitation) => (
              <p key={limitation.kind}>
                <code>{limitation.kind}</code> {limitation.statement}
              </p>
            ))}
          </div>
        </details>
      )}
    </>
  );
}

function CohortStats({ metrics }: { metrics: ProjectReport["cohorts"][number]["metrics"] }) {
  return (
    <div className="table-wrap compact-table">
      <table>
        <thead>
          <tr>
            <th>Metric</th>
            <th className="num">Value</th>
            <th>Metric</th>
            <th className="num">Value</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Starting capital</td>
            <td className="num">{money(metrics.starting_capital)}</td>
            <td>Ending equity</td>
            <td className="num">{money(metrics.ending_equity)}</td>
          </tr>
          <tr>
            <td>Gross P&L</td>
            <td className={`num ${sign(metrics.gross_profit)}`}>{signedMoney(metrics.gross_profit)}</td>
            <td>Return</td>
            <td className={`num ${sign(metrics.gross_return)}`}>{percent(metrics.gross_return)}</td>
          </tr>
          <tr>
            <td>Max drawdown</td>
            <td className="num">{percent(metrics.maximum_drawdown)}</td>
            <td>Max drawdown dollars</td>
            <td className="num">{money(metrics.maximum_drawdown_dollars)}</td>
          </tr>
          <tr>
            <td>Profit / drawdown</td>
            <td className="num">{ratio(metrics.profit_drawdown)}</td>
            <td>Positive / negative / flat books</td>
            <td className="num">
              {metrics.positive_revision_count} / {metrics.negative_revision_count} / {metrics.flat_revision_count}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

function StrategySection({ strategy }: { strategy: ReportStrategy }) {
  return (
    <details className="strategy-report">
      <summary>
        <span>{shortStrategy(strategy.display_name || strategy.strategy_name)}</span>
        <small>
          {signedMoney(strategy.stats.gross_profit)} · {count(strategy.stats.closed_trades)} trades · DD{" "}
          {percent(strategy.stats.maximum_drawdown)}
        </small>
      </summary>
      <div className="strategy-body">
        <p className="report-description">{strategy.description || strategy.strategy_name}</p>

        <div className="strategy-meta">
          <span className={`badge ${sign(strategy.stats.gross_profit)}`}>
            {signedMoney(strategy.stats.gross_profit)}
          </span>
          <span className="badge">Return {percent(strategy.stats.gross_return)}</span>
          <span className="badge">Drawdown {percent(strategy.stats.maximum_drawdown)}</span>
          <span className="badge">
            W/L/F {strategy.stats.wins}/{strategy.stats.losses}/{strategy.stats.flats}
          </span>
          <span className="badge">Turnover {ratio(strategy.stats.turnover)}</span>
        </div>

        <div className="rules-grid">
          {strategy.rules.map((rule) => (
            <span key={rule}>{rule}</span>
          ))}
        </div>

        <div className="trade-example-grid">
          {strategy.examples.map((example) => (
            <TradeExampleCard key={`${example.kind}-${example.trade.trade_identity}`} example={example} />
          ))}
        </div>
      </div>
    </details>
  );
}

function TradeExampleCard({ example }: { example: ReportTradeExample }) {
  const tone = sign(example.trade.gross_pnl);
  const label = example.fallback
    ? `${example.kind === "win" ? "Win" : "Loss"} fallback`
    : example.kind === "win"
      ? "Largest win"
      : "Largest loss";

  return (
    <div className="trade-example">
      <div className="trade-example-head">
        <div>
          <h4>
            {label}: {example.trade.symbol}
          </h4>
          <p>
            {example.trade.entry_session} to {example.trade.exit_session} · {example.trade.exit_reason}
          </p>
        </div>
        <strong className={tone}>{signedMoney(example.trade.gross_pnl)}</strong>
      </div>

      <CandlestickChart example={example} title={`${example.trade.symbol} ${label}`} />

      <div className="trade-facts">
        <span>Entry {money(example.trade.entry_price)}</span>
        <span>Exit {money(example.trade.exit_price)}</span>
        <span>TP {money(example.geometry.target_price)}</span>
        <span>SL {money(example.geometry.initial_stop_price)}</span>
        <span>Qty {count(Number(example.trade.quantity))}</span>
      </div>

      <div className="signal-facts">
        {Object.entries(example.signal.facts).map(([name, value]) => (
          <span key={name}>
            {name.replace("daily_", "").replace("weekly_", "").replace("monthly_", "")}: {ratio(value)}
          </span>
        ))}
      </div>
    </div>
  );
}
