import { useEffect, useState } from "react";
import { put, useApi } from "../api";
import { ErrorCard, Loading, PageHead } from "../components/Layout";
import type { LegacyConfig as Payload, Me } from "../types";
import { LegacyNav } from "./LegacyNav";

export function LegacyConfig() {
  const { data, error, loading } = useApi<Payload>("/api/legacy/config");
  const me = useApi<Me>("/api/me");
  const [settings, setSettings] = useState<Record<string, boolean | number>>({});
  const [message, setMessage] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  useEffect(() => { if (data) setSettings(data.editable); }, [data]);
  if (loading) return <Loading />;
  if (error) return <ErrorCard error={error} />;
  if (!data) return null;

  async function save() {
    setSaving(true); setMessage(null);
    try {
      const updated = await put<Record<string, boolean | number>>("/api/legacy/config/safe", settings);
      setSettings(updated); setMessage("Legacy settings saved and audited.");
    } catch (cause) { setMessage(cause instanceof Error ? cause.message : "Save failed."); }
    finally { setSaving(false); }
  }

  return (
    <>
      <LegacyNav />
      <PageHead title="Legacy configuration" subtitle="Secrets are redacted. Strategy and preregistration inputs remain read-only." />
      <div className="grid-2">
        <section className="card"><h3>Environment</h3><div className="key-values">{Object.entries(data.env).map(([key, value]) => <div key={key}><code>{key}</code><span>{value}</span></div>)}{!Object.keys(data.env).length && <p className="muted">No redacted environment snapshot is mounted.</p>}</div></section>
        <section className="card"><h3>Allowlisted settings</h3>
          {Object.entries(data.schema).map(([key, constraint]) => <div className="field" key={key}>
            <label htmlFor={`setting-${key}`}>{key} · {constraint}</label>
            {constraint === "bool" ? <input id={`setting-${key}`} type="checkbox" checked={Boolean(settings[key])} disabled={me.data?.role !== "admin"} onChange={(event) => setSettings({ ...settings, [key]: event.target.checked })} /> :
              <input id={`setting-${key}`} type="number" min="0" max="0.5" step="0.001" value={Number(settings[key] ?? 0)} disabled={me.data?.role !== "admin"} onChange={(event) => setSettings({ ...settings, [key]: Number(event.target.value) })} />}
          </div>)}
          {message && <p className={message.includes("saved") ? "muted" : "error"}>{message}</p>}
          <button className="button" disabled={saving || me.data?.role !== "admin"} onClick={save}>{saving ? "Saving…" : "Save allowlisted settings"}</button>
          {me.data?.role !== "admin" && <p className="muted">Viewer access is read-only.</p>}
        </section>
      </div>
      <section className="section"><h2>Universe</h2><div className="card"><pre className="report">{JSON.stringify(data.universe, null, 2)}</pre></div></section>
      <section className="section"><h2>Study roster</h2><div className="card"><pre className="report">{JSON.stringify(data.study_roster, null, 2)}</pre></div></section>
    </>
  );
}
