import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import "./styles.css";
import { Unauthenticated, useApi } from "./api";
import { RouterProvider, useRouter } from "./router";
import { Shell, ErrorCard, Loading } from "./components/Layout";
import { Overview } from "./views/Overview";
import { Forward } from "./views/Forward";
import { Backtests } from "./views/Backtests";
import { Login } from "./views/Login";
import type { Me, Overview as OverviewPayload } from "./types";

function Routes({ path }: { path: string }) {
  if (path === "/" || path === "") return <Overview />;
  if (path === "/forward") return <Forward cohort={null} />;
  if (path.startsWith("/forward/")) return <Forward cohort={path.slice("/forward/".length)} />;
  if (path === "/backtests") return <Backtests window={null} />;
  if (path.startsWith("/backtests/"))
    return <Backtests window={path.slice("/backtests/".length)} />;
  return <p className="empty">No such page.</p>;
}

function App() {
  const { path } = useRouter();
  const me = useApi<Me>(path === "/login" ? null : "/api/me");
  // The overview is fetched here only for the legacy link, which the shell
  // renders on every page; the views fetch their own data.
  const overview = useApi<OverviewPayload>(path === "/login" ? null : "/api/overview");

  if (path === "/login") return <Login />;
  if (me.error instanceof Unauthenticated) {
    window.location.href = "/login";
    return null;
  }
  if (me.loading) return <Loading />;
  if (me.error) return <ErrorCard error={me.error} />;

  return (
    <Shell
      email={me.data?.email ?? null}
      legacyUrl={overview.data?.legacy_dashboard_url ?? "http://127.0.0.1:8000"}
    >
      <Routes path={path} />
    </Shell>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <RouterProvider>
      <App />
    </RouterProvider>
  </StrictMode>,
);
