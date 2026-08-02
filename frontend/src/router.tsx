import { createContext, useCallback, useContext, useEffect, useState } from "react";

/* A ~40-line history router. The dashboard has five routes and the FastAPI
 * app already falls back to index.html for every path, so a routing library
 * would be more dependency than navigation. */

type RouterValue = { path: string; navigate: (to: string) => void };

const RouterContext = createContext<RouterValue>({
  path: "/",
  navigate: () => {},
});

export function RouterProvider({ children }: { children: React.ReactNode }) {
  const [path, setPath] = useState(() => window.location.pathname);

  useEffect(() => {
    const onPop = () => setPath(window.location.pathname);
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const navigate = useCallback((to: string) => {
    if (to === window.location.pathname) return;
    window.history.pushState({}, "", to);
    setPath(to);
  }, []);

  return <RouterContext.Provider value={{ path, navigate }}>{children}</RouterContext.Provider>;
}

export function useRouter(): RouterValue {
  return useContext(RouterContext);
}

type LinkProps = {
  to: string;
  className?: string;
  children: React.ReactNode;
};

export function Link({ to, className, children }: LinkProps) {
  const { path, navigate } = useRouter();
  const active = path === to || (to !== "/" && to !== "/legacy" && path.startsWith(`${to}/`));
  return (
    <a
      href={to}
      className={[className, active ? "active" : ""].filter(Boolean).join(" ")}
      onClick={(event) => {
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
        event.preventDefault();
        navigate(to);
      }}
    >
      {children}
    </a>
  );
}
