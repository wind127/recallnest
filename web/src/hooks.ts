import { useEffect, useRef, useState } from "react";
import { api, errorText } from "./api";
export function useResource<T>(path: string | null) {
  const [version, setVersion] = useState(0);
  const [state, setState] = useState<{
    path: string | null;
    version: number;
    data?: T;
    busy: boolean;
    error: string;
  }>({ path: null, version: -1, busy: false, error: "" });
  useEffect(() => {
    const controller = new AbortController();
    let current = true;
    setState({ path, version, busy: !!path, error: "" });
    if (!path) return;
    api
      .get<T>(path, controller.signal)
      .then((value) => {
        if (current)
          setState({ path, version, data: value, busy: false, error: "" });
      })
      .catch((e) => {
        if (current && e.name !== "AbortError")
          setState({ path, version, busy: false, error: errorText(e) });
      });
    return () => {
      current = false;
      controller.abort();
    };
  }, [path, version]);
  // Mask an old response synchronously during render, before effects run. A
  // consumer's selection effect must never observe it under the new query.
  const active =
    state.path === path && state.version === version
      ? state
      : { data: undefined, busy: !!path, error: "" };
  return {
    data: active.data,
    busy: active.busy,
    error: active.error,
    refresh: () => setVersion((v) => v + 1),
  };
}
export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const mounted = useRef(true);
  const pending = useRef(false);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  async function run(task: () => Promise<void>) {
    if (pending.current) return;
    pending.current = true;
    setBusy(true);
    setError("");
    try {
      await task();
    } catch (e) {
      if (mounted.current) setError(errorText(e));
    } finally {
      pending.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  return { busy, error, run, setError };
}
