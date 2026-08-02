import { useEffect, useState } from "react";
import { post, useApi } from "../api";
import { ErrorCard, Loading, PageHead } from "../components/Layout";
import type { LegacyJob, Me } from "../types";
import { LegacyNav } from "./LegacyNav";

type SyncState = { id: string; status: string; updated_at?: string; returncode?: number };

export function LegacyJobs() {
  const jobs = useApi<LegacyJob[]>("/api/legacy/jobs");
  const me = useApi<Me>("/api/me");
  const [sync, setSync] = useState<SyncState | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!sync || sync.status !== "running") return;
    const timer = window.setInterval(async () => {
      const response = await fetch(`/api/legacy/sync/${sync.id}`, { credentials: "same-origin" });
      if (response.ok) setSync(await response.json() as SyncState);
    }, 2000);
    return () => window.clearInterval(timer);
  }, [sync]);
  if (jobs.loading) return <Loading />;
  if (jobs.error) return <ErrorCard error={jobs.error} />;
  if (!jobs.data) return null;

  async function start() {
    setError(null);
    try { setSync({ ...(await post<{ id: string }>("/api/legacy/sync")), status: "running" }); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Sync failed to start."); }
  }

  return (
    <>
      <LegacyNav />
      <PageHead title="Legacy jobs" subtitle="Retired pipeline status and a narrowly scoped manual artifact sync." />
      <div className="table-wrap"><table><thead><tr><th>Job</th><th>Status</th><th>Last run</th><th>Next run (PT)</th></tr></thead><tbody>
        {jobs.data.map((job) => <tr key={job.name}><td>{job.name}</td><td><span className={`badge ${job.status === "failed" ? "warn" : job.status === "ok" ? "accent" : ""}`}>{job.status}</span></td><td>{job.last_run ?? "—"}</td><td>{job.next_run ?? "—"}</td></tr>)}
      </tbody></table></div>
      <section className="section"><h2>Manual sync</h2><div className="card admin-action"><div><strong>Sync legacy artifacts</strong><p className="muted">Runs the retained sync command in an isolated sidecar. It cannot invoke the v1 scheduler.</p></div>
        <button className="button link" disabled={me.data?.role !== "admin" || sync?.status === "running"} onClick={start}>Run sync</button>
        {sync && <span className="badge">{sync.id} · {sync.status}</span>}
      </div>{error && <p className="error">{error}</p>}{me.data?.role !== "admin" && <p className="muted">Viewer access is read-only.</p>}</section>
    </>
  );
}
