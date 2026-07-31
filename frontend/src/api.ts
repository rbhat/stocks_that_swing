import { useEffect, useState } from "react";

export class Unauthenticated extends Error {}

async function get<T>(path: string): Promise<T> {
  const response = await fetch(path, { credentials: "same-origin" });
  if (response.status === 401) throw new Unauthenticated("unauthenticated");
  if (!response.ok) throw new Error(`${path} failed: ${response.status}`);
  return (await response.json()) as T;
}

export type Loaded<T> = {
  data: T | null;
  error: Error | null;
  loading: boolean;
};

/** Fetch `path` whenever it changes. A 401 surfaces as `Unauthenticated`,
 *  which the app turns into a redirect to /login rather than an error card. */
export function useApi<T>(path: string | null): Loaded<T> {
  const [state, setState] = useState<Loaded<T>>({
    data: null,
    error: null,
    loading: path !== null,
  });

  useEffect(() => {
    if (path === null) {
      setState({ data: null, error: null, loading: false });
      return;
    }
    let live = true;
    setState((prev) => ({ ...prev, loading: true }));
    get<T>(path)
      .then((data) => live && setState({ data, error: null, loading: false }))
      .catch(
        (error: Error) => live && setState({ data: null, error, loading: false }),
      );
    return () => {
      live = false;
    };
  }, [path]);

  return state;
}

export async function passwordLogin(
  username: string,
  password: string,
): Promise<void> {
  const body = new FormData();
  body.append("username", username);
  body.append("password", password);
  const response = await fetch("/auth/password", {
    method: "POST",
    body,
    credentials: "same-origin",
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(detail.error === "bad_credentials" ? "Incorrect username or password." : "Sign-in failed.");
  }
}

export async function logout(): Promise<void> {
  await fetch("/auth/logout", { method: "POST", credentials: "same-origin" });
}
