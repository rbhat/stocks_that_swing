import type { Integrity } from "../types";
import { Link } from "../router";
import { logout } from "../api";

export function Shell({
  email,
  children,
}: {
  email: string | null;
  children: React.ReactNode;
}) {
  return (
    <div className="shell">
      <header className="topbar">
        <Link to="/" className="brand">
          <img src="/favicon.svg" alt="" />
          <span>
            Swing ranking <small>v1</small>
          </span>
        </Link>
        <nav className="nav">
          <Link to="/">Overview</Link>
          <Link to="/forward">Forward</Link>
          <Link to="/backtests">Backtests</Link>
          <Link to="/project-report">Report</Link>
          <Link to="/legacy">Legacy</Link>
        </nav>
        <div className="topbar-end">
          {email && <span className="muted">{email}</span>}
          <button
            className="button link"
            onClick={async () => {
              await logout();
              window.location.href = "/login";
            }}
          >
            Sign out
          </button>
        </div>
      </header>
      <main>{children}</main>
    </div>
  );
}

export function PageHead({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="page-head">
      <h1>{title}</h1>
      {subtitle && <p>{subtitle}</p>}
    </div>
  );
}

export function Tile({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: "gain" | "loss" | "flat";
}) {
  return (
    <div className="card tile">
      <div className="label">{label}</div>
      <div className={`value ${tone === "flat" ? "" : (tone ?? "")}`}>{value}</div>
      {hint && <div className="hint">{hint}</div>}
    </div>
  );
}

/** A manifest mismatch is shown, not thrown: the run still renders beneath it.
 *
 *  Only `degraded` — a file present whose content changed — raises a warning.
 *  `partial` is the normal state of a screening window on the VM, which holds
 *  only the curated subset, and gets a quiet note instead; a banner that fires
 *  on every backtest view is one nobody reads when it finally matters. */
export function IntegrityBanner({ reports }: { reports: Record<string, Integrity> }) {
  const entries = Object.entries(reports);
  const degraded = entries.filter(([, report]) => report.status === "degraded");
  const partial = entries.filter(([, report]) => report.status === "partial");

  return (
    <>
      {degraded.length > 0 && (
        <div className="banner warn">
          <span aria-hidden>⚠</span>
          <div>
            <strong>Artifact content has changed since it was written</strong>
            {degraded.map(([name, report]) => (
              <p key={name}>
                <code>{name}</code> — changed: {report.mismatched.join(", ")}
              </p>
            ))}
          </div>
        </div>
      )}
      {partial.length > 0 && (
        <div className="banner">
          <span aria-hidden>ⓘ</span>
          <div>
            <strong>Curated subset</strong>
            {partial.map(([name, report]) => (
              <p key={name}>
                <code>{name}</code> — {report.detail}. The raw per-revision
                projections stay on the research machine.
              </p>
            ))}
          </div>
        </div>
      )}
    </>
  );
}

export function Loading() {
  return <p className="empty">Loading…</p>;
}

export function ErrorCard({ error }: { error: Error }) {
  return (
    <div className="banner warn">
      <span aria-hidden>⚠</span>
      <div>
        <strong>Could not load this view</strong>
        <p>{error.message}</p>
      </div>
    </div>
  );
}
