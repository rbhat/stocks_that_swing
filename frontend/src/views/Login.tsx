import { useState } from "react";
import { passwordLogin } from "../api";

export function Login() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await passwordLogin(username, password);
      window.location.href = "/";
    } catch (caught) {
      setError((caught as Error).message);
      setBusy(false);
    }
  }

  return (
    <div className="login">
      <div className="card">
        <h1>Swing ranking v1</h1>
        <p className="sub">Sign in to view the forward ledger and the sealed backtests.</p>

        {/* Google is a full-page navigation, not fetch: authlib sets OAuth
         * state in the session cookie and redirects to accounts.google.com. */}
        <a className="button" href="/auth/google">
          Continue with Google
        </a>

        <div className="divider">or</div>

        {error && <p className="error">{error}</p>}

        <form onSubmit={submit}>
          <div className="field">
            <label htmlFor="username">Username</label>
            <input
              id="username"
              type="text"
              autoComplete="username"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              required
            />
          </div>
          <div className="field">
            <label htmlFor="password">Password</label>
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
            />
          </div>
          <button className="button secondary" type="submit" disabled={busy}>
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </div>
    </div>
  );
}
