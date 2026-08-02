import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import "./styles.css";
import { Unauthenticated, useApi } from "./api";
import { RouterProvider, useRouter } from "./router";
import { Shell, ErrorCard, Loading } from "./components/Layout";
import { Overview } from "./views/Overview";
import { Forward } from "./views/Forward";
import { Backtests } from "./views/Backtests";
import { ProjectReportView } from "./views/ProjectReport";
import { LegacyBacktests } from "./views/LegacyBacktests";
import { LegacyConfig } from "./views/LegacyConfig";
import { LegacyForward } from "./views/LegacyForward";
import { LegacyJobs } from "./views/LegacyJobs";
import { LegacyOverview } from "./views/LegacyOverview";
import { Login } from "./views/Login";
import type { Me } from "./types";

function Routes({ path }: { path: string }) {
  if (path === "/" || path === "") return <Overview />;
  if (path === "/forward") return <Forward cohort={null} />;
  if (path.startsWith("/forward/")) return <Forward cohort={path.slice("/forward/".length)} />;
  if (path === "/backtests") return <Backtests window={null} />;
  if (path.startsWith("/backtests/"))
    return <Backtests window={path.slice("/backtests/".length)} />;
  if (path === "/project-report") return <ProjectReportView />;
  if (path === "/legacy") return <LegacyOverview />;
  if (path === "/legacy/forward" || path === "/legacy/forward/")
    return <LegacyForward family="h1" />;
  if (path.startsWith("/legacy/forward/"))
    return <LegacyForward family={path.slice("/legacy/forward/".length)} />;
  if (path === "/legacy/backtests") return <LegacyBacktests family={null} />;
  if (path.startsWith("/legacy/backtests/"))
    return <LegacyBacktests family={path.slice("/legacy/backtests/".length)} />;
  if (path === "/legacy/config") return <LegacyConfig />;
  if (path === "/legacy/jobs") return <LegacyJobs />;
  return <p className="empty">No such page.</p>;
}

function App() {
  const { path } = useRouter();
  const me = useApi<Me>(path === "/login" ? null : "/api/me");

  if (path === "/login") return <Login />;
  if (me.error instanceof Unauthenticated) {
    window.location.href = "/login";
    return null;
  }
  if (me.loading) return <Loading />;
  if (me.error) return <ErrorCard error={me.error} />;

  return (
    <Shell email={me.data?.email ?? null}>
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
